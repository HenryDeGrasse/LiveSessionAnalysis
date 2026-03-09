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


# ---- Built-in profiles ---------------------------------------------------

LECTURE = SessionProfile(
    tutor_overtalk_threshold=0.92,       # lectures are tutor-heavy by design
    student_silence_threshold_seconds=300,  # student silence is normal
    interruption_spike_count=3,
    off_task_persistence_seconds=90,      # longer leash — student may be listening
    tech_check_silence_seconds=45,
)

PRACTICE = SessionProfile(
    tutor_overtalk_threshold=0.55,       # student should be doing most of the work
    student_silence_threshold_seconds=60,
    interruption_spike_count=4,          # more interaction → more overlaps tolerated
    off_task_persistence_seconds=60,
    tech_check_silence_seconds=30,
)

SOCRATIC = SessionProfile(
    tutor_overtalk_threshold=0.65,       # question-driven, moderate tutor share
    student_silence_threshold_seconds=45,
    interruption_spike_count=3,
    off_task_persistence_seconds=60,
    tech_check_silence_seconds=30,
)

GENERAL = SessionProfile(
    tutor_overtalk_threshold=0.80,       # current default
    student_silence_threshold_seconds=180,
    interruption_spike_count=3,
    off_task_persistence_seconds=75,
    tech_check_silence_seconds=30,
)

DISCUSSION = SessionProfile(
    tutor_overtalk_threshold=0.60,
    student_silence_threshold_seconds=90,
    interruption_spike_count=4,
    off_task_persistence_seconds=60,
    tech_check_silence_seconds=30,
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
