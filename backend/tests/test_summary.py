import pytest
from datetime import datetime, timedelta
from app.analytics.summary import generate_summary
from app.models import (
    MetricsSnapshot, ParticipantMetrics, SessionMetrics,
    Nudge, NudgePriority,
)


def _snap(
    session_id: str = "test",
    elapsed: float = 0.0,
    tutor_eye: float = 0.8,
    student_eye: float = 0.5,
    tutor_talk: float = 0.6,
    student_talk: float = 0.4,
    tutor_energy: float = 0.7,
    student_energy: float = 0.6,
    engagement_score: float = 70.0,
    interruptions: int = 0,
    trend: str = "stable",
    degraded: bool = False,
) -> MetricsSnapshot:
    base = datetime(2025, 1, 1)
    return MetricsSnapshot(
        session_id=session_id,
        timestamp=base + timedelta(seconds=elapsed),
        tutor=ParticipantMetrics(
            eye_contact_score=tutor_eye,
            talk_time_percent=tutor_talk,
            energy_score=tutor_energy,
            is_speaking=False,
        ),
        student=ParticipantMetrics(
            eye_contact_score=student_eye,
            talk_time_percent=student_talk,
            energy_score=student_energy,
            is_speaking=False,
        ),
        session=SessionMetrics(
            interruption_count=interruptions,
            engagement_trend=trend,
            engagement_score=engagement_score,
        ),
        degraded=degraded,
    )


class TestGenerateSummary:
    def test_basic_summary_fields(self):
        snapshots = [_snap(elapsed=i * 10) for i in range(10)]
        summary = generate_summary("test", snapshots, tutor_id="alice")
        assert summary.session_id == "test"
        assert summary.tutor_id == "alice"
        assert summary.duration_seconds > 0

    def test_session_type_preserved(self):
        snapshots = [_snap(elapsed=i * 10) for i in range(3)]
        summary = generate_summary("test", snapshots, tutor_id="alice", session_type="practice")
        assert summary.session_type == "practice"

    def test_averages_computed(self):
        snapshots = [
            _snap(elapsed=0, tutor_eye=0.8, student_eye=0.4),
            _snap(elapsed=10, tutor_eye=0.6, student_eye=0.6),
        ]
        summary = generate_summary("test", snapshots)
        assert abs(summary.avg_eye_contact["tutor"] - 0.7) < 0.01
        assert abs(summary.avg_eye_contact["student"] - 0.5) < 0.01

    def test_talk_time_ratio(self):
        snapshots = [
            _snap(elapsed=0, tutor_talk=0.7, student_talk=0.3),
            _snap(elapsed=10, tutor_talk=0.7, student_talk=0.3),
        ]
        summary = generate_summary("test", snapshots)
        assert abs(summary.talk_time_ratio["tutor"] - 0.7) < 0.01
        assert abs(summary.talk_time_ratio["student"] - 0.3) < 0.01

    def test_engagement_score_averaged(self):
        snapshots = [
            _snap(elapsed=0, engagement_score=60.0),
            _snap(elapsed=10, engagement_score=80.0),
        ]
        summary = generate_summary("test", snapshots)
        assert abs(summary.engagement_score - 70.0) < 0.01

    def test_interruption_count_takes_max(self):
        """Interruption count should use the max from snapshots since it's cumulative."""
        snapshots = [
            _snap(elapsed=0, interruptions=1),
            _snap(elapsed=10, interruptions=3),
            _snap(elapsed=20, interruptions=5),
        ]
        summary = generate_summary("test", snapshots)
        assert summary.total_interruptions == 5

    def test_timeline_generated(self):
        snapshots = [_snap(elapsed=i * 10, engagement_score=50.0 + i) for i in range(5)]
        summary = generate_summary("test", snapshots)
        assert "engagement" in summary.timeline
        assert len(summary.timeline["engagement"]) == 5

    def test_timeline_includes_eye_contact(self):
        snapshots = [_snap(elapsed=i * 10) for i in range(3)]
        summary = generate_summary("test", snapshots)
        assert "student_eye_contact" in summary.timeline
        assert "tutor_eye_contact" in summary.timeline

    def test_nudges_counted(self):
        snapshots = [_snap(elapsed=i * 10) for i in range(3)]
        nudges = [
            Nudge(nudge_type="test", message="m1"),
            Nudge(nudge_type="test", message="m2"),
        ]
        summary = generate_summary("test", snapshots, nudges=nudges)
        assert summary.nudges_sent == 2

    def test_degradation_events_counted(self):
        snapshots = [
            _snap(elapsed=0, degraded=False),
            _snap(elapsed=10, degraded=True),
            _snap(elapsed=20, degraded=True),
            _snap(elapsed=30, degraded=False),
            _snap(elapsed=40, degraded=True),
        ]
        summary = generate_summary("test", snapshots)
        # Transitions into degraded: at elapsed=10 and elapsed=40
        assert summary.degradation_events == 2


class TestFlaggedMoments:
    def test_low_engagement_flagged(self):
        snapshots = [
            _snap(elapsed=0, engagement_score=70.0),
            _snap(elapsed=10, engagement_score=35.0),  # < 40
        ]
        summary = generate_summary("test", snapshots)
        flags = [f for f in summary.flagged_moments if f.metric_name == "engagement"]
        assert len(flags) >= 1
        assert flags[0].direction == "below"

    def test_student_silence_flagged(self):
        snapshots = [
            _snap(elapsed=0, student_talk=0.3),
            _snap(elapsed=10, student_talk=0.02),  # < 5%
        ]
        summary = generate_summary("test", snapshots)
        flags = [f for f in summary.flagged_moments if f.metric_name == "student_talk_time"]
        assert len(flags) >= 1

    def test_no_flags_on_normal_session(self):
        snapshots = [_snap(elapsed=i * 10) for i in range(5)]
        summary = generate_summary("test", snapshots)
        assert len(summary.flagged_moments) == 0

    def test_high_interruption_flagged(self):
        snapshots = [
            _snap(elapsed=0, interruptions=0),
            _snap(elapsed=10, interruptions=4),  # >= 3
        ]
        summary = generate_summary("test", snapshots)
        flags = [f for f in summary.flagged_moments if f.metric_name == "interruptions"]
        assert len(flags) >= 1


class TestEmptyInput:
    def test_empty_snapshots(self):
        summary = generate_summary("test", [])
        assert summary.session_id == "test"
        assert summary.duration_seconds == 0
        assert summary.engagement_score == 50.0  # neutral default for empty sessions

    def test_empty_snapshots_preserve_session_type(self):
        summary = generate_summary("test", [], session_type="lecture")
        assert summary.session_type == "lecture"

    def test_single_snapshot(self):
        snapshots = [_snap(elapsed=0)]
        summary = generate_summary("test", snapshots)
        assert summary.duration_seconds == 0
        assert summary.engagement_score == 70.0
