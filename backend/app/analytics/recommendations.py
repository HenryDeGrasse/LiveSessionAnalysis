from __future__ import annotations

from ..models import SessionSummary

# Talk time thresholds by session type
_TUTOR_TALK_THRESHOLDS = {
    "general": 0.75,
    "lecture": 0.85,
    "practice": 0.55,
    "discussion": 0.60,
}


def generate_recommendations(summary: SessionSummary) -> list[str]:
    """Generate actionable coaching recommendations based on session metrics."""
    recs = []

    tutor_talk = summary.talk_time_ratio.get("tutor", 0.5)
    student_eye = summary.avg_eye_contact.get("student", 0.5)
    student_energy = summary.avg_energy.get("student", 0.5)
    engagement = summary.engagement_score

    # Tutor overtalk
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

    # High interruptions
    if summary.total_interruptions >= 5:
        recs.append(
            f"There were {summary.total_interruptions} interruptions during the session. "
            "Consider establishing clearer turn-taking signals or pausing before responding."
        )

    # Low student energy
    if student_energy < 0.25:
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

    return recs
