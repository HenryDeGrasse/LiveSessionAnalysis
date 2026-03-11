from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from livekit import rtc

from .config import settings
from .livekit import (
    build_livekit_worker_join_payload,
    livekit_analytics_worker_enabled,
    livekit_identity,
    livekit_role_for_identity,
)
from .models import Role
from .session_manager import SessionRoom
from .session_runtime import process_audio_chunk, process_video_frame_array

logger = logging.getLogger(__name__)

LIVEKIT_WORKER_AUDIO_SAMPLE_RATE = 16000
LIVEKIT_WORKER_AUDIO_CHANNELS = 1


async def _await_if_needed(result):
    if inspect.isawaitable(result):
        return await result
    return result


TOPIC_METRICS = "lsa.metrics.v1"
TOPIC_NUDGE = "lsa.nudge.v1"

_workers: dict[str, "LiveKitAnalyticsWorker"] = {}


@dataclass
class LiveKitAnalyticsWorker:
    session: SessionRoom
    room: rtc.Room | None = None
    task: asyncio.Task | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    _track_tasks: dict[str, asyncio.Task] = field(default_factory=dict)

    def start(self) -> asyncio.Task:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run())
        return self.task

    async def publish_data_to_tutor(
        self, payload: bytes, *, topic: str, reliable: bool = True
    ) -> bool:
        """Publish a data packet to the tutor participant only.

        Returns True if the packet was sent, False if the worker isn't connected.
        """
        room = self.room
        if room is None:
            return False
        try:
            tutor_identity = livekit_identity(
                self.session.session_id, Role.TUTOR
            )
            await room.local_participant.publish_data(
                payload,
                reliable=reliable,
                destination_identities=[tutor_identity],
                topic=topic,
            )
            return True
        except Exception as exc:
            logger.debug(
                "Session %s: failed to publish data packet (topic=%s): %s",
                self.session.session_id,
                topic,
                exc,
            )
            return False

    def request_stop(self):
        self.stop_event.set()
        room = self.room
        if room is not None:
            try:
                disconnect_result = room.disconnect()
                if inspect.isawaitable(disconnect_result):
                    try:
                        asyncio.create_task(disconnect_result)
                    except RuntimeError:
                        pass
            except Exception:
                pass
        for task in list(self._track_tasks.values()):
            task.cancel()

    async def run(self):
        join = build_livekit_worker_join_payload(self.session)
        room = rtc.Room()
        self.room = room
        self.session.livekit_worker_last_error = None

        room.on("connected", self._on_connected)
        room.on("disconnected", self._on_disconnected)
        room.on("participant_connected", self._on_participant_connected)
        room.on("participant_disconnected", self._on_participant_disconnected)
        room.on("track_subscribed", self._on_track_subscribed)
        room.on("track_unsubscribed", self._on_track_unsubscribed)
        room.on("track_subscription_failed", self._on_track_subscription_failed)

        try:
            await _await_if_needed(room.connect(join["url"], join["token"]))
            logger.info(
                "Session %s: livekit analytics worker connected to %s",
                self.session.session_id,
                join["room_name"],
            )
            await self._subscribe_existing_tracks()
            await self.stop_event.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.session.livekit_worker_last_error = str(exc)
            logger.exception(
                "Session %s: livekit analytics worker failed",
                self.session.session_id,
            )
            raise
        finally:
            await self._shutdown()

    async def _shutdown(self):
        self.stop_event.set()
        track_tasks = list(self._track_tasks.values())
        self._track_tasks.clear()
        for task in track_tasks:
            task.cancel()
        for task in track_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        room = self.room
        self.room = None
        if room is not None:
            try:
                await _await_if_needed(room.disconnect())
            except Exception:
                pass

    def _on_connected(self):
        self.session.livekit_worker_connected_at = time.time()
        logger.info(
            "Session %s: livekit analytics worker room connected",
            self.session.session_id,
        )

    def _on_disconnected(self, *_args: Any):
        logger.info(
            "Session %s: livekit analytics worker room disconnected",
            self.session.session_id,
        )
        self.stop_event.set()

    def _on_participant_connected(self, participant):
        logger.info(
            "Session %s: livekit worker saw participant connected %s",
            self.session.session_id,
            getattr(participant, "identity", "unknown"),
        )

    def _on_participant_disconnected(self, participant):
        logger.info(
            "Session %s: livekit worker saw participant disconnected %s",
            self.session.session_id,
            getattr(participant, "identity", "unknown"),
        )

    def _on_track_subscribed(self, track, publication, participant):
        track_sid = getattr(publication, "sid", "") or getattr(track, "sid", "")
        if not isinstance(track_sid, str) or not track_sid:
            return
        if track_sid in self._track_tasks:
            return

        role_result = self._role_and_index_for_participant(participant)
        if role_result is None:
            return
        role, student_index = role_result

        task = asyncio.create_task(
            self._consume_track(
                track=track,
                track_sid=track_sid,
                role=role,
                student_index=student_index,
            )
        )
        self._track_tasks[track_sid] = task
        task.add_done_callback(lambda _task, sid=track_sid: self._track_tasks.pop(sid, None))

    def _on_track_unsubscribed(self, track, publication, participant):
        track_sid = getattr(publication, "sid", "") or getattr(track, "sid", "")
        task = self._track_tasks.pop(track_sid, None)
        if task is not None:
            task.cancel()

    def _on_track_subscription_failed(self, participant, track_sid, error):
        logger.warning(
            "Session %s: livekit worker failed to subscribe to %s from %s: %s",
            self.session.session_id,
            track_sid,
            getattr(participant, "identity", "unknown"),
            error,
        )
        self.session.livekit_worker_last_error = str(error)

    async def _subscribe_existing_tracks(self):
        room = self.room
        if room is None:
            return

        remote_participants = getattr(room, "remote_participants", {})
        for participant in list(remote_participants.values()):
            role_result = self._role_and_index_for_participant(participant)
            if role_result is None:
                continue
            for publication in getattr(participant, "track_publications", {}).values():
                track = getattr(publication, "track", None)
                if track is None:
                    continue
                self._on_track_subscribed(track, publication, participant)

    def _role_and_index_for_participant(
        self, participant
    ) -> "tuple[Role, int] | None":
        """Return (role, student_index) for a LiveKit participant, or None."""
        identity = getattr(participant, "identity", "")
        if not isinstance(identity, str):
            return None
        return livekit_role_for_identity(self.session.session_id, identity)

    def _role_for_participant(self, participant) -> "Role | None":
        """Legacy helper kept for external callers; returns only the role."""
        result = self._role_and_index_for_participant(participant)
        return result[0] if result is not None else None

    async def _consume_track(
        self, *, track, track_sid: str, role: Role, student_index: int = 0
    ):
        if isinstance(track, rtc.RemoteAudioTrack):
            await self._consume_audio_track(
                track_sid=track_sid,
                track=track,
                role=role,
                student_index=student_index,
            )
            return
        if isinstance(track, rtc.RemoteVideoTrack):
            await self._consume_video_track(
                track_sid=track_sid,
                track=track,
                role=role,
                student_index=student_index,
            )
            return

    async def _consume_audio_track(
        self, *, track_sid: str, track, role: Role, student_index: int = 0
    ):
        stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=LIVEKIT_WORKER_AUDIO_SAMPLE_RATE,
            num_channels=LIVEKIT_WORKER_AUDIO_CHANNELS,
        )
        try:
            async for event in stream:
                pcm = pcm_bytes_from_audio_frame(event.frame)
                if pcm:
                    await process_audio_chunk(
                        self.session, role, pcm, student_index=student_index
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Session %s: livekit worker audio consumer failed for %s: %s",
                self.session.session_id,
                track_sid,
                exc,
            )
            self.session.livekit_worker_last_error = str(exc)
        finally:
            await stream.aclose()

    async def _consume_video_track(
        self, *, track_sid: str, track, role: Role, student_index: int = 0
    ):
        stream = rtc.VideoStream.from_track(
            track=track,
            format=rtc.VideoBufferType.RGB24,
            capacity=1,
        )
        try:
            async for event in stream:
                frame_bgr = bgr_frame_from_video_frame(event.frame)
                await process_video_frame_array(
                    self.session, role, frame_bgr, student_index=student_index
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Session %s: livekit worker video consumer failed for %s: %s",
                self.session.session_id,
                track_sid,
                exc,
            )
            self.session.livekit_worker_last_error = str(exc)
        finally:
            await stream.aclose()


def maybe_start_livekit_analytics_worker(room: SessionRoom) -> bool:
    if not livekit_analytics_worker_enabled(room):
        return False
    if room.started_at is None or room.ended_at is not None:
        return False

    tutor = room.participants[Role.TUTOR]
    any_student_connected = any(
        participant.livekit_connected for _idx, participant in room.all_student_participants()
    )
    webhooks_seen = room.livekit_last_webhook_at is not None
    if webhooks_seen and (not tutor.livekit_connected or not any_student_connected):
        return False

    existing = _workers.get(room.session_id)
    if existing is not None and existing.task is not None and not existing.task.done():
        return False

    room.livekit_worker_started_at = time.time()
    room.livekit_worker_last_error = None
    worker = LiveKitAnalyticsWorker(session=room)
    task = worker.start()
    _workers[room.session_id] = worker

    def _cleanup(done_task: asyncio.Task):
        current = _workers.get(room.session_id)
        if current is worker:
            _workers.pop(room.session_id, None)
        try:
            done_task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    task.add_done_callback(_cleanup)
    return True


def get_active_worker(session_id: str) -> LiveKitAnalyticsWorker | None:
    """Return the active, connected worker for a session, or None."""
    worker = _workers.get(session_id)
    if worker is None:
        return None
    if worker.room is None or worker.task is None or worker.task.done():
        return None
    return worker


def stop_livekit_analytics_worker(session_id: str):
    worker = _workers.pop(session_id, None)
    if worker is not None:
        worker.request_stop()


def reset_livekit_analytics_workers():
    for session_id in list(_workers.keys()):
        stop_livekit_analytics_worker(session_id)


def pcm_bytes_from_audio_frame(frame: rtc.AudioFrame) -> bytes:
    samples = np.frombuffer(frame.data, dtype=np.int16)
    if samples.size == 0:
        return b""

    samples = samples.reshape(frame.samples_per_channel, frame.num_channels)
    mono = samples.mean(axis=1) if frame.num_channels > 1 else samples[:, 0].astype(np.float32)

    if frame.sample_rate != LIVEKIT_WORKER_AUDIO_SAMPLE_RATE:
        source_positions = np.arange(mono.shape[0], dtype=np.float32)
        target_length = max(
            1,
            int(round(mono.shape[0] * LIVEKIT_WORKER_AUDIO_SAMPLE_RATE / frame.sample_rate)),
        )
        target_positions = np.linspace(0, mono.shape[0] - 1, num=target_length, dtype=np.float32)
        mono = np.interp(target_positions, source_positions, mono)

    pcm = np.clip(np.round(mono), -32768, 32767).astype("<i2")
    return pcm.tobytes()


def bgr_frame_from_video_frame(frame: rtc.VideoFrame) -> np.ndarray:
    rgb_frame = (
        frame
        if frame.type == rtc.VideoBufferType.RGB24
        else frame.convert(rtc.VideoBufferType.RGB24)
    )
    rgb = np.frombuffer(rgb_frame.data, dtype=np.uint8).reshape(
        rgb_frame.height,
        rgb_frame.width,
        3,
    )
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
