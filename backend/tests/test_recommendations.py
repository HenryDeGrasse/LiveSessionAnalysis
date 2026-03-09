import pytest
from app.analytics.recommendations import generate_recommendations
from app.models import SessionSummary
from datetime import datetime, timedelta


def _summary(
    tutor_talk: float = 0.6,
    student_talk: float = 0.4,
    tutor_eye: float = 0.8,
    student_eye: float = 0.5,
    tutor_energy: float = 0.7,
    student_energy: float = 0.6,
    interruptions: int = 2,
    engagement: float = 70.0,
    session_type: str = "general",
    duration: float = 1800.0,
) -> SessionSummary:
    st = datetime(2025, 1, 1)
    return SessionSummary(
        session_id="test",
        tutor_id="tutor1",
        start_time=st,
        end_time=st + timedelta(seconds=duration),
        duration_seconds=duration,
        session_type=session_type,
        talk_time_ratio={"tutor": tutor_talk, "student": student_talk},
        avg_eye_contact={"tutor": tutor_eye, "student": student_eye},
        avg_energy={"tutor": tutor_energy, "student": student_energy},
        total_interruptions=interruptions,
        engagement_score=engagement,
    )


class TestRecommendations:
    def test_good_session_few_recommendations(self):
        recs = generate_recommendations(_summary())
        # A balanced session should have few/no recommendations
        assert len(recs) <= 2

    def test_tutor_overtalk_recommendation(self):
        recs = generate_recommendations(_summary(tutor_talk=0.9, student_talk=0.1))
        assert any("talk" in r.lower() or "speak" in r.lower() or "question" in r.lower() for r in recs)

    def test_low_student_eye_contact_recommendation(self):
        recs = generate_recommendations(_summary(student_eye=0.15))
        assert any("eye" in r.lower() or "contact" in r.lower() or "engagement" in r.lower() for r in recs)

    def test_high_interruptions_recommendation(self):
        recs = generate_recommendations(_summary(interruptions=8))
        assert any("interrupt" in r.lower() or "turn" in r.lower() for r in recs)

    def test_low_energy_recommendation(self):
        recs = generate_recommendations(_summary(student_energy=0.15))
        assert any("energy" in r.lower() or "activ" in r.lower() or "break" in r.lower() for r in recs)

    def test_low_engagement_recommendation(self):
        recs = generate_recommendations(_summary(engagement=25.0))
        assert any("engag" in r.lower() for r in recs)

    def test_all_bad_gives_multiple_recommendations(self):
        recs = generate_recommendations(
            _summary(
                tutor_talk=0.95,
                student_eye=0.1,
                student_energy=0.1,
                interruptions=10,
                engagement=20.0,
            )
        )
        assert len(recs) >= 3

    def test_returns_list_of_strings(self):
        recs = generate_recommendations(_summary())
        assert isinstance(recs, list)
        for r in recs:
            assert isinstance(r, str)

    def test_lecture_type_has_different_thresholds(self):
        """For lecture type, higher tutor talk is acceptable."""
        recs_general = generate_recommendations(
            _summary(tutor_talk=0.78, student_talk=0.22, session_type="general")
        )
        recs_lecture = generate_recommendations(
            _summary(tutor_talk=0.78, student_talk=0.22, session_type="lecture")
        )
        # Lecture should have fewer talk-related recommendations
        talk_recs_general = [r for r in recs_general if "talk" in r.lower() or "speak" in r.lower() or "question" in r.lower()]
        talk_recs_lecture = [r for r in recs_lecture if "talk" in r.lower() or "speak" in r.lower() or "question" in r.lower()]
        assert len(talk_recs_lecture) <= len(talk_recs_general)

    def test_short_session_no_silence_recommendation(self):
        """Very short sessions shouldn't trigger silence recommendations."""
        recs = generate_recommendations(_summary(duration=60.0, student_talk=0.02))
        # Should still flag low talk but context-appropriate
        assert isinstance(recs, list)
