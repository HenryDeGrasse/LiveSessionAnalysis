from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import (
    FlaggedMoment,
    MediaProvider,
    MetricsSnapshot,
    Nudge,
    ParticipantMetrics,
    SessionSummary,
)

# Thresholds for flagged moments
ENGAGEMENT_LOW = 40.0
STUDENT_TALK_LOW = 0.05
INTERRUPTION_HIGH = 3
STUDENT_ENERGY_LOW = 0.15
STUDENT_OFF_TASK_SECONDS = 60.0
MUTUAL_SILENCE_SECONDS = 45.0

# Grace period: ignore the first N seconds of a session for flagging purposes.
# Early snapshots have no meaningful data (nobody has spoken, engagement score
# is cold-started, energy trackers haven't accumulated history) so flagging
# them produces false positives like "Engagement dropped to 38 at 0:00".
FLAGGED_MOMENT_WARMUP_SECONDS = 30.0

# Treat energy as a vocal metric: only trust it while the participant is
# speaking or has spoken very recently.
ENERGY_RECENT_SPEECH_WINDOW_SECONDS = 3.0
MIN_STUDENT_ENERGY_EVIDENCE_SNAPSHOTS = 3

# Persistence / hysteresis: don't flag on a single bad sample.
ENGAGEMENT_PERSISTENCE_SECONDS = 8.0
STUDENT_TALK_PERSISTENCE_SECONDS = 12.0
STUDENT_ENERGY_PERSISTENCE_SECONDS = 8.0


@dataclass
class _PersistenceState:
    bad_since: float | None = None
    emitted_in_run: bool = False

    def step(self, *, is_bad: bool, elapsed: float, persistence_seconds: float) -> bool:
        """Track a bad run and return True once it has persisted long enough."""
        if not is_bad:
            self.bad_since = None
            self.emitted_in_run = False
            return False

        if self.bad_since is None:
            self.bad_since = elapsed

        if (not self.emitted_in_run) and (elapsed - self.bad_since >= persistence_seconds):
            self.emitted_in_run = True
            return True

        return False


def _has_recent_speech(participant: ParticipantMetrics) -> bool:
    """Whether a snapshot has enough recent speech evidence to trust vocal energy."""
    return participant.is_speaking or (
        0.0 < participant.time_since_spoke_seconds <= ENERGY_RECENT_SPEECH_WINDOW_SECONDS
    )


def _average_energy_from_active_snapshots(
    snapshots: list[MetricsSnapshot],
    role: str,
) -> float:
    """Average energy only across speaking / just-spoke snapshots.

    Falls back to the legacy all-snapshot average if there is no speaking-evidence
    metadata at all (useful for older summaries or synthetic unit-test fixtures).
    """
    active_scores: list[float] = []
    fallback_scores: list[float] = []

    for snapshot in snapshots:
        participant = snapshot.tutor if role == "tutor" else snapshot.student
        fallback_scores.append(participant.energy_score)
        if _has_recent_speech(participant):
            active_scores.append(participant.energy_score)

    scores = active_scores or fallback_scores
    if not scores:
        return 0.5
    return sum(scores) / len(scores)


def generate_summary(
    session_id: str,
    snapshots: list[MetricsSnapshot],
    tutor_id: str = "",
    student_user_id: str = "",
    session_type: str = "general",
    session_title: str = "",
    media_provider: MediaProvider = MediaProvider.LIVEKIT,
    nudges: Optional[list[Nudge]] = None,
) -> SessionSummary:
    """Generate a post-session summary from collected metrics snapshots."""
    if not snapshots:
        from datetime import datetime
        now = datetime.utcnow()
        return SessionSummary(
            session_id=session_id,
            session_title=session_title,
            tutor_id=tutor_id,
            student_user_id=student_user_id,
            session_type=session_type,
            media_provider=media_provider,
            start_time=now,
            end_time=now,
            duration_seconds=0,
            engagement_score=50.0,  # neutral default, not 0 which triggers false flags
        )

    start_time = snapshots[0].timestamp
    end_time = snapshots[-1].timestamp
    duration = (end_time - start_time).total_seconds()

    n = len(snapshots)

    # Use LAST snapshot's cumulative talk-time ratios (more accurate than averaging)
    last = snapshots[-1]
    final_tutor_talk = last.tutor.talk_time_percent
    final_student_talk = last.student.talk_time_percent
    per_student_talk_time_ratio: dict[str, float] | None = None
    if last.per_student_metrics:
        per_student_talk_time_ratio = {
            "0": final_student_talk,
            **{
                str(student_index): float(metrics.get("talk_time_percent", 0.0))
                for student_index, metrics in last.per_student_metrics.items()
            },
        }

    # Average other metrics normally.
    # Energy is averaged only over speaking / just-spoke snapshots so silence
    # doesn't make an engaged but quiet student look "low energy".
    avg_tutor_eye = sum(s.tutor.eye_contact_score for s in snapshots) / n
    avg_student_eye = sum(s.student.eye_contact_score for s in snapshots) / n
    avg_tutor_energy = _average_energy_from_active_snapshots(snapshots, "tutor")
    avg_student_energy = _average_energy_from_active_snapshots(snapshots, "student")
    avg_engagement = sum(s.session.engagement_score for s in snapshots) / n

    # Interruptions: cumulative, take max
    total_interruptions = max(s.session.interruption_count for s in snapshots)

    # Timeline arrays
    timeline = {
        "engagement": [s.session.engagement_score for s in snapshots],
        "tutor_eye_contact": [s.tutor.eye_contact_score for s in snapshots],
        "student_eye_contact": [s.student.eye_contact_score for s in snapshots],
        "tutor_talk_time": [s.tutor.talk_time_percent for s in snapshots],
        "student_talk_time": [s.student.talk_time_percent for s in snapshots],
        "tutor_energy": [s.tutor.energy_score for s in snapshots],
        "student_energy": [s.student.energy_score for s in snapshots],
    }

    # Degradation events: count transitions into degraded state
    degradation_events = 0
    prev_degraded = False
    for s in snapshots:
        if s.degraded and not prev_degraded:
            degradation_events += 1
        prev_degraded = s.degraded

    # Flagged moments
    flagged = _detect_flagged_moments(snapshots, start_time)

    # Attention state distribution: count frames per state, normalize to percentages
    attention_state_distribution = _compute_attention_distribution(snapshots)

    # Nudge details: serialize full nudge objects
    nudge_details: list[dict] = []
    if nudges:
        for nudge in nudges:
            nudge_details.append({
                "nudge_type": nudge.nudge_type,
                "message": nudge.message,
                "timestamp": nudge.timestamp.isoformat(),
                "priority": nudge.priority.value,
            })

    # Turn counts from the last snapshot
    turn_counts = {
        "tutor": last.session.tutor_turn_count,
        "student": last.session.student_turn_count,
    }

    return SessionSummary(
        session_id=session_id,
        session_title=session_title,
        tutor_id=tutor_id,
        student_user_id=student_user_id,
        session_type=session_type,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration,
        media_provider=media_provider,
        talk_time_ratio={"tutor": final_tutor_talk, "student": final_student_talk},
        per_student_talk_time_ratio=per_student_talk_time_ratio,
        avg_eye_contact={"tutor": avg_tutor_eye, "student": avg_student_eye},
        avg_energy={"tutor": avg_tutor_energy, "student": avg_student_energy},
        total_interruptions=total_interruptions,
        engagement_score=avg_engagement,
        flagged_moments=flagged,
        timeline=timeline,
        nudges_sent=len(nudges) if nudges else 0,
        degradation_events=degradation_events,
        attention_state_distribution=attention_state_distribution,
        nudge_details=nudge_details,
        turn_counts=turn_counts,
    )


def _compute_attention_distribution(
    snapshots: list[MetricsSnapshot],
) -> dict[str, dict[str, float]]:
    """Count frames per attention state for tutor and student, normalize to percentages."""
    if not snapshots:
        return {}

    tutor_counts: dict[str, int] = {}
    student_counts: dict[str, int] = {}
    n = len(snapshots)

    for s in snapshots:
        tutor_counts[s.tutor.attention_state] = (
            tutor_counts.get(s.tutor.attention_state, 0) + 1
        )
        student_counts[s.student.attention_state] = (
            student_counts.get(s.student.attention_state, 0) + 1
        )

    tutor_dist = {state: count / n for state, count in tutor_counts.items()}
    student_dist = {state: count / n for state, count in student_counts.items()}

    return {"tutor": tutor_dist, "student": student_dist}


def _detect_flagged_moments(
    snapshots: list[MetricsSnapshot],
    start_time,
) -> list[FlaggedMoment]:
    flagged: list[FlaggedMoment] = []
    warmup = FLAGGED_MOMENT_WARMUP_SECONDS

    engagement_state = _PersistenceState()
    student_talk_state = _PersistenceState()
    interruption_state = _PersistenceState()
    student_energy_state = _PersistenceState()
    attention_state = _PersistenceState()
    mutual_silence_state = _PersistenceState()

    student_energy_evidence_snapshots = 0

    for s in snapshots:
        elapsed = (s.timestamp - start_time).total_seconds()
        if elapsed < warmup:
            continue

        student_has_recent_speech = _has_recent_speech(s.student)
        if student_has_recent_speech:
            student_energy_evidence_snapshots += 1

        # Low engagement — require persistence, not one bad sample.
        if engagement_state.step(
            is_bad=s.session.engagement_score < ENGAGEMENT_LOW,
            elapsed=elapsed,
            persistence_seconds=ENGAGEMENT_PERSISTENCE_SECONDS,
        ):
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="engagement",
                value=s.session.engagement_score,
                direction="below",
                description=f"Engagement stayed low at {s.session.engagement_score:.0f}",
            ))

        # Student talk-share — also require persistence so early cumulative
        # ratios don't instantly trigger after warmup.
        if student_talk_state.step(
            is_bad=s.student.talk_time_percent < STUDENT_TALK_LOW,
            elapsed=elapsed,
            persistence_seconds=STUDENT_TALK_PERSISTENCE_SECONDS,
        ):
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="student_talk_time",
                value=s.student.talk_time_percent,
                direction="below",
                description="Student talk time stayed below 5%",
            ))

        # High interruptions are cumulative, so crossing the threshold is a real
        # event; no extra persistence beyond the threshold crossing is needed.
        if interruption_state.step(
            is_bad=s.session.interruption_count >= INTERRUPTION_HIGH,
            elapsed=elapsed,
            persistence_seconds=0.0,
        ):
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="interruptions",
                value=float(s.session.interruption_count),
                direction="above",
                description=f"Interruption count reached {s.session.interruption_count}",
            ))

        # Student energy should only be judged when we have enough actual speech
        # evidence and the participant is speaking / has just spoken.
        energy_bad = (
            student_energy_evidence_snapshots >= MIN_STUDENT_ENERGY_EVIDENCE_SNAPSHOTS
            and student_has_recent_speech
            and s.student.energy_score < STUDENT_ENERGY_LOW
        )
        if student_energy_state.step(
            is_bad=energy_bad,
            elapsed=elapsed,
            persistence_seconds=STUDENT_ENERGY_PERSISTENCE_SECONDS,
        ):
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="student_energy",
                value=s.student.energy_score,
                direction="below",
                description=f"Student speaking energy stayed low at {s.student.energy_score:.2f}",
            ))

        # Sustained off-task / face missing. The time-in-state requirement is
        # already the persistence gate, so emit once when it crosses.
        attention_bad = (
            s.student.attention_state in ("OFF_TASK_AWAY", "FACE_MISSING")
            and s.student.time_in_attention_state_seconds >= STUDENT_OFF_TASK_SECONDS
            and s.student.attention_state_confidence >= 0.5
        )
        if attention_state.step(
            is_bad=attention_bad,
            elapsed=elapsed,
            persistence_seconds=0.0,
        ):
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="student_attention",
                value=s.student.time_in_attention_state_seconds,
                direction="above",
                description=(
                    f"Student has been {s.student.attention_state} for "
                    f"{s.student.time_in_attention_state_seconds:.0f}s"
                ),
            ))

        # Prolonged mutual silence. The duration metric already carries the
        # persistence, so emit once when the threshold is crossed.
        if mutual_silence_state.step(
            is_bad=s.session.mutual_silence_duration_current >= MUTUAL_SILENCE_SECONDS,
            elapsed=elapsed,
            persistence_seconds=0.0,
        ):
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="mutual_silence",
                value=s.session.mutual_silence_duration_current,
                direction="above",
                description=(
                    f"Mutual silence reached "
                    f"{s.session.mutual_silence_duration_current:.0f}s"
                ),
            ))

    return flagged
