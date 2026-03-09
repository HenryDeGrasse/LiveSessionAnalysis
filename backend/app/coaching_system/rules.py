"""Live coaching rules.

Each rule is a function ``(snapshot, elapsed, profile) -> bool`` where
*profile* carries the session-type-specific thresholds.  Rules are
intentionally few and high-precision — ambiguous signals are deferred
to post-session flagged moments.

Design principles (from v2.md §8):
- Precision > recall for live nudges.
- Only 3–5 high-confidence rules fire live.
- Energy is a *supporting* signal, not a standalone live trigger.
- Session-type profiles adjust thresholds per conversation norm.
- Visual rules are gated on visual confidence; audio rules are not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import MetricsSnapshot, NudgePriority
from ..config import settings
from .profiles import SessionProfile, get_profile


@dataclass
class CoachingRule:
    """A configurable coaching rule that triggers nudges."""

    name: str
    nudge_type: str
    condition: Callable[[MetricsSnapshot, float, SessionProfile], bool]
    message_template: str
    priority: NudgePriority
    cooldown_seconds: int
    min_session_elapsed: int  # Don't nudge in first N seconds
    requires_visual_confidence: bool = False


# ---------------------------------------------------------------------------
# Rule conditions
# ---------------------------------------------------------------------------

def _check_for_understanding_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    """Tutor overtalk beyond what the session type expects.

    Uses session-type-aware thresholds so a lecture tutor talking 85%
    doesn't trigger (threshold 92%), but a practice tutor at 60% does
    (threshold 55%).

    If the student has also been silent for a sustained period, it's an
    even stronger signal, but overtalk alone is enough to fire.
    """
    return (
        elapsed > 60
        and snapshot.session.recent_tutor_talk_percent > profile.tutor_overtalk_threshold
    )


def _student_off_task_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    """Persistence-based off-task detection.

    v2.md "Student likely off-task": OFF_TASK_AWAY sustained for >N seconds.
    Uses time-in-state for persistence instead of instantaneous checks.
    Gated on visual confidence.
    """
    if snapshot.gaze_unavailable:
        return False

    # Must have decent confidence
    if snapshot.student.attention_state_confidence < 0.5:
        return False

    if snapshot.student.attention_state == "OFF_TASK_AWAY":
        return (
            snapshot.student.time_in_attention_state_seconds
            >= profile.off_task_persistence_seconds
        )

    # FACE_MISSING for a long time is also concerning
    if snapshot.student.attention_state == "FACE_MISSING":
        return (
            snapshot.student.time_in_attention_state_seconds
            >= profile.off_task_persistence_seconds
        )

    return False


def _let_them_finish_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    """Tutor interruption pattern: hard interrupts/cutoffs while dominating.

    v2.md "Let them finish": tutor hard interruptions/cutoffs exceed
    threshold AND student talk share is low.
    """
    return (
        not snapshot.degraded
        and not snapshot.session.echo_suspected
        and (
            snapshot.session.recent_hard_interruptions
            >= profile.interruption_spike_count
            or snapshot.session.tutor_cutoffs
            >= max(1, profile.interruption_spike_count - 1)
        )
        and snapshot.session.recent_tutor_talk_percent >= 0.65
    )


def _tech_check_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    """Mutual silence + media anomaly suggests a technical issue.

    v2.md "Tech check": mutual silence >N seconds AND face missing /
    audio muted / reconnect churn.
    """
    if (
        snapshot.session.mutual_silence_duration_current
        < profile.tech_check_silence_seconds
    ):
        return False

    # Need at least one anomaly signal beyond just silence
    face_missing = snapshot.student.attention_state == "FACE_MISSING"
    tutor_face_missing = snapshot.tutor.attention_state == "FACE_MISSING"
    degraded = snapshot.degraded

    return face_missing or tutor_face_missing or degraded


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[CoachingRule] = [
    CoachingRule(
        name="check_for_understanding",
        nudge_type="check_for_understanding",
        condition=_check_for_understanding_condition,
        message_template=(
            "You've been talking for a while and the student has been quiet. "
            "Consider asking a question to check understanding."
        ),
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=settings.tutor_overtalk_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
    CoachingRule(
        name="student_off_task",
        nudge_type="student_off_task",
        condition=_student_off_task_condition,
        message_template=(
            "Student appears to have been away from the screen for a while. "
            "They may be distracted or having a technical issue."
        ),
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=settings.low_eye_contact_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
        requires_visual_confidence=True,
    ),
    CoachingRule(
        name="let_them_finish",
        nudge_type="let_them_finish",
        condition=_let_them_finish_condition,
        message_template=(
            "Several interruptions detected while the student was speaking. "
            "Try giving more wait time after questions."
        ),
        priority=NudgePriority.LOW,
        cooldown_seconds=settings.interruption_spike_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
    CoachingRule(
        name="tech_check",
        nudge_type="tech_check",
        condition=_tech_check_condition,
        message_template=(
            "Extended silence detected and a participant may be off-camera. "
            "There might be a technical issue — consider checking in."
        ),
        priority=NudgePriority.HIGH,
        cooldown_seconds=300,  # At most once per 5 minutes
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
]
