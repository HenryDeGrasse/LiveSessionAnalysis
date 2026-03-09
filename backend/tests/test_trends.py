import pytest
from datetime import datetime, timedelta
from app.analytics.trends import compute_trends
from app.models import SessionSummary, FlaggedMoment


def _summary(
    session_id: str = "s1",
    tutor_id: str = "tutor1",
    start_offset_hours: int = 0,
    engagement: float = 70.0,
    tutor_eye: float = 0.8,
    student_eye: float = 0.5,
    tutor_talk: float = 0.6,
    student_talk: float = 0.4,
    interruptions: int = 2,
) -> SessionSummary:
    base = datetime(2025, 1, 1)
    st = base + timedelta(hours=start_offset_hours)
    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        start_time=st,
        end_time=st + timedelta(minutes=30),
        duration_seconds=1800,
        talk_time_ratio={"tutor": tutor_talk, "student": student_talk},
        avg_eye_contact={"tutor": tutor_eye, "student": student_eye},
        avg_energy={"tutor": 0.7, "student": 0.6},
        total_interruptions=interruptions,
        engagement_score=engagement,
    )


class TestComputeTrends:
    def test_empty_sessions(self):
        result = compute_trends("tutor1", [])
        assert result.tutor_id == "tutor1"
        assert result.sessions == []
        assert result.trends == {}

    def test_single_session(self):
        result = compute_trends("tutor1", [_summary()])
        assert len(result.sessions) == 1
        # With one session, trend is stable
        assert result.trends.get("engagement") == "stable"

    def test_improving_engagement(self):
        sessions = [
            _summary(session_id=f"s{i}", start_offset_hours=i, engagement=50.0 + i * 5)
            for i in range(5)
        ]
        result = compute_trends("tutor1", sessions)
        assert result.trends["engagement"] == "improving"

    def test_declining_engagement(self):
        sessions = [
            _summary(session_id=f"s{i}", start_offset_hours=i, engagement=90.0 - i * 10)
            for i in range(5)
        ]
        result = compute_trends("tutor1", sessions)
        assert result.trends["engagement"] == "declining"

    def test_stable_engagement(self):
        sessions = [
            _summary(session_id=f"s{i}", start_offset_hours=i, engagement=70.0 + (i % 2))
            for i in range(5)
        ]
        result = compute_trends("tutor1", sessions)
        assert result.trends["engagement"] == "stable"

    def test_eye_contact_trend(self):
        sessions = [
            _summary(session_id=f"s{i}", start_offset_hours=i, student_eye=0.3 + i * 0.1)
            for i in range(5)
        ]
        result = compute_trends("tutor1", sessions)
        assert result.trends["student_eye_contact"] == "improving"

    def test_interruption_trend(self):
        # Fewer interruptions over time = improving
        sessions = [
            _summary(session_id=f"s{i}", start_offset_hours=i, interruptions=10 - i * 2)
            for i in range(5)
        ]
        result = compute_trends("tutor1", sessions)
        assert result.trends["interruptions"] == "improving"

    def test_sessions_ordered_chronologically(self):
        sessions = [
            _summary(session_id="new", start_offset_hours=10, engagement=80.0),
            _summary(session_id="old", start_offset_hours=0, engagement=60.0),
        ]
        result = compute_trends("tutor1", sessions)
        assert result.sessions[0]["session_id"] == "old"
        assert result.sessions[1]["session_id"] == "new"

    def test_talk_time_balance_trend(self):
        # Tutor talk decreasing (more balanced) = improving
        sessions = [
            _summary(session_id=f"s{i}", start_offset_hours=i, tutor_talk=0.9 - i * 0.05)
            for i in range(5)
        ]
        result = compute_trends("tutor1", sessions)
        assert result.trends["talk_time_balance"] == "improving"

    def test_session_data_includes_key_metrics(self):
        result = compute_trends("tutor1", [_summary()])
        s = result.sessions[0]
        assert "engagement_score" in s
        assert "student_eye_contact" in s
        assert "interruptions" in s
        assert "start_time" in s
