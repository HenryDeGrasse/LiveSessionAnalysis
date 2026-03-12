"""Session-type coaching profiles.

Different session types have different conversational norms.  A lecture
is expected to be tutor-dominated; a practice session should be student-
heavy.  These profiles adjust live coaching thresholds so rules fire
only when the conversation deviates from what's *normal for that type*.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionProfile:
    """Per-session-type thresholds for live coaching rules."""

    # Talk balance -----------------------------------------------------------
    # The tutor talk % above which we consider "overtalk" for this type.
    tutor_overtalk_threshold: float
    # How long student silence (seconds) is tolerated before nudging.
    student_silence_threshold_seconds: float

    # Interruptions ----------------------------------------------------------
    # Minimum hard interruptions in the recent window before nudging.
    interruption_spike_count: int

    # Off-task ---------------------------------------------------------------
    # Seconds of sustained OFF_TASK_AWAY before firing the off-task nudge.
    off_task_persistence_seconds: float

    # Tech check -------------------------------------------------------------
    # Seconds of mutual silence + media anomaly before tech check nudge.
    tech_check_silence_seconds: float

    # Re-engage silence ------------------------------------------------------
    # Seconds of mutual silence with BOTH participants visually present
    # before firing a re-engage nudge (distinct from tech_check which
    # requires a media anomaly).
    mutual_silence_threshold_seconds: float

    # Encourage student response ---------------------------------------------
    # Seconds student has been silent while tutor is NOT dominating talk
    # (i.e. check_for_understanding wouldn't cover it) and student is present.
    student_long_silence_seconds: float

    # Session momentum loss --------------------------------------------------
    # Engagement score below which session_momentum_loss can fire
    # (combined with a declining trend signal).
    low_engagement_score_threshold: float


# ---- Built-in profiles ---------------------------------------------------

LECTURE = SessionProfile(
    tutor_overtalk_threshold=0.92,       # lectures are tutor-heavy by design
    student_silence_threshold_seconds=300,  # student silence is normal
    interruption_spike_count=3,
    off_task_persistence_seconds=90,      # longer leash — student may be listening
    tech_check_silence_seconds=45,
    mutual_silence_threshold_seconds=90,  # long gap before nudging in a lecture
    student_long_silence_seconds=300,     # silence is expected in lecture
    low_engagement_score_threshold=40.0,  # lower bar — monologue is normal
)

PRACTICE = SessionProfile(
    tutor_overtalk_threshold=0.55,       # student should be doing most of the work
    student_silence_threshold_seconds=60,
    interruption_spike_count=4,          # more interaction → more overlaps tolerated
    off_task_persistence_seconds=60,
    tech_check_silence_seconds=30,
    mutual_silence_threshold_seconds=45,  # practice should have active back-and-forth
    student_long_silence_seconds=75,
    low_engagement_score_threshold=50.0,
)

SOCRATIC = SessionProfile(
    tutor_overtalk_threshold=0.65,       # question-driven, moderate tutor share
    student_silence_threshold_seconds=45,
    interruption_spike_count=3,
    off_task_persistence_seconds=60,
    tech_check_silence_seconds=30,
    mutual_silence_threshold_seconds=45,  # question-answer flow should be active
    student_long_silence_seconds=60,
    low_engagement_score_threshold=50.0,
)

GENERAL = SessionProfile(
    tutor_overtalk_threshold=0.80,       # current default
    student_silence_threshold_seconds=180,
    interruption_spike_count=3,
    off_task_persistence_seconds=75,
    tech_check_silence_seconds=30,
    mutual_silence_threshold_seconds=60,  # 60s mutual silence is unusual
    student_long_silence_seconds=90,
    low_engagement_score_threshold=50.0,
)

DISCUSSION = SessionProfile(
    tutor_overtalk_threshold=0.60,
    student_silence_threshold_seconds=90,
    interruption_spike_count=4,
    off_task_persistence_seconds=60,
    tech_check_silence_seconds=30,
    mutual_silence_threshold_seconds=45,  # discussions should be lively
    student_long_silence_seconds=90,
    low_engagement_score_threshold=50.0,
)

_PROFILES: dict[str, SessionProfile] = {
    "lecture": LECTURE,
    "practice": PRACTICE,
    "socratic": SOCRATIC,
    "general": GENERAL,
    "discussion": DISCUSSION,
}


def get_profile(session_type: str) -> SessionProfile:
    """Return the coaching profile for a session type, defaulting to GENERAL."""
    return _PROFILES.get(session_type, GENERAL)
