from __future__ import annotations

from typing import Literal

from ..models import SessionSummary, TrendData


def _classify_trend(values: list[float], inverted: bool = False) -> Literal["improving", "stable", "declining"]:
    """Classify a series as improving, stable, or declining using linear regression slope.

    If inverted=True, a decreasing value means improving (e.g., interruptions).
    """
    if len(values) < 2:
        return "stable"

    n = len(values)
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n

    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return "stable"

    slope = numerator / denominator

    # Normalize slope relative to value range for threshold comparison
    val_range = max(values) - min(values) if max(values) != min(values) else 1.0
    normalized_slope = slope / val_range if val_range > 0 else 0.0

    threshold = 0.1  # 10% of range per step = meaningful trend

    if inverted:
        if normalized_slope < -threshold:
            return "improving"
        elif normalized_slope > threshold:
            return "declining"
    else:
        if normalized_slope > threshold:
            return "improving"
        elif normalized_slope < -threshold:
            return "declining"

    return "stable"


def compute_trends(tutor_id: str, sessions: list[SessionSummary]) -> TrendData:
    """Compute cross-session trends from a list of session summaries."""
    if not sessions:
        return TrendData(tutor_id=tutor_id)

    # Sort chronologically
    sorted_sessions = sorted(sessions, key=lambda s: s.start_time)

    # Extract per-session data points
    session_data = []
    engagements = []
    student_eyes = []
    interruptions = []
    tutor_talks = []

    for s in sorted_sessions:
        session_data.append({
            "session_id": s.session_id,
            "start_time": s.start_time.isoformat(),
            "duration_seconds": s.duration_seconds,
            "engagement_score": s.engagement_score,
            "student_eye_contact": s.avg_eye_contact.get("student", 0.0),
            "tutor_eye_contact": s.avg_eye_contact.get("tutor", 0.0),
            "tutor_talk_ratio": s.talk_time_ratio.get("tutor", 0.0),
            "interruptions": s.total_interruptions,
        })
        engagements.append(s.engagement_score)
        student_eyes.append(s.avg_eye_contact.get("student", 0.0))
        interruptions.append(float(s.total_interruptions))
        tutor_talks.append(s.talk_time_ratio.get("tutor", 0.5))

    # Compute trends
    trends = {
        "engagement": _classify_trend(engagements),
        "student_eye_contact": _classify_trend(student_eyes),
        "interruptions": _classify_trend(interruptions, inverted=True),
        "talk_time_balance": _classify_trend(tutor_talks, inverted=True),
    }

    return TrendData(
        tutor_id=tutor_id,
        sessions=session_data,
        trends=trends,
    )
