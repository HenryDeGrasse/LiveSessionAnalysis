from __future__ import annotations

from typing import Optional

from ..models import (
    FlaggedMoment,
    MediaProvider,
    MetricsSnapshot,
    Nudge,
    SessionSummary,
)

# Thresholds for flagged moments
ENGAGEMENT_LOW = 40.0
STUDENT_TALK_LOW = 0.05
INTERRUPTION_HIGH = 3
STUDENT_EYE_LOW = 0.3
ENERGY_LOW = 0.2


def generate_summary(
    session_id: str,
    snapshots: list[MetricsSnapshot],
    tutor_id: str = "",
    session_type: str = "general",
    media_provider: MediaProvider = MediaProvider.CUSTOM_WEBRTC,
    nudges: Optional[list[Nudge]] = None,
) -> SessionSummary:
    """Generate a post-session summary from collected metrics snapshots."""
    if not snapshots:
        from datetime import datetime
        now = datetime.utcnow()
        return SessionSummary(
            session_id=session_id,
            tutor_id=tutor_id,
            session_type=session_type,
            media_provider=media_provider,
            start_time=now,
            end_time=now,
            duration_seconds=0,
        )

    start_time = snapshots[0].timestamp
    end_time = snapshots[-1].timestamp
    duration = (end_time - start_time).total_seconds()

    n = len(snapshots)

    # Use LAST snapshot's cumulative talk-time ratios (more accurate than averaging)
    last = snapshots[-1]
    final_tutor_talk = last.tutor.talk_time_percent
    final_student_talk = last.student.talk_time_percent

    # Average other metrics normally
    avg_tutor_eye = sum(s.tutor.eye_contact_score for s in snapshots) / n
    avg_student_eye = sum(s.student.eye_contact_score for s in snapshots) / n
    avg_tutor_energy = sum(s.tutor.energy_score for s in snapshots) / n
    avg_student_energy = sum(s.student.energy_score for s in snapshots) / n
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

    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        session_type=session_type,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration,
        media_provider=media_provider,
        talk_time_ratio={"tutor": final_tutor_talk, "student": final_student_talk},
        avg_eye_contact={"tutor": avg_tutor_eye, "student": avg_student_eye},
        avg_energy={"tutor": avg_tutor_energy, "student": avg_student_energy},
        total_interruptions=total_interruptions,
        engagement_score=avg_engagement,
        flagged_moments=flagged,
        timeline=timeline,
        nudges_sent=len(nudges) if nudges else 0,
        degradation_events=degradation_events,
    )


STUDENT_ENERGY_LOW = 0.15
STUDENT_OFF_TASK_SECONDS = 60.0
MUTUAL_SILENCE_SECONDS = 45.0


def _detect_flagged_moments(
    snapshots: list[MetricsSnapshot],
    start_time,
) -> list[FlaggedMoment]:
    flagged = []
    prev_engagement_ok = True
    prev_student_talk_ok = True
    prev_interruption_ok = True
    prev_student_energy_ok = True
    prev_attention_ok = True
    prev_mutual_silence_ok = True

    for s in snapshots:
        elapsed = (s.timestamp - start_time).total_seconds()

        # Low engagement
        eng_ok = s.session.engagement_score >= ENGAGEMENT_LOW
        if not eng_ok and prev_engagement_ok:
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="engagement",
                value=s.session.engagement_score,
                direction="below",
                description=f"Engagement dropped to {s.session.engagement_score:.0f}",
            ))
        prev_engagement_ok = eng_ok

        # Student silence
        talk_ok = s.student.talk_time_percent >= STUDENT_TALK_LOW
        if not talk_ok and prev_student_talk_ok:
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="student_talk_time",
                value=s.student.talk_time_percent,
                direction="below",
                description="Student talk time dropped below 5%",
            ))
        prev_student_talk_ok = talk_ok

        # High interruptions
        int_ok = s.session.interruption_count < INTERRUPTION_HIGH
        if not int_ok and prev_interruption_ok:
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="interruptions",
                value=float(s.session.interruption_count),
                direction="above",
                description=f"Interruption count reached {s.session.interruption_count}",
            ))
        prev_interruption_ok = int_ok

        # Student energy drop (post-session signal — moved out of live nudges)
        energy_ok = s.student.energy_score >= STUDENT_ENERGY_LOW
        if not energy_ok and prev_student_energy_ok:
            flagged.append(FlaggedMoment(
                timestamp=elapsed,
                metric_name="student_energy",
                value=s.student.energy_score,
                direction="below",
                description=f"Student energy dropped to {s.student.energy_score:.2f}",
            ))
        prev_student_energy_ok = energy_ok

        # Sustained off-task / face missing
        attention_ok = not (
            s.student.attention_state in ("OFF_TASK_AWAY", "FACE_MISSING")
            and s.student.time_in_attention_state_seconds >= STUDENT_OFF_TASK_SECONDS
            and s.student.attention_state_confidence >= 0.5
        )
        if not attention_ok and prev_attention_ok:
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
        prev_attention_ok = attention_ok

        # Prolonged mutual silence
        silence_ok = (
            s.session.mutual_silence_duration_current < MUTUAL_SILENCE_SECONDS
        )
        if not silence_ok and prev_mutual_silence_ok:
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
        prev_mutual_silence_ok = silence_ok

    return flagged
