from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ..config import settings
from ..models import MetricsSnapshot, Nudge, SessionSummary
from .trace_models import (
    AudioSignalPoint,
    CoachingDecisionTrace,
    OverlapSegment,
    SessionEvent,
    SessionTrace,
    VisualSignalPoint,
)
from . import get_trace_store, TraceStore


def default_config_hash() -> str:
    payload = json.dumps(settings.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def default_build_metadata() -> Dict[str, Any]:
    return {
        "git_sha": os.getenv("LSA_BUILD_GIT_SHA", ""),
        "app_version": os.getenv("LSA_BUILD_VERSION", "1.0.0"),
        "models_version": os.getenv("LSA_MODELS_VERSION", ""),
    }


class SessionTraceRecorder:
    """Collect session trace artifacts with deterministic ordering metadata."""

    def __init__(
        self,
        session_id: str,
        tutor_id: str = "",
        session_type: str = "general",
        *,
        store: Optional[TraceStore] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        monotonic_fn: Optional[Callable[[], float]] = None,
        capture_mode: str = "prod",
        created_at: Optional[datetime] = None,
        build: Optional[Dict[str, Any]] = None,
        env: Optional[Dict[str, Any]] = None,
        config_hash: Optional[str] = None,
        max_metrics_snapshots: Optional[int] = None,
        max_signal_points_per_role: Optional[int] = None,
    ):
        self.session_id = session_id
        self.tutor_id = tutor_id
        self.session_type = session_type
        self._store = store if store is not None else get_trace_store()
        self._now_fn = now_fn or datetime.utcnow
        self._monotonic_fn = monotonic_fn or time.monotonic
        self._origin_monotonic = self._monotonic_fn()
        self._created_at = created_at or self._now_fn()
        self._started_at: Optional[datetime] = None
        self._seq = 0

        self._build = build or default_build_metadata()
        self._env = env or {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        }
        self._config_hash = config_hash or default_config_hash()
        self._capture_mode = capture_mode

        self._max_metrics_snapshots = (
            settings.trace_max_metrics_snapshots
            if max_metrics_snapshots is None
            else max_metrics_snapshots
        )
        self._max_signal_points_per_role = (
            settings.trace_max_signal_points_per_role
            if max_signal_points_per_role is None
            else max_signal_points_per_role
        )

        self._events: List[SessionEvent] = []
        self._visual_signals: List[VisualSignalPoint] = []
        self._audio_signals: List[AudioSignalPoint] = []
        self._overlap_segments: List[OverlapSegment] = []
        self._metrics_history: List[MetricsSnapshot] = []
        self._nudges: List[Nudge] = []
        self._coaching_decisions: List[CoachingDecisionTrace] = []
        self._visual_signal_counts: Dict[str, int] = {"tutor": 0, "student": 0}
        self._audio_signal_counts: Dict[str, int] = {"tutor": 0, "student": 0}

    def mark_started(self) -> None:
        if self._started_at is None:
            self._started_at = self._now_fn()

    def _next_point(self) -> Dict[str, Any]:
        self._seq += 1
        return {
            "seq": self._seq,
            "t_ms": int(round((self._monotonic_fn() - self._origin_monotonic) * 1000)),
            "timestamp": self._now_fn(),
        }

    def _append_incremental(self, kind: str, payload: Any) -> None:
        if self._store is None:
            return
        self._store.append_record(
            self.session_id,
            {
                "kind": kind,
                "data": payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload,
            },
        )

    def record_event(
        self,
        event_type: str,
        *,
        role: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> SessionEvent:
        event = SessionEvent(
            event_type=event_type,
            role=role,
            data=data or {},
            **self._next_point(),
        )
        self._events.append(event)
        self._append_incremental("event", event)
        return event

    def record_webrtc_signal(
        self,
        *,
        role: str,
        signal_type: str,
        payload: Dict[str, Any],
    ) -> SessionEvent:
        payload_bytes = len(json.dumps(payload, sort_keys=True).encode("utf-8"))
        payload_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        return self.record_event(
            "webrtc_signal_relayed",
            role=role,
            data={
                "signal_type": signal_type,
                "payload_bytes": payload_bytes,
                "payload_keys": payload_keys,
            },
        )

    def record_visual_signal(
        self,
        *,
        role: str,
        face_present: bool,
        gaze_on_camera: Optional[bool] = None,
        attention_state: Optional[str] = None,
        confidence: float = 0.0,
    ) -> Optional[VisualSignalPoint]:
        if self._max_signal_points_per_role > 0:
            if self._visual_signal_counts[role] >= self._max_signal_points_per_role:
                return None
            self._visual_signal_counts[role] += 1
        point = VisualSignalPoint(
            role=role,
            face_present=face_present,
            gaze_on_camera=gaze_on_camera,
            attention_state=attention_state,
            confidence=confidence,
            **self._next_point(),
        )
        self._visual_signals.append(point)
        self._append_incremental("visual_signal", point)
        return point

    def record_audio_signal(
        self,
        *,
        role: str,
        speech_active: bool,
        rms_db: Optional[float] = None,
        noise_floor_db: Optional[float] = None,
    ) -> Optional[AudioSignalPoint]:
        if self._max_signal_points_per_role > 0:
            if self._audio_signal_counts[role] >= self._max_signal_points_per_role:
                return None
            self._audio_signal_counts[role] += 1
        point = AudioSignalPoint(
            role=role,
            speech_active=speech_active,
            rms_db=rms_db,
            noise_floor_db=noise_floor_db,
            **self._next_point(),
        )
        self._audio_signals.append(point)
        self._append_incremental("audio_signal", point)
        return point

    def record_overlap_segment(
        self,
        *,
        start_t_ms: int,
        end_t_ms: int,
        overlap_type: str,
    ) -> OverlapSegment:
        segment = OverlapSegment(
            start_t_ms=start_t_ms,
            end_t_ms=end_t_ms,
            overlap_type=overlap_type,
        )
        self._overlap_segments.append(segment)
        self._append_incremental("overlap_segment", segment)
        return segment

    def record_metrics_snapshot(self, snapshot: MetricsSnapshot) -> Optional[MetricsSnapshot]:
        if self._max_metrics_snapshots > 0 and len(self._metrics_history) >= self._max_metrics_snapshots:
            return None
        self._metrics_history.append(snapshot)
        self._append_incremental("metrics_snapshot", snapshot)
        return snapshot

    def record_nudge(self, nudge: Nudge) -> Nudge:
        self._nudges.append(nudge)
        self._append_incremental("nudge", nudge)
        return nudge

    def record_coaching_decision(
        self,
        *,
        candidate_nudges: List[str],
        emitted_nudge: Optional[str] = None,
        suppressed_reasons: Optional[List[str]] = None,
        metrics_index: Optional[int] = None,
        trigger_features: Optional[Dict[str, Any]] = None,
    ) -> CoachingDecisionTrace:
        decision = CoachingDecisionTrace(
            candidate_nudges=candidate_nudges,
            emitted_nudge=emitted_nudge,
            suppressed_reasons=suppressed_reasons or [],
            metrics_index=metrics_index,
            trigger_features=trigger_features or {},
            **self._next_point(),
        )
        self._coaching_decisions.append(decision)
        self._append_incremental("coaching_decision", decision)
        return decision

    def to_t_ms(self, timestamp_s: float) -> int:
        created_ts = self._created_at.timestamp()
        return int(round(max(0.0, timestamp_s - created_ts) * 1000))

    def finalize(
        self,
        *,
        summary: SessionSummary,
        ended_at: Optional[datetime] = None,
        duration_seconds: Optional[float] = None,
    ) -> SessionTrace:
        trace = SessionTrace(
            session_id=self.session_id,
            tutor_id=self.tutor_id,
            session_type=self.session_type,
            created_at=self._created_at,
            started_at=self._started_at or self._created_at,
            ended_at=ended_at or self._now_fn(),
            duration_seconds=(
                summary.duration_seconds if duration_seconds is None else duration_seconds
            ),
            build=self._build,
            config_hash=self._config_hash,
            capture_mode=self._capture_mode,
            env=self._env,
            events=self._events,
            visual_signals=self._visual_signals,
            audio_signals=self._audio_signals,
            overlap_segments=self._overlap_segments,
            metrics_history=self._metrics_history,
            nudges=self._nudges,
            coaching_decisions=self._coaching_decisions,
            summary=summary,
        )
        if self._store is not None:
            self._store.save(trace)
        return trace
