from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime

from fastapi import WebSocket

from .config import settings
from .models import (
    LatencyStats,
    MediaProvider,
    MetricsSnapshot,
    Nudge,
    Role,
    SessionCreateResponse,
)


@dataclass
class ParticipantState:
    role: Role
    websocket: WebSocket | None = None
    connected: bool = False
    livekit_connected: bool = False
    livekit_identity: str = ""
    livekit_published_tracks: set[str] = field(default_factory=set)
    livekit_last_joined_at: float | None = None
    livekit_last_left_at: float | None = None
    # Video state
    last_gaze_on_camera: bool = False
    gaze_history: list[tuple[float, bool]] = field(default_factory=list)
    expression_valence: float = 0.5
    last_video_processed_at: float | None = None
    # Audio state
    is_speaking: bool = False
    speech_history: list[tuple[float, bool]] = field(default_factory=list)
    rms_energy: float = 0.0
    speech_rate: float = 0.0
    audio_muted: bool = False
    video_enabled: bool = True
    tab_hidden: bool = False
    # Cumulative
    total_speech_seconds: float = 0.0
    last_speech_update: float = 0.0
    # Disconnect tracking
    disconnected_at: float | None = None


@dataclass
class SessionRoom:
    session_id: str
    tutor_token: str
    student_token: str
    tutor_id: str = ""
    session_type: str = "general"
    media_provider: MediaProvider = MediaProvider.CUSTOM_WEBRTC
    livekit_room_name: str = ""
    livekit_room_started_at: float | None = None
    livekit_room_ended_at: float | None = None
    livekit_last_webhook_event: str | None = None
    livekit_last_webhook_at: float | None = None
    livekit_webhook_event_ids: set[str] = field(default_factory=set, repr=False)
    livekit_worker_started_at: float | None = None
    livekit_worker_connected_at: float | None = None
    livekit_worker_last_error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    participants: dict[Role, ParticipantState] = field(default_factory=dict)
    interruption_count: int = 0
    interruption_timestamps: list[float] = field(default_factory=list)
    nudges_sent: list[Nudge] = field(default_factory=list)
    metrics_history: list[MetricsSnapshot] = field(default_factory=list)
    # Latency tracking
    processing_times: list[float] = field(default_factory=list)
    _latency_history: list[float] = field(default_factory=list, repr=False)
    decode_times: list[float] = field(default_factory=list)
    facemesh_times: list[float] = field(default_factory=list)
    gaze_times: list[float] = field(default_factory=list)
    expression_times: list[float] = field(default_factory=list)
    aggregation_times: list[float] = field(default_factory=list)
    dropped_frames: int = 0
    degradation_events: int = 0
    current_fps: int = 3
    degradation_level: int = 0  # 0=normal, 1=reduced fps, 2=no expression, 3=no gaze
    # Metrics emit task
    _metrics_task: asyncio.Task | None = field(default=None, repr=False)
    _last_metrics_emit_at: float = field(default=0.0, repr=False)
    # Grace period tasks per role
    _grace_tasks: dict[str, asyncio.Task] = field(default_factory=dict, repr=False)
    trace_recorder: object | None = field(default=None, repr=False)
    debug_mode: bool = False

    def __post_init__(self):
        self.participants[Role.TUTOR] = ParticipantState(role=Role.TUTOR)
        self.participants[Role.STUDENT] = ParticipantState(role=Role.STUDENT)
        if settings.enable_session_tracing:
            from .observability.trace_recorder import SessionTraceRecorder

            self.trace_recorder = SessionTraceRecorder(
                session_id=self.session_id,
                tutor_id=self.tutor_id,
                session_type=self.session_type,
                created_at=datetime.utcfromtimestamp(self.created_at),
            )

    def get_role_for_token(self, token: str) -> Role | None:
        if token == self.tutor_token:
            return Role.TUTOR
        elif token == self.student_token:
            return Role.STUDENT
        return None

    def both_connected(self) -> bool:
        return all(p.connected for p in self.participants.values())

    def any_connected(self) -> bool:
        return any(p.connected for p in self.participants.values())

    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at or time.time()
        return end - self.started_at

    def record_processing_time(self, ms: float):
        self.processing_times.append(ms)
        if len(self.processing_times) > 5:
            self.processing_times = self.processing_times[-5:]
        self._latency_history.append(ms)
        if len(self._latency_history) > 100:
            self._latency_history = self._latency_history[-100:]

    def rolling_avg_processing_ms(self) -> float:
        if not self.processing_times:
            return 0.0
        return sum(self.processing_times) / len(self.processing_times)

    def latency_percentiles(self) -> tuple[float, float]:
        """Return (p50, p95) of recent processing times in ms."""
        samples = self._latency_history
        if len(samples) < 2:
            avg = self.rolling_avg_processing_ms()
            return (avg, avg)
        sorted_times = sorted(samples)
        n = len(sorted_times)
        p50 = sorted_times[n // 2]
        p95_idx = min(n - 1, int(n * 0.95))
        p95 = sorted_times[p95_idx]
        return (p50, p95)

    def degradation_reason(self) -> str:
        """Human-readable degradation state."""
        if self.degradation_level == 0:
            return "normal"
        elif self.degradation_level == 1:
            return "reduced_fps"
        elif self.degradation_level == 2:
            return "skip_expression"
        else:
            return "skip_gaze_and_expression"

    def _record_rolling_metric(
        self,
        samples: list[float],
        value: float,
        max_samples: int = 20,
    ):
        samples.append(value)
        if len(samples) > max_samples:
            del samples[:-max_samples]

    def record_stage_times(
        self,
        decode_ms: float,
        facemesh_ms: float,
        gaze_ms: float,
        expression_ms: float,
    ):
        self._record_rolling_metric(self.decode_times, decode_ms)
        self._record_rolling_metric(self.facemesh_times, facemesh_ms)
        self._record_rolling_metric(self.gaze_times, gaze_ms)
        self._record_rolling_metric(self.expression_times, expression_ms)

    def record_aggregation_time(self, ms: float):
        self._record_rolling_metric(self.aggregation_times, ms)

    def should_process_video_frame(
        self,
        role: Role,
        now: float | None = None,
    ) -> bool:
        """Rate-limit per-participant video processing based on current FPS."""
        participant = self.participants[role]
        now = time.time() if now is None else now
        min_interval = 1.0 / max(self.current_fps, 1)

        if (
            participant.last_video_processed_at is not None
            and now - participant.last_video_processed_at < min_interval
        ):
            self.dropped_frames += 1
            return False

        participant.last_video_processed_at = now
        return True

    def _avg(self, samples: list[float]) -> float:
        if not samples:
            return 0.0
        return sum(samples) / len(samples)

    def check_degradation(self) -> int:
        avg = self.rolling_avg_processing_ms()
        new_level = 0
        if avg > settings.degradation_step3_ms:
            new_level = 3
        elif avg > settings.degradation_step2_ms:
            new_level = 2
        elif avg > settings.degradation_step1_ms:
            new_level = 1

        if new_level != self.degradation_level:
            self.degradation_events += 1
            self.degradation_level = new_level
            if new_level == 0:
                self.current_fps = settings.default_fps
            elif new_level == 1:
                self.current_fps = 2
            else:
                self.current_fps = settings.min_fps

        return self.degradation_level

    def get_latency_stats(self) -> LatencyStats:
        avg = self.rolling_avg_processing_ms()
        return LatencyStats(
            avg_processing_ms=avg,
            avg_decode_ms=self._avg(self.decode_times),
            avg_facemesh_ms=self._avg(self.facemesh_times),
            avg_gaze_ms=self._avg(self.gaze_times),
            avg_expression_ms=self._avg(self.expression_times),
            avg_aggregation_ms=self._avg(self.aggregation_times),
            dropped_frames=self.dropped_frames,
            degradation_events=self.degradation_events,
            current_fps=self.current_fps,
            degradation_level=self.degradation_level,
        )

    def cancel_grace_task(self, role: Role):
        """Cancel any pending grace-period finalization for this role."""
        key = role.value
        task = self._grace_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, SessionRoom] = {}

    def create_session(
        self,
        tutor_id: str = "",
        session_type: str = "general",
        media_provider: MediaProvider | None = None,
    ) -> SessionCreateResponse:
        if media_provider is None:
            media_provider = MediaProvider(settings.default_media_provider)
        session_id = secrets.token_urlsafe(8)
        tutor_token = secrets.token_urlsafe(16)
        student_token = secrets.token_urlsafe(16)
        livekit_room_name = ""
        if media_provider == MediaProvider.LIVEKIT:
            livekit_room_name = f"{settings.livekit_room_prefix}-{session_id}"

        room = SessionRoom(
            session_id=session_id,
            tutor_token=tutor_token,
            student_token=student_token,
            tutor_id=tutor_id,
            session_type=session_type,
            media_provider=media_provider,
            livekit_room_name=livekit_room_name,
        )
        self._sessions[session_id] = room

        return SessionCreateResponse(
            session_id=session_id,
            tutor_token=tutor_token,
            student_token=student_token,
            media_provider=media_provider,
            livekit_room_name=livekit_room_name or None,
        )

    def get_session(self, session_id: str) -> SessionRoom | None:
        return self._sessions.get(session_id)

    def get_session_by_livekit_room(self, room_name: str) -> SessionRoom | None:
        for room in self._sessions.values():
            if room.livekit_room_name == room_name:
                return room
        return None

    def remove_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())


# Global singleton
session_manager = SessionManager()
