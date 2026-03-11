from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..models import MetricsSnapshot, Nudge, SessionSummary


class TracePoint(BaseModel):
    seq: int
    t_ms: int
    timestamp: datetime


class SessionEvent(TracePoint):
    event_type: Literal[
        "tutor_connected",
        "student_connected",
        "participant_ready",
        "participant_disconnected",
        "participant_reconnected",
        "session_end_requested",
        "session_end",
        "degradation_changed",
        "webrtc_signal_relayed",
        "livekit_webhook",
    ]
    role: Optional[Literal["tutor", "student"]] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class VisualSignalPoint(TracePoint):
    role: Literal["tutor", "student"]
    face_present: bool
    gaze_on_camera: Optional[bool] = None
    attention_state: Optional[str] = None
    confidence: float = 0.0


class AudioSignalPoint(TracePoint):
    role: Literal["tutor", "student"]
    speech_active: bool
    rms_db: Optional[float] = None
    noise_floor_db: Optional[float] = None


class OverlapSegment(BaseModel):
    start_t_ms: int
    end_t_ms: int
    overlap_type: Literal["hard", "backchannel", "echo_suspected", "meaningful"]


class CoachingDecisionTrace(TracePoint):
    emitted_nudge: Optional[str] = None
    candidate_nudges: List[str] = Field(default_factory=list)
    suppressed_reasons: List[str] = Field(default_factory=list)
    metrics_index: Optional[int] = None
    trigger_features: Dict[str, Any] = Field(default_factory=dict)
    candidates_evaluated: List[str] = Field(default_factory=list)
    fired_rule: Optional[str] = None


class SessionTrace(BaseModel):
    trace_version: int = 1
    session_id: str
    tutor_id: str = ""
    session_type: str = "general"
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: datetime
    duration_seconds: float
    build: Dict[str, Any] = Field(default_factory=dict)
    config_hash: str = ""
    capture_mode: Literal["prod", "eval", "browser-debug"] = "prod"
    env: Dict[str, Any] = Field(default_factory=dict)
    events: List[SessionEvent] = Field(default_factory=list)
    visual_signals: List[VisualSignalPoint] = Field(default_factory=list)
    audio_signals: List[AudioSignalPoint] = Field(default_factory=list)
    overlap_segments: List[OverlapSegment] = Field(default_factory=list)
    metrics_history: List[MetricsSnapshot] = Field(default_factory=list)
    nudges: List[Nudge] = Field(default_factory=list)
    coaching_decisions: List[CoachingDecisionTrace] = Field(default_factory=list)
    summary: SessionSummary
