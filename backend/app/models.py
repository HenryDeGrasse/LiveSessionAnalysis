from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Role(str, Enum):
    TUTOR = "tutor"
    STUDENT = "student"


class MediaProvider(str, Enum):
    CUSTOM_WEBRTC = "custom_webrtc"
    LIVEKIT = "livekit"


class ParticipantMetrics(BaseModel):
    eye_contact_score: float = 0.0
    talk_time_percent: float = 0.0
    energy_score: float = 0.0
    energy_drop_from_baseline: float = 0.0
    is_speaking: bool = False
    attention_state: Literal[
        "FACE_MISSING",
        "LOW_CONFIDENCE",
        "CAMERA_FACING",
        "SCREEN_ENGAGED",
        "DOWN_ENGAGED",
        "OFF_TASK_AWAY",
    ] = "LOW_CONFIDENCE"
    attention_state_confidence: float = 0.0
    face_presence_score: float = 0.0
    visual_attention_score: float = 0.5
    time_in_attention_state_seconds: float = 0.0


class SessionMetrics(BaseModel):
    interruption_count: int = 0
    recent_interruptions: int = 0
    hard_interruption_count: int = 0
    recent_hard_interruptions: int = 0
    backchannel_overlap_count: int = 0
    recent_backchannel_overlaps: int = 0
    echo_suspected: bool = False
    active_overlap_duration_current: float = 0.0
    active_overlap_state: Literal[
        "none", "candidate", "backchannel", "meaningful", "hard", "echo_like"
    ] = "none"
    tutor_cutoffs: int = 0
    student_cutoffs: int = 0
    silence_duration_current: float = 0.0
    time_since_student_spoke: float = 0.0
    mutual_silence_duration_current: float = 0.0
    tutor_monologue_duration_current: float = 0.0
    tutor_turn_count: int = 0
    student_turn_count: int = 0
    student_response_latency_last_seconds: float = 0.0
    tutor_response_latency_last_seconds: float = 0.0
    recent_tutor_talk_percent: float = 0.0
    engagement_trend: Literal["rising", "stable", "declining"] = "stable"
    engagement_score: float = 0.0


class MetricsSnapshot(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str
    tutor: ParticipantMetrics = Field(default_factory=ParticipantMetrics)
    student: ParticipantMetrics = Field(default_factory=ParticipantMetrics)
    session: SessionMetrics = Field(default_factory=SessionMetrics)
    degraded: bool = False
    gaze_unavailable: bool = False
    server_processing_ms: float = 0.0
    target_fps: int = 3


class NudgePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Nudge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    nudge_type: str
    message: str
    priority: NudgePriority = NudgePriority.MEDIUM
    trigger_metrics: dict = Field(default_factory=dict)


class FlaggedMoment(BaseModel):
    timestamp: float  # seconds from session start
    metric_name: str
    value: float
    direction: Literal["above", "below"]
    description: str


class SessionSummary(BaseModel):
    session_id: str
    tutor_id: str = ""
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    session_type: str = "general"
    media_provider: MediaProvider = MediaProvider.CUSTOM_WEBRTC
    talk_time_ratio: dict[str, float] = Field(default_factory=dict)
    avg_eye_contact: dict[str, float] = Field(default_factory=dict)
    avg_energy: dict[str, float] = Field(default_factory=dict)
    total_interruptions: int = 0
    engagement_score: float = 0.0
    flagged_moments: list[FlaggedMoment] = Field(default_factory=list)
    timeline: dict[str, list[float]] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    nudges_sent: int = 0
    degradation_events: int = 0


class TrendData(BaseModel):
    tutor_id: str
    sessions: list[dict] = Field(default_factory=list)
    trends: dict[str, Literal["improving", "stable", "declining"]] = Field(
        default_factory=dict
    )


class SessionCreateRequest(BaseModel):
    tutor_id: str = ""
    session_type: str = "general"
    media_provider: Optional[MediaProvider] = None


class SessionCreateResponse(BaseModel):
    session_id: str
    tutor_token: str
    student_token: str
    media_provider: MediaProvider = MediaProvider.CUSTOM_WEBRTC
    livekit_room_name: Optional[str] = None


class WebRTCSignal(BaseModel):
    signal_type: Literal["offer", "answer", "ice_candidate"]
    payload: dict = Field(default_factory=dict)
    from_role: Optional[Literal["tutor", "student"]] = None


class WSMessage(BaseModel):
    type: Literal[
        "metrics",
        "nudge",
        "session_end",
        "participant_ready",
        "participant_disconnected",
        "participant_reconnected",
        "webrtc_signal",
    ]
    data: dict


class LatencyStats(BaseModel):
    avg_processing_ms: float = 0.0
    avg_decode_ms: float = 0.0
    avg_facemesh_ms: float = 0.0
    avg_gaze_ms: float = 0.0
    avg_expression_ms: float = 0.0
    avg_aggregation_ms: float = 0.0
    dropped_frames: int = 0
    degradation_events: int = 0
    current_fps: int = 3
    degradation_level: int = 0
