from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import MetricsSnapshot, NudgePriority
from ..config import settings


@dataclass
class CoachingRule:
    """A configurable coaching rule that triggers nudges."""
    name: str
    nudge_type: str
    condition: Callable[[MetricsSnapshot, float], bool]  # (snapshot, elapsed_s) -> bool
    message_template: str
    priority: NudgePriority
    cooldown_seconds: int
    min_session_elapsed: int  # Don't nudge in first N seconds


def _student_silence_condition(snapshot: MetricsSnapshot, elapsed: float) -> bool:
    """Student has not spoken for a sustained period."""
    return (
        snapshot.session.silence_duration_current
        >= settings.student_silence_threshold_seconds
    )


def _low_eye_contact_condition(snapshot: MetricsSnapshot, elapsed: float) -> bool:
    """Student visual attention looks low when gaze is available.

    Prefer the categorical attention-state model when confidence is decent.
    Fall back to raw eye-contact score for older synthetic tests/callers.
    """
    if snapshot.gaze_unavailable:
        return False

    if snapshot.student.attention_state_confidence >= 0.5:
        if snapshot.student.attention_state in {
            "CAMERA_FACING",
            "SCREEN_ENGAGED",
            "DOWN_ENGAGED",
        }:
            return False
        if snapshot.student.attention_state in {"FACE_MISSING", "OFF_TASK_AWAY"}:
            return True

    return snapshot.student.eye_contact_score < settings.low_eye_contact_threshold


def _tutor_overtalk_condition(snapshot: MetricsSnapshot, elapsed: float) -> bool:
    """Tutor dominates recent conversation window (not just cumulative)."""
    return (
        elapsed > 60  # Need some data first
        and snapshot.session.recent_tutor_talk_percent > settings.tutor_overtalk_threshold
    )


def _energy_drop_condition(snapshot: MetricsSnapshot, elapsed: float) -> bool:
    """Either participant's energy drops significantly.

    Triggers when energy falls below an absolute floor OR when energy
    has dropped significantly from the session baseline (whichever fires first).
    """
    absolute_drop = (
        snapshot.tutor.energy_score < settings.energy_drop_threshold
        or snapshot.student.energy_score < settings.energy_drop_threshold
    )
    baseline_drop = (
        snapshot.tutor.energy_drop_from_baseline
        > settings.energy_drop_from_baseline_threshold
        or snapshot.student.energy_drop_from_baseline
        > settings.energy_drop_from_baseline_threshold
    )
    return absolute_drop or baseline_drop


def _interruption_spike_condition(snapshot: MetricsSnapshot, elapsed: float) -> bool:
    """Too many meaningful recent interruptions in a tutor-dominant window.

    Prefer hard interruptions and cut-off behavior over raw overlap counts so
    live coaching fires less often and with higher precision.
    """
    return (
        not snapshot.degraded
        and not snapshot.session.echo_suspected
        and (
            snapshot.session.recent_hard_interruptions
            >= settings.interruption_spike_count
            or snapshot.session.tutor_cutoffs
            >= max(1, settings.interruption_spike_count - 1)
        )
        and snapshot.session.recent_tutor_talk_percent >= 0.65
    )


DEFAULT_RULES: list[CoachingRule] = [
    CoachingRule(
        name="student_silence",
        nudge_type="student_silence",
        condition=_student_silence_condition,
        message_template="Student hasn't spoken much. Consider asking a question to check understanding.",
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=settings.student_silence_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
    CoachingRule(
        name="low_eye_contact",
        nudge_type="low_eye_contact",
        condition=_low_eye_contact_condition,
        message_template="Student visual attention looks low. They may be distracted, away from the screen, or off camera.",
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=settings.low_eye_contact_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
    CoachingRule(
        name="tutor_overtalk",
        nudge_type="tutor_overtalk",
        condition=_tutor_overtalk_condition,
        message_template="You've been talking for a while. Try asking the student a question.",
        priority=NudgePriority.LOW,
        cooldown_seconds=settings.tutor_overtalk_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
    CoachingRule(
        name="energy_drop",
        nudge_type="energy_drop",
        condition=_energy_drop_condition,
        message_template="Energy levels are low. Consider a short break or change of activity.",
        priority=NudgePriority.HIGH,
        cooldown_seconds=settings.energy_drop_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
    CoachingRule(
        name="interruption_spike",
        nudge_type="interruption_spike",
        condition=_interruption_spike_condition,
        message_template="Several interruptions detected. Try giving more wait time after questions.",
        priority=NudgePriority.LOW,
        cooldown_seconds=settings.interruption_spike_cooldown,
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
    ),
]
