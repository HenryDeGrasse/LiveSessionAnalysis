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
    severity: Callable[[MetricsSnapshot, float, SessionProfile], float] | None = None
    requires_visual_confidence: bool = False
    allow_when_degraded: bool = False


# ---------------------------------------------------------------------------
# Rule conditions
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _student_recent_talk(snapshot: MetricsSnapshot) -> float:
    # ``talk_time_pct_windowed`` is the best live signal. Fall back to the
    # inverse tutor share when the window has not yet accumulated enough data.
    if snapshot.student.talk_time_pct_windowed > 0.0:
        return snapshot.student.talk_time_pct_windowed
    return max(0.0, 1.0 - snapshot.session.recent_tutor_talk_percent)


def priority_for_severity(score: float) -> NudgePriority:
    if score >= 0.85:
        return NudgePriority.HIGH
    if score >= 0.60:
        return NudgePriority.MEDIUM
    return NudgePriority.LOW

def _check_for_understanding_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _check_for_understanding_severity(snapshot, elapsed, profile) > 0.0



def _check_for_understanding_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Tutor overtalk beyond what the session type expects.

    Severity rises with how far beyond the profile threshold the tutor is,
    and is amplified when the student has been quiet or barely taking turns.
    """
    if elapsed <= 45:
        return 0.0

    overtalk_excess = (
        snapshot.session.recent_tutor_talk_percent - profile.tutor_overtalk_threshold
    )
    if overtalk_excess < 0.03:
        return 0.0

    student_recent_talk = _student_recent_talk(snapshot)
    silence_factor = _clamp01(
        snapshot.session.time_since_student_spoke
        / max(1.0, profile.student_silence_threshold_seconds)
    )
    quiet_factor = _clamp01((0.25 - student_recent_talk) / 0.25)
    overtalk_factor = _clamp01(overtalk_excess / 0.18)

    return _clamp01(0.42 + 0.34 * overtalk_factor + 0.12 * silence_factor + 0.14 * quiet_factor)


def _student_off_task_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _student_off_task_severity(snapshot, elapsed, profile) > 0.0



def _student_off_task_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Persistence-based off-task detection."""
    if snapshot.gaze_unavailable:
        return 0.0
    if snapshot.student.attention_state_confidence < 0.5:
        return 0.0

    if snapshot.student.attention_state not in {"OFF_TASK_AWAY", "FACE_MISSING"}:
        return 0.0

    persistence = snapshot.student.time_in_attention_state_seconds
    if persistence < profile.off_task_persistence_seconds:
        return 0.0

    state_bonus = 0.10 if snapshot.student.attention_state == "FACE_MISSING" else 0.0
    persistence_factor = _clamp01(
        (persistence - profile.off_task_persistence_seconds)
        / max(15.0, profile.off_task_persistence_seconds)
    )
    confidence_factor = _clamp01(snapshot.student.attention_state_confidence)
    return _clamp01(0.72 + 0.12 * persistence_factor + 0.08 * confidence_factor + state_bonus)


def _let_them_finish_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _let_them_finish_severity(snapshot, elapsed, profile) > 0.0



def _let_them_finish_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Tutor interruption pattern: hard interrupts/cutoffs while dominating.

    This is intentionally broader than the old binary rule so it can reflect
    persistent cutoff patterns, not just a single exact threshold crossing.
    """
    # Echo affects overlap detection reliability; reduce severity instead of
    # hard-suppressing so strong interruption patterns can still surface.
    echo_penalty = 0.5 if snapshot.session.echo_suspected else 1.0
    if snapshot.session.recent_tutor_talk_percent < 0.58:
        return 0.0

    hard_count = snapshot.session.recent_hard_interruptions
    cutoff_count = snapshot.session.tutor_cutoffs
    recent_overlaps = snapshot.session.recent_interruptions

    hard_factor = _clamp01(hard_count / max(1.0, profile.interruption_spike_count))
    cutoff_factor = _clamp01(cutoff_count / max(2.0, profile.interruption_spike_count - 1))
    dominance_factor = _clamp01((snapshot.session.recent_tutor_talk_percent - 0.58) / 0.22)

    active_bonus = 0.0
    if snapshot.session.active_overlap_state == "hard":
        active_bonus = 0.18
    elif (
        snapshot.session.active_overlap_state == "meaningful"
        and snapshot.session.active_overlap_duration_current
        >= settings.hard_interruption_min_duration_seconds
    ):
        active_bonus = 0.08

    # Require a real recent pattern rather than isolated overlap noise.
    if hard_count < max(1, profile.interruption_spike_count - 1) and cutoff_count < 2:
        if not (cutoff_count >= 1 and recent_overlaps >= profile.interruption_spike_count * 2):
            return 0.0

    pattern_factor = max(hard_factor, cutoff_factor)
    raw_severity = _clamp01(0.24 + 0.34 * pattern_factor + 0.14 * dominance_factor + active_bonus)
    return _clamp01(raw_severity * echo_penalty)


def _tech_check_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _tech_check_severity(snapshot, elapsed, profile) > 0.0



def _tech_check_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Mutual silence + media anomaly suggests a technical issue."""
    silence = snapshot.session.mutual_silence_duration_current
    if silence < profile.tech_check_silence_seconds:
        return 0.0

    face_missing = snapshot.student.attention_state == "FACE_MISSING"
    tutor_face_missing = snapshot.tutor.attention_state == "FACE_MISSING"
    degraded = snapshot.degraded

    anomaly_count = int(face_missing) + int(tutor_face_missing) + int(degraded)
    if anomaly_count == 0:
        return 0.0

    silence_factor = _clamp01(silence / max(1.0, profile.tech_check_silence_seconds * 2.0))
    return _clamp01(0.7 + 0.1 * anomaly_count + 0.15 * silence_factor)


# ---------------------------------------------------------------------------
# New rules to cover previously uncovered live-session scenarios
# ---------------------------------------------------------------------------


def _re_engage_silence_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _re_engage_silence_severity(snapshot, elapsed, profile) > 0.0


def _re_engage_silence_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Both participants are present and quiet for too long.

    Unlike tech_check, this rule requires BOTH participants to have faces
    present (no FACE_MISSING), meaning the silence is social/conversational
    rather than technical.  It directly addresses the reported session
    scenario: mutual_silence=68s, both CAMERA_FACING, no anomalies.

    Severity rises with silence duration and is amplified when the silence
    window is unusually long relative to the profile expectation.
    """
    silence = snapshot.session.mutual_silence_duration_current
    if silence < profile.mutual_silence_threshold_seconds:
        return 0.0

    # Both must be visually present — this is not a tech issue
    student_present = snapshot.student.attention_state not in {"FACE_MISSING"}
    tutor_present = snapshot.tutor.attention_state not in {"FACE_MISSING"}
    if not (student_present and tutor_present):
        return 0.0

    silence_factor = _clamp01(
        (silence - profile.mutual_silence_threshold_seconds)
        / max(1.0, profile.mutual_silence_threshold_seconds)
    )
    return _clamp01(0.55 + 0.35 * silence_factor)


def _encourage_student_response_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _encourage_student_response_severity(snapshot, elapsed, profile) > 0.0


def _encourage_student_response_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Student has been silent for a long time despite being visually present,
    while the tutor is NOT dominating talk.

    This fills the gap between check_for_understanding (high tutor talk) and
    silence during low-activity stretches.  A student who is present but quiet
    in a low-talk-share session is likely disengaged or confused.

    Tutor talk < 0.60 requirement prevents double-firing with
    check_for_understanding.
    """
    student_silence = snapshot.session.time_since_student_spoke
    if student_silence < profile.student_long_silence_seconds:
        return 0.0

    # Only fire when tutor is NOT dominating — check_for_understanding handles that
    if snapshot.session.recent_tutor_talk_percent >= 0.60:
        return 0.0

    # Student must be visually present — if missing, tech_check should cover it
    student_present = snapshot.student.attention_state not in {"FACE_MISSING"}
    if not student_present:
        return 0.0

    silence_factor = _clamp01(
        (student_silence - profile.student_long_silence_seconds)
        / max(1.0, profile.student_long_silence_seconds)
    )
    presence_bonus = 0.10 if snapshot.student.attention_state == "CAMERA_FACING" else 0.0
    return _clamp01(0.52 + 0.30 * silence_factor + presence_bonus)


def _session_momentum_loss_condition(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> bool:
    return _session_momentum_loss_severity(snapshot, elapsed, profile) > 0.0


def _session_momentum_loss_severity(
    snapshot: MetricsSnapshot,
    elapsed: float,
    profile: SessionProfile,
) -> float:
    """Gradual disengagement that individual signal rules miss.

    Fires when engagement_score has dropped below the profile threshold AND
    the engagement trend is declining AND both participants are present.
    To avoid overfiring on merely "low scoring" but still-active sessions,
    interaction rate must also have slowed via a growing silence gap,
    sluggish response latency, or an unusually low number of turns.
    """
    # Require meaningful session time before momentum can be judged
    if elapsed < 120:
        return 0.0

    if snapshot.session.engagement_score >= profile.low_engagement_score_threshold:
        return 0.0

    if snapshot.session.engagement_trend != "declining":
        return 0.0

    # Both participants must be present — if faces missing, tech_check fires instead
    student_present = snapshot.student.attention_state not in {"FACE_MISSING"}
    tutor_present = snapshot.tutor.attention_state not in {"FACE_MISSING"}
    if not (student_present and tutor_present):
        return 0.0

    silence_gap_threshold = max(
        15.0,
        min(30.0, profile.mutual_silence_threshold_seconds * 0.5),
    )
    response_latency_threshold = max(
        12.0,
        min(30.0, profile.student_long_silence_seconds * 0.2),
    )
    total_turns = snapshot.session.tutor_turn_count + snapshot.session.student_turn_count
    sparse_turns = elapsed >= 240 and total_turns <= 4
    slow_responses = (
        snapshot.session.student_response_latency_last_seconds >= response_latency_threshold
        or snapshot.session.tutor_response_latency_last_seconds >= response_latency_threshold
    )
    interaction_rate_dropped = (
        snapshot.session.mutual_silence_duration_current >= silence_gap_threshold
        or slow_responses
        or sparse_turns
    )
    if not interaction_rate_dropped:
        return 0.0

    score_deficit = _clamp01(
        (profile.low_engagement_score_threshold - snapshot.session.engagement_score)
        / max(1.0, profile.low_engagement_score_threshold)
    )
    interaction_factor = max(
        _clamp01(
            snapshot.session.mutual_silence_duration_current
            / max(1.0, silence_gap_threshold * 2.0)
        ),
        _clamp01(
            max(
                snapshot.session.student_response_latency_last_seconds,
                snapshot.session.tutor_response_latency_last_seconds,
            )
            / max(1.0, response_latency_threshold * 2.0)
        ),
        0.35 if sparse_turns else 0.0,
    )
    return _clamp01(0.44 + 0.28 * score_deficit + 0.18 * interaction_factor)


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[CoachingRule] = [
    CoachingRule(
        name="check_for_understanding",
        nudge_type="check_for_understanding",
        condition=_check_for_understanding_condition,
        severity=_check_for_understanding_severity,
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
        severity=_student_off_task_severity,
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
        severity=_let_them_finish_severity,
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
        severity=_tech_check_severity,
        message_template=(
            "Extended silence detected and a participant may be off-camera. "
            "There might be a technical issue — consider checking in."
        ),
        priority=NudgePriority.HIGH,
        cooldown_seconds=300,  # At most once per 5 minutes
        min_session_elapsed=settings.min_session_elapsed_for_nudges,
        allow_when_degraded=True,
    ),
    CoachingRule(
        name="re_engage_silence",
        nudge_type="re_engage_silence",
        condition=_re_engage_silence_condition,
        severity=_re_engage_silence_severity,
        message_template=(
            "Both you and the student have been quiet for a while. "
            "Consider asking a question to restart the conversation."
        ),
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=120,
        min_session_elapsed=60,
        # Audio/presence-based signal — fires even in degraded visual mode
        allow_when_degraded=True,
    ),
    CoachingRule(
        name="encourage_student_response",
        nudge_type="encourage_student_response",
        condition=_encourage_student_response_condition,
        severity=_encourage_student_response_severity,
        message_template=(
            "The student has been quiet for a while despite being present. "
            "Try asking a direct question or checking if they need help."
        ),
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=120,
        min_session_elapsed=60,
        # Audio/presence-based signal — fires even in degraded visual mode
        allow_when_degraded=True,
    ),
    CoachingRule(
        name="session_momentum_loss",
        nudge_type="session_momentum_loss",
        condition=_session_momentum_loss_condition,
        severity=_session_momentum_loss_severity,
        message_template=(
            "Session momentum appears to be fading. "
            "Consider changing your approach or asking if the student "
            "wants to try a different topic."
        ),
        priority=NudgePriority.LOW,
        cooldown_seconds=180,
        min_session_elapsed=120,
        allow_when_degraded=False,
    ),
]
