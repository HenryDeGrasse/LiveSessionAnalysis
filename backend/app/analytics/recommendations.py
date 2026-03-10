from __future__ import annotations

from ..coaching_system.profiles import get_profile
from ..models import SessionSummary

# Talk time thresholds by session type (pulled from profiles)
_TUTOR_TALK_THRESHOLDS = {
    "general": 0.75,
    "lecture": 0.85,
    "practice": 0.55,
    "discussion": 0.60,
    "socratic": 0.65,
}


def generate_recommendations(summary: SessionSummary) -> list[str]:
    """Generate actionable coaching recommendations based on session metrics."""
    # Don't generate recommendations for very short or empty sessions
    if summary.duration_seconds < 30:
        return []

    recs = []
    profile = get_profile(summary.session_type)

    tutor_talk = summary.talk_time_ratio.get("tutor", 0.5)
    student_eye = summary.avg_eye_contact.get("student", 0.5)
    student_energy = summary.avg_energy.get("student", 0.5)
    tutor_energy = summary.avg_energy.get("tutor", 0.5)
    engagement = summary.engagement_score

    # Tutor overtalk (session-type-aware)
    threshold = _TUTOR_TALK_THRESHOLDS.get(summary.session_type, 0.75)
    if tutor_talk > threshold:
        recs.append(
            "Try asking more open-ended questions to encourage student participation. "
            f"Tutor talk time was {tutor_talk:.0%}, consider aiming for under {threshold:.0%}."
        )

    # Low student eye contact
    if student_eye < 0.3:
        recs.append(
            "Student eye contact was low. Try using direct address, checking for understanding, "
            "or varying your presentation to re-engage visual attention."
        )

    # High interruptions (session-type-aware)
    int_threshold = max(3, profile.interruption_spike_count + 2)
    if summary.total_interruptions >= int_threshold:
        recs.append(
            f"There were {summary.total_interruptions} interruptions during the session. "
            "Consider establishing clearer turn-taking signals or pausing before responding."
        )

    # Low student energy — contextual message based on session type
    if student_energy < 0.25:
        if summary.session_type == "lecture":
            recs.append(
                "Student energy was low, though this can be normal during lectures. "
                "Consider incorporating brief check-in questions or interactive moments "
                "to gauge understanding."
            )
        else:
            recs.append(
                "Student energy was notably low. Consider incorporating more interactive activities, "
                "taking short breaks, or checking in on the student's comfort and understanding."
            )

    # Low engagement
    if engagement < 40.0:
        recs.append(
            f"Overall engagement score was {engagement:.0f}/100. "
            "Consider reviewing session pacing, incorporating more interactive elements, "
            "and checking for comprehension more frequently."
        )

    # Flagged attention issues
    attention_flags = [
        f for f in summary.flagged_moments
        if f.metric_name == "student_attention"
    ]
    if attention_flags:
        recs.append(
            "The student appeared away from the screen for extended periods. "
            "Consider checking whether they are following along, or if there's "
            "a technical issue with their setup."
        )

    # Mutual silence flags
    silence_flags = [
        f for f in summary.flagged_moments
        if f.metric_name == "mutual_silence"
    ]
    if len(silence_flags) >= 2:
        recs.append(
            "There were multiple periods of extended silence. This may indicate "
            "pacing issues or uncertainty. Consider providing clearer prompts "
            "or breaking content into smaller segments."
        )

    return recs
