from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from .models import Role
from .session_manager import session_manager, SessionRoom
from .video_processor.pipeline import VideoProcessor
from .audio_processor.pipeline import AudioProcessor
from .metrics_engine.engine import MetricsEngine
from .config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-session resources (created when session starts)
_session_resources: dict[str, dict] = {}


def _trace_recorder(room: SessionRoom):
    return getattr(room, "trace_recorder", None)


def _get_or_create_resources(room: SessionRoom) -> dict:
    """Get or create processing resources for a session."""
    sid = room.session_id
    if sid not in _session_resources:
        _session_resources[sid] = {
            "video_tutor": VideoProcessor(),
            "video_student": VideoProcessor(),
            "audio_tutor": AudioProcessor(),
            "audio_student": AudioProcessor(),
            "metrics_engine": MetricsEngine(sid),
        }
    return _session_resources[sid]


def _cleanup_resources(session_id: str):
    """Clean up processing resources for a session."""
    resources = _session_resources.pop(session_id, None)
    if resources:
        resources["video_tutor"].close()
        resources["video_student"].close()


def _generate_session_summary(room: SessionRoom):
    from .analytics.summary import generate_summary

    return generate_summary(
        room.session_id,
        room.metrics_history,
        tutor_id=room.tutor_id,
        session_type=room.session_type,
        media_provider=room.media_provider,
        nudges=room.nudges_sent,
    )


def _save_session(room: SessionRoom):
    """Persist session summary to storage."""
    try:
        from .analytics.session_store import SessionStore

        summary = _generate_session_summary(room)
        store = SessionStore()
        store.save(summary)
        return summary
    except Exception as e:
        logger.error(f"Failed to save session: {e}")
        return None


def _finalize_session(room: SessionRoom):
    """End session, save data, clean up resources.

    Sends session_end to any still-connected participant via a fire-and-forget task.
    """
    if room.ended_at is not None:
        return  # Already finalized
    room.ended_at = time.time()
    duration = room.elapsed_seconds()
    if room._metrics_task:
        room._metrics_task.cancel()

    summary = _save_session(room)
    if summary is None:
        try:
            summary = _generate_session_summary(room)
        except Exception:
            summary = None

    recorder = _trace_recorder(room)
    if recorder is not None:
        recorder.record_event(
            "session_end",
            data={
                "session_id": room.session_id,
                "duration_seconds": duration,
            },
        )
        if summary is not None:
            recorder.finalize(summary=summary, duration_seconds=duration)

    _cleanup_resources(room.session_id)
    logger.info(f"Session {room.session_id}: finalized")

    # Notify any still-connected participants
    async def _notify():
        for p in room.participants.values():
            if p.connected and p.websocket:
                try:
                    await p.websocket.send_json({
                        "type": "session_end",
                        "data": {
                            "session_id": room.session_id,
                            "duration_seconds": duration,
                        },
                    })
                    await p.websocket.close(code=1000, reason="Session ended")
                except Exception:
                    pass

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_notify())
    except RuntimeError:
        pass  # No event loop — called from sync context (e.g., tests)


async def _grace_period_finalize(room: SessionRoom, role: Role):
    """Wait for reconnect grace period, then finalize if still disconnected."""
    try:
        await asyncio.sleep(settings.reconnect_grace_seconds)
        participant = room.participants[role]
        if not participant.connected and room.ended_at is None:
            if not room.any_connected():
                logger.info(
                    f"Session {room.session_id}: grace period expired for {role.value}, "
                    "no participants connected — finalizing"
                )
                _finalize_session(room)
            else:
                logger.info(
                    f"Session {room.session_id}: {role.value} did not reconnect, "
                    "but other participant still connected"
                )
    except asyncio.CancelledError:
        pass  # Reconnect happened, grace cancelled


def _opposite_role(role: Role) -> Role:
    return Role.STUDENT if role == Role.TUTOR else Role.TUTOR


async def _send_json_to_role(
    room: SessionRoom,
    role: Role,
    message_type: str,
    data: dict,
):
    participant = room.participants[role]
    if participant.connected and participant.websocket:
        try:
            await participant.websocket.send_json({
                "type": message_type,
                "data": data,
            })
        except Exception:
            pass


async def _send_json_to_other_participant(
    room: SessionRoom,
    source_role: Role,
    message_type: str,
    data: dict,
):
    await _send_json_to_role(room, _opposite_role(source_role), message_type, data)


async def _broadcast_json(room: SessionRoom, message_type: str, data: dict):
    for role in (Role.TUTOR, Role.STUDENT):
        await _send_json_to_role(room, role, message_type, data)


async def _handle_text_message(room: SessionRoom, role: Role, text: str):
    """Handle JSON control messages on the session websocket.

    Text frames are reserved for signaling/control. Binary frames continue to carry
    analytics media payloads.
    """
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return

    message_type = message.get("type")
    data = message.get("data") or {}

    if message_type == "client_status":
        participant = room.participants[role]
        if "audio_muted" in data:
            participant.audio_muted = bool(data["audio_muted"])
        if "video_enabled" in data:
            participant.video_enabled = bool(data["video_enabled"])
        if "tab_hidden" in data:
            participant.tab_hidden = bool(data["tab_hidden"])
        return

    if message_type != "webrtc_signal":
        return

    signal_type = data.get("signal_type")
    if signal_type not in {"offer", "answer", "ice_candidate"}:
        return

    payload = data.get("payload")
    if not isinstance(payload, dict):
        return

    recorder = _trace_recorder(room)
    if recorder is not None:
        recorder.record_webrtc_signal(
            role=role.value,
            signal_type=signal_type,
            payload=payload,
        )

    await _send_json_to_other_participant(
        room,
        role,
        "webrtc_signal",
        {
            "session_id": room.session_id,
            "from_role": role.value,
            "signal_type": signal_type,
            "payload": payload,
        },
    )


@router.websocket("/ws/session/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
):
    room = session_manager.get_session(session_id)
    if room is None:
        await websocket.close(code=4004, reason="Session not found")
        return

    role = room.get_role_for_token(token)
    if role is None:
        await websocket.close(code=4001, reason="Invalid token")
        return

    participant = room.participants[role]

    if participant.connected:
        await websocket.close(code=4002, reason="Role already connected")
        return

    if room.ended_at is not None:
        await websocket.close(code=4003, reason="Session already ended")
        return

    was_reconnecting = participant.disconnected_at is not None

    await websocket.accept()
    participant.websocket = websocket
    participant.connected = True
    participant.disconnected_at = None
    participant.last_speech_update = time.time()

    # Cancel any pending grace-period finalization (reconnect!)
    room.cancel_grace_task(role)

    logger.info(f"Session {session_id}: {role.value} connected")
    recorder = _trace_recorder(room)
    if recorder is not None:
        recorder.record_event(f"{role.value}_connected", role=role.value)

    if was_reconnecting:
        await _send_json_to_other_participant(
            room,
            role,
            "participant_reconnected",
            {
                "role": role.value,
                "session_id": session_id,
            },
        )
        if recorder is not None:
            recorder.record_event(
                "participant_reconnected",
                role=role.value,
                data={"session_id": session_id},
            )

    # Start session analysis when both are connected
    if room.both_connected():
        if room.started_at is None:
            room.started_at = time.time()
            if recorder is not None:
                recorder.mark_started()
            logger.info(f"Session {session_id}: both participants connected, analysis started")
            room._metrics_task = asyncio.create_task(
                _metrics_emit_loop(room)
            )

        ready_payload = {
            "role": role.value,
            "session_id": session_id,
            "reconnected": was_reconnecting,
        }
        if recorder is not None:
            recorder.record_event(
                "participant_ready",
                role=role.value,
                data=ready_payload,
            )
        await _broadcast_json(
            room,
            "participant_ready",
            ready_payload,
        )

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()

            data = message.get("bytes")
            if data is not None:
                if len(data) < 2:
                    continue

                msg_type = data[0]
                payload = data[1:]

                if msg_type == 0x01:
                    await _process_video_frame(room, role, payload)
                elif msg_type == 0x02:
                    await _process_audio_chunk(room, role, payload)
                continue

            text = message.get("text")
            if text is not None:
                await _handle_text_message(room, role, text)
                continue

    except WebSocketDisconnect:
        logger.info(f"Session {session_id}: {role.value} disconnected")
    except Exception as e:
        logger.error(f"Session {session_id}: error for {role.value}: {e}")
    finally:
        participant.connected = False
        participant.websocket = None
        participant.disconnected_at = time.time()

        if room.started_at is not None and room.ended_at is None:
            disconnect_payload = {
                "role": role.value,
                "session_id": session_id,
                "grace_seconds": settings.reconnect_grace_seconds,
            }
            recorder = _trace_recorder(room)
            if recorder is not None:
                recorder.record_event(
                    "participant_disconnected",
                    role=role.value,
                    data=disconnect_payload,
                )

            # Start grace period instead of immediate finalization
            grace_task = asyncio.create_task(
                _grace_period_finalize(room, role)
            )
            room._grace_tasks[role.value] = grace_task

            await _send_json_to_other_participant(
                room,
                role,
                "participant_disconnected",
                disconnect_payload,
            )


async def _process_video_frame(room: SessionRoom, role: Role, payload: bytes):
    """Process a video frame through the full pipeline."""
    if not room.should_process_video_frame(role):
        return

    resources = _get_or_create_resources(room)
    processor = resources[f"video_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    deg_level = room.degradation_level
    skip_expression = deg_level >= 2
    skip_gaze = deg_level >= 3

    result = processor.process_frame(
        payload,
        skip_expression=skip_expression,
        skip_gaze=skip_gaze,
    )

    now = time.time()
    if result.gaze is not None:
        engine.update_gaze(
            role,
            now,
            result.gaze.on_camera,
            result.gaze.horizontal_angle_deg,
            result.gaze.vertical_angle_deg,
        )
    else:
        engine.update_visual_observation(
            role,
            now,
            face_detected=result.face_detected,
        )
    if result.expression is not None:
        engine.update_expression(role, result.expression.valence)

    recorder = _trace_recorder(room)
    if recorder is not None:
        visual_signal = engine.current_visual_signal(role, now)
        recorder.record_visual_signal(
            role=role.value,
            face_present=result.face_detected,
            gaze_on_camera=result.gaze.on_camera if result.gaze is not None else None,
            attention_state=visual_signal.get("attention_state"),
            confidence=float(visual_signal.get("confidence", 0.0)),
        )

    room.record_processing_time(result.total_ms)
    room.record_stage_times(
        decode_ms=result.decode_ms,
        facemesh_ms=result.facemesh_ms,
        gaze_ms=result.gaze_ms,
        expression_ms=result.expression_ms,
    )
    previous_degradation = room.degradation_level
    room.check_degradation()
    if recorder is not None and room.degradation_level != previous_degradation:
        recorder.record_event(
            "degradation_changed",
            data={
                "previous_level": previous_degradation,
                "new_level": room.degradation_level,
                "target_fps": room.current_fps,
            },
        )


async def _process_audio_chunk(room: SessionRoom, role: Role, payload: bytes):
    """Process an audio chunk through VAD and prosody."""
    resources = _get_or_create_resources(room)
    processor = resources[f"audio_{role.value}"]
    engine: MetricsEngine = resources["metrics_engine"]

    participant = room.participants[role]
    result = processor.process_chunk(
        payload,
        force_muted=participant.audio_muted,
    )

    audio_timestamp = time.time()
    state_changed = engine.update_audio(
        role,
        audio_timestamp,
        result.is_speech,
        result.prosody.rms_energy,
        result.prosody.speech_rate_proxy,
        rms_db=result.prosody.rms_db,
    )

    recorder = _trace_recorder(room)
    if recorder is not None:
        recorder.record_audio_signal(
            role=role.value,
            speech_active=result.is_speech,
            rms_db=result.prosody.rms_db,
            noise_floor_db=result.noise_floor_db,
        )
        for event in engine.drain_overlap_events():
            overlap_type = "meaningful"
            if event.echo_like:
                overlap_type = "echo_suspected"
            elif event.hard:
                overlap_type = "hard"
            elif event.backchannel:
                overlap_type = "backchannel"
            recorder.record_overlap_segment(
                start_t_ms=recorder.to_t_ms(event.timestamp),
                end_t_ms=recorder.to_t_ms(event.timestamp + event.duration_s),
                overlap_type=overlap_type,
            )

    if state_changed:
        await _emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=False,
            min_interval_seconds=settings.live_metrics_min_emit_interval_seconds,
        )


async def _emit_metrics_snapshot(
    room: SessionRoom,
    *,
    record_history: bool,
    allow_coaching: bool,
    min_interval_seconds: float = 0.0,
):
    """Send a metrics snapshot to the tutor, optionally recording/coaching.

    The periodic loop records analytics history and evaluates coaching rules.
    Fast-path emits from audio updates are UI-only and intentionally skip both.
    """
    if room.ended_at is not None:
        return None

    now = time.time()
    if (
        min_interval_seconds > 0
        and now - room._last_metrics_emit_at < min_interval_seconds
    ):
        return None

    resources = _session_resources.get(room.session_id)
    if not resources:
        return None

    engine: MetricsEngine = resources["metrics_engine"]

    aggregation_start = time.time()
    snapshot = engine.compute_snapshot(
        degraded=room.degradation_level > 0,
        gaze_unavailable=room.degradation_level >= 3,
        processing_ms=room.rolling_avg_processing_ms(),
        target_fps=room.current_fps,
    )
    room.record_aggregation_time((time.time() - aggregation_start) * 1000)

    metrics_index = None
    if record_history:
        room.metrics_history.append(snapshot)
        metrics_index = len(room.metrics_history) - 1
        recorder = _trace_recorder(room)
        if recorder is not None:
            recorder.record_metrics_snapshot(snapshot)

    tutor = room.participants[Role.TUTOR]
    if tutor.connected and tutor.websocket:
        try:
            await tutor.websocket.send_json({
                "type": "metrics",
                "data": snapshot.model_dump(mode="json"),
            })
            room._last_metrics_emit_at = now
        except Exception as e:
            logger.error(f"Failed to send metrics to tutor: {e}")

    if not allow_coaching:
        return snapshot

    try:
        from .coaching_system.coach import Coach

        coach = resources.get("coach")
        if coach is None:
            coach = Coach()
            resources["coach"] = coach
        evaluation = coach.evaluate(snapshot, room.elapsed_seconds())
        recorder = _trace_recorder(room)
        if recorder is not None:
            recorder.record_coaching_decision(
                candidate_nudges=evaluation.candidate_nudges,
                emitted_nudge=evaluation.emitted_nudge_type,
                suppressed_reasons=evaluation.suppressed_reasons,
                metrics_index=metrics_index,
                trigger_features=evaluation.trigger_features,
            )

        for nudge in evaluation.nudges:
            room.nudges_sent.append(nudge)
            if recorder is not None:
                recorder.record_nudge(nudge)
            if tutor.connected and tutor.websocket:
                try:
                    await tutor.websocket.send_json({
                        "type": "nudge",
                        "data": nudge.model_dump(mode="json"),
                    })
                except Exception:
                    pass
    except ImportError:
        pass

    return snapshot


async def _metrics_emit_loop(room: SessionRoom):
    """Emit MetricsSnapshot on the normal periodic cadence."""
    try:
        while room.ended_at is None:
            await asyncio.sleep(settings.metrics_emit_interval_seconds)

            if room.ended_at is not None:
                break

            await _emit_metrics_snapshot(
                room,
                record_history=True,
                allow_coaching=True,
            )

    except asyncio.CancelledError:
        pass
