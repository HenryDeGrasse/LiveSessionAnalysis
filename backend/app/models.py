from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, computed_field


class Role(str, Enum):
    TUTOR = "tutor"
    STUDENT = "student"


class CoachingIntensity(str, Enum):
    OFF = "off"
    SUBTLE = "subtle"
    NORMAL = "normal"
    AGGRESSIVE = "aggressive"


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
    instant_attention_state: Literal[
        "FACE_MISSING",
        "LOW_CONFIDENCE",
        "CAMERA_FACING",
        "SCREEN_ENGAGED",
        "DOWN_ENGAGED",
        "OFF_TASK_AWAY",
    ] = "LOW_CONFIDENCE"
    instant_attention_state_confidence: float = 0.0
    face_presence_score: float = 0.0
    visual_attention_score: float = 0.5
    time_in_attention_state_seconds: float = 0.0
    talk_time_pct_windowed: float = 0.0
    time_since_spoke_seconds: float = 0.0


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
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    degradation_reason: str = "normal"
    target_fps: int = 3
    coaching_decision: Optional[dict] = None
    coaching_status: Optional[dict] = None
    # Per-student metrics for multi-student sessions (indices 1+ students).
    # Keyed by student index as a string for JSON serialization.
    # Not populated for single-student sessions (max_students=1).
    per_student_metrics: Optional[dict] = None

    # --- AI Conversational Intelligence fields ---
    transcript_available: bool = False
    student_uncertainty_score: Optional[float] = None
    student_uncertainty_topic: Optional[str] = None
    student_uncertainty_confidence: Optional[float] = None
    ai_suggestion: Optional[str] = None
    backpressure_level: int = 0


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
    session_title: str = ""
    tutor_id: str = ""
    student_user_id: str = ""
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    session_type: str = "general"
    media_provider: MediaProvider = MediaProvider.LIVEKIT
    talk_time_ratio: dict[str, float] = Field(default_factory=dict)
    # Multi-student sessions can expose a per-student talk-time breakdown keyed
    # by student index ("0" == primary student, "1+" == extra students).
    per_student_talk_time_ratio: Optional[dict[str, float]] = None
    avg_eye_contact: dict[str, float] = Field(default_factory=dict)
    avg_energy: dict[str, float] = Field(default_factory=dict)
    total_interruptions: int = 0
    engagement_score: float = 0.0
    flagged_moments: list[FlaggedMoment] = Field(default_factory=list)
    timeline: dict[str, list[float]] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)
    nudges_sent: int = 0
    degradation_events: int = 0
    # Post-session analytics enrichments
    attention_state_distribution: dict[str, dict[str, float]] = Field(
        default_factory=dict
    )
    nudge_details: list[dict] = Field(default_factory=list)
    turn_counts: dict[str, int] = Field(default_factory=dict)

    # --- AI Conversational Intelligence post-session fields ---
    transcript_available: bool = False
    transcript_word_count: int = 0
    topics_covered: list[str] = Field(default_factory=list)
    ai_summary: Optional[str] = None
    student_understanding_map: dict[str, float] = Field(default_factory=dict)
    key_moments: list[dict] = Field(default_factory=list)
    follow_up_recommendations: list[str] = Field(default_factory=list)
    uncertainty_timeline: list[dict] = Field(default_factory=list)
    transcript_compact: Optional[dict[str, Any]] = None

    def is_owner(self, user_id: str) -> bool:
        """Return True if user_id matches the tutor or the student of this session."""
        if not user_id:
            return False
        return self.tutor_id == user_id or self.student_user_id == user_id


class TrendData(BaseModel):
    tutor_id: str
    sessions: list[dict] = Field(default_factory=list)
    trends: dict[str, Literal["improving", "stable", "declining"]] = Field(
        default_factory=dict
    )


class SessionCreateRequest(BaseModel):
    tutor_id: str = ""
    student_user_id: str = ""
    session_type: str = "general"
    session_title: str = ""
    media_provider: Optional[MediaProvider] = None
    coaching_intensity: CoachingIntensity = CoachingIntensity.NORMAL
    max_students: int = 1


class SessionTitleUpdateRequest(BaseModel):
    session_title: str


class SessionCreateResponse(BaseModel):
    session_id: str
    session_title: str = ""
    tutor_token: str
    # Primary list of all pre-generated student tokens.
    student_tokens: list[str] = Field(default_factory=list)
    max_students: int = 1
    media_provider: MediaProvider = MediaProvider.CUSTOM_WEBRTC
    livekit_room_name: Optional[str] = None
    coaching_intensity: CoachingIntensity = CoachingIntensity.NORMAL

    @computed_field  # type: ignore[misc]
    @property
    def student_token(self) -> str:
        """Backward-compatible alias for student_tokens[0]."""
        return self.student_tokens[0] if self.student_tokens else ""


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
        "transcript_partial",
        "transcript_final",
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
