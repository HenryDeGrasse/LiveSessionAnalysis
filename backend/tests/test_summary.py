import pytest
from datetime import datetime, timedelta
from app.analytics.summary import generate_summary
from app.models import (
    MediaProvider,
    MetricsSnapshot,
    ParticipantMetrics,
    SessionMetrics,
    Nudge,
    NudgePriority,
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
    tutor_attention_state: str = "CAMERA_FACING",
    student_attention_state: str = "SCREEN_ENGAGED",
    tutor_turn_count: int = 0,
    student_turn_count: int = 0,
    tutor_is_speaking: bool = False,
    student_is_speaking: bool = False,
    tutor_time_since_spoke: float = 999.0,
    student_time_since_spoke: float = 999.0,
) -> MetricsSnapshot:
    base = datetime(2025, 1, 1)
    return MetricsSnapshot(
        session_id=session_id,
        timestamp=base + timedelta(seconds=elapsed),
        tutor=ParticipantMetrics(
            eye_contact_score=tutor_eye,
            talk_time_percent=tutor_talk,
            energy_score=tutor_energy,
            is_speaking=tutor_is_speaking,
            time_since_spoke_seconds=tutor_time_since_spoke,
            attention_state=tutor_attention_state,
        ),
        student=ParticipantMetrics(
            eye_contact_score=student_eye,
            talk_time_percent=student_talk,
            energy_score=student_energy,
            is_speaking=student_is_speaking,
            time_since_spoke_seconds=student_time_since_spoke,
            attention_state=student_attention_state,
        ),
        session=SessionMetrics(
            interruption_count=interruptions,
            engagement_trend=trend,
            engagement_score=engagement_score,
            tutor_turn_count=tutor_turn_count,
            student_turn_count=student_turn_count,
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
        assert summary.per_student_talk_time_ratio is None

    def test_per_student_talk_time_ratio_includes_primary_and_extra_students(self):
        snapshots = [
            _snap(
                elapsed=0,
                tutor_talk=0.6,
                student_talk=0.4,
            ),
            _snap(
                elapsed=10,
                tutor_talk=0.5,
                student_talk=0.2,
            ),
        ]
        snapshots[-1].per_student_metrics = {
            "1": {"talk_time_percent": 0.15},
            "2": {"talk_time_percent": 0.05},
        }

        summary = generate_summary("test", snapshots)

        assert summary.per_student_talk_time_ratio == {
            "0": 0.2,
            "1": 0.15,
            "2": 0.05,
        }

    def test_engagement_score_averaged(self):
        snapshots = [
            _snap(elapsed=0, engagement_score=60.0),
            _snap(elapsed=10, engagement_score=80.0),
        ]
        summary = generate_summary("test", snapshots)
        assert abs(summary.engagement_score - 70.0) < 0.01

    def test_energy_average_prefers_speaking_snapshots(self):
        snapshots = [
            _snap(elapsed=0, student_energy=0.8, student_is_speaking=True),
            _snap(elapsed=10, student_energy=0.2),
            _snap(elapsed=20, student_energy=0.2),
        ]
        summary = generate_summary("test", snapshots)
        # Speaking-only average should ignore the silent/idle snapshots.
        assert summary.avg_energy["student"] == pytest.approx(0.8)

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
        """Engagement must stay low past warmup for the persistence window."""
        snapshots = [
            _snap(elapsed=0, engagement_score=70.0),
            _snap(elapsed=25, engagement_score=70.0),
            _snap(elapsed=35, engagement_score=70.0),
            _snap(elapsed=45, engagement_score=35.0),
            _snap(elapsed=55, engagement_score=34.0),  # 10s later -> persisted
        ]
        summary = generate_summary("test", snapshots)
        flags = [f for f in summary.flagged_moments if f.metric_name == "engagement"]
        assert len(flags) >= 1
        assert flags[0].direction == "below"
        assert flags[0].timestamp == 55.0

    def test_student_silence_flagged(self):
        """Student silence must persist before flagging."""
        snapshots = [
            _snap(elapsed=0, student_talk=0.3),
            _snap(elapsed=25, student_talk=0.3),
            _snap(elapsed=35, student_talk=0.3),
            _snap(elapsed=45, student_talk=0.02),
            _snap(elapsed=60, student_talk=0.02),  # 15s later -> persisted
        ]
        summary = generate_summary("test", snapshots)
        flags = [f for f in summary.flagged_moments if f.metric_name == "student_talk_time"]
        assert len(flags) >= 1
        assert flags[0].timestamp == 60.0

    def test_no_flags_on_normal_session(self):
        snapshots = [_snap(elapsed=i * 10) for i in range(10)]
        summary = generate_summary("test", snapshots)
        assert len(summary.flagged_moments) == 0

    def test_high_interruption_flagged(self):
        """High interruptions after warmup should be flagged immediately on crossing."""
        snapshots = [
            _snap(elapsed=0, interruptions=0),
            _snap(elapsed=25, interruptions=0),
            _snap(elapsed=35, interruptions=0),
            _snap(elapsed=45, interruptions=4),  # >= 3
        ]
        summary = generate_summary("test", snapshots)
        flags = [f for f in summary.flagged_moments if f.metric_name == "interruptions"]
        assert len(flags) >= 1
        assert flags[0].timestamp == 45.0

    def test_no_flags_during_warmup_period(self):
        """Nothing should be flagged during the first 30 seconds, even with bad data."""
        snapshots = [
            _snap(elapsed=0, engagement_score=10.0, student_talk=0.0, student_energy=0.0, interruptions=10),
            _snap(elapsed=3, engagement_score=10.0, student_talk=0.0, student_energy=0.0, interruptions=10),
            _snap(elapsed=10, engagement_score=10.0, student_talk=0.0, student_energy=0.0, interruptions=10),
            _snap(elapsed=20, engagement_score=10.0, student_talk=0.0, student_energy=0.0, interruptions=10),
        ]
        summary = generate_summary("test", snapshots)
        assert len(summary.flagged_moments) == 0

    def test_low_metric_during_warmup_can_flag_later_if_it_stays_bad(self):
        """A metric that's already bad in warmup should not flag immediately at 30s,
        but can still flag later if it remains bad long enough."""
        snapshots = [
            _snap(elapsed=0, engagement_score=30.0),
            _snap(elapsed=15, engagement_score=30.0),
            _snap(elapsed=25, engagement_score=30.0),
            _snap(elapsed=35, engagement_score=30.0),
            _snap(elapsed=45, engagement_score=30.0),
        ]
        summary = generate_summary("test", snapshots)
        engagement_flags = [f for f in summary.flagged_moments if f.metric_name == "engagement"]
        assert len(engagement_flags) == 1
        assert engagement_flags[0].timestamp == 45.0

    def test_recovery_then_drop_requires_new_persistence_window(self):
        """Metric bad during warmup -> recovers -> drops again should require a fresh
        persistence window before flagging."""
        snapshots = [
            _snap(elapsed=0, engagement_score=30.0),
            _snap(elapsed=25, engagement_score=30.0),
            _snap(elapsed=35, engagement_score=70.0),
            _snap(elapsed=45, engagement_score=30.0),
            _snap(elapsed=55, engagement_score=30.0),
        ]
        summary = generate_summary("test", snapshots)
        engagement_flags = [f for f in summary.flagged_moments if f.metric_name == "engagement"]
        assert len(engagement_flags) == 1
        assert engagement_flags[0].timestamp == 55.0

    def test_low_student_energy_requires_speech_evidence(self):
        """Low energy should not be flagged for a student who never actually spoke."""
        snapshots = [
            _snap(elapsed=0, student_energy=0.05),
            _snap(elapsed=35, student_energy=0.05),
            _snap(elapsed=45, student_energy=0.05),
            _snap(elapsed=55, student_energy=0.05),
            _snap(elapsed=65, student_energy=0.05),
        ]
        summary = generate_summary("test", snapshots)
        energy_flags = [f for f in summary.flagged_moments if f.metric_name == "student_energy"]
        assert len(energy_flags) == 0

    def test_low_student_energy_flagged_after_speech_evidence_and_persistence(self):
        """Low speaking energy should only flag after recent speech evidence exists."""
        snapshots = [
            _snap(elapsed=0, student_energy=0.5),
            _snap(elapsed=35, student_energy=0.14, student_is_speaking=True, student_time_since_spoke=0.0),
            _snap(elapsed=40, student_energy=0.13, student_time_since_spoke=1.0),
            _snap(elapsed=45, student_energy=0.12, student_time_since_spoke=1.0),
            _snap(elapsed=50, student_energy=0.11, student_time_since_spoke=1.0),
            _snap(elapsed=55, student_energy=0.10, student_time_since_spoke=1.0),
        ]
        summary = generate_summary("test", snapshots)
        energy_flags = [f for f in summary.flagged_moments if f.metric_name == "student_energy"]
        assert len(energy_flags) == 1
        assert energy_flags[0].timestamp == 55.0


class TestAttentionStateDistribution:
    def test_attention_state_distribution_computed(self):
        """Varying attention states should produce correct percentage distribution."""
        snapshots = [
            _snap(elapsed=0, tutor_attention_state="CAMERA_FACING", student_attention_state="SCREEN_ENGAGED"),
            _snap(elapsed=10, tutor_attention_state="CAMERA_FACING", student_attention_state="SCREEN_ENGAGED"),
            _snap(elapsed=20, tutor_attention_state="SCREEN_ENGAGED", student_attention_state="CAMERA_FACING"),
            _snap(elapsed=30, tutor_attention_state="SCREEN_ENGAGED", student_attention_state="OFF_TASK_AWAY"),
        ]
        summary = generate_summary("test", snapshots)
        dist = summary.attention_state_distribution

        # Both participants should be present
        assert "tutor" in dist
        assert "student" in dist

        # Tutor: 2/4 CAMERA_FACING = 0.5, 2/4 SCREEN_ENGAGED = 0.5
        assert abs(dist["tutor"]["CAMERA_FACING"] - 0.5) < 0.01
        assert abs(dist["tutor"]["SCREEN_ENGAGED"] - 0.5) < 0.01

        # Student: 2/4 SCREEN_ENGAGED = 0.5, 1/4 CAMERA_FACING = 0.25, 1/4 OFF_TASK_AWAY = 0.25
        assert abs(dist["student"]["SCREEN_ENGAGED"] - 0.5) < 0.01
        assert abs(dist["student"]["CAMERA_FACING"] - 0.25) < 0.01
        assert abs(dist["student"]["OFF_TASK_AWAY"] - 0.25) < 0.01

        # Each participant's percentages should sum to ~1.0
        assert abs(sum(dist["tutor"].values()) - 1.0) < 0.01
        assert abs(sum(dist["student"].values()) - 1.0) < 0.01

    def test_single_state_distribution(self):
        """All snapshots with same state should produce 100% for that state."""
        snapshots = [
            _snap(elapsed=i * 10, tutor_attention_state="CAMERA_FACING", student_attention_state="CAMERA_FACING")
            for i in range(5)
        ]
        summary = generate_summary("test", snapshots)
        dist = summary.attention_state_distribution
        assert abs(dist["tutor"]["CAMERA_FACING"] - 1.0) < 0.01
        assert abs(dist["student"]["CAMERA_FACING"] - 1.0) < 0.01


class TestNudgeDetails:
    def test_nudge_details_serialized(self):
        """Nudge objects should be serialized into nudge_details dicts."""
        snapshots = [_snap(elapsed=i * 10) for i in range(3)]
        ts1 = datetime(2025, 6, 1, 10, 0, 0)
        ts2 = datetime(2025, 6, 1, 10, 5, 0)
        nudges = [
            Nudge(nudge_type="silence", message="Student has been quiet", timestamp=ts1, priority=NudgePriority.HIGH),
            Nudge(nudge_type="eye_contact", message="Low eye contact", timestamp=ts2, priority=NudgePriority.LOW),
        ]
        summary = generate_summary("test", snapshots, nudges=nudges)

        assert len(summary.nudge_details) == 2

        nd0 = summary.nudge_details[0]
        assert nd0["nudge_type"] == "silence"
        assert nd0["message"] == "Student has been quiet"
        assert nd0["timestamp"] == ts1.isoformat()
        assert nd0["priority"] == "high"

        nd1 = summary.nudge_details[1]
        assert nd1["nudge_type"] == "eye_contact"
        assert nd1["message"] == "Low eye contact"
        assert nd1["timestamp"] == ts2.isoformat()
        assert nd1["priority"] == "low"

    def test_no_nudges_empty_details(self):
        """No nudges should produce empty nudge_details."""
        snapshots = [_snap(elapsed=0)]
        summary = generate_summary("test", snapshots, nudges=None)
        assert summary.nudge_details == []

    def test_nudge_details_preserves_count(self):
        """nudges_sent count should still be correct alongside nudge_details."""
        snapshots = [_snap(elapsed=0)]
        nudges = [
            Nudge(nudge_type="test", message="m1"),
            Nudge(nudge_type="test", message="m2"),
            Nudge(nudge_type="test", message="m3"),
        ]
        summary = generate_summary("test", snapshots, nudges=nudges)
        assert summary.nudges_sent == 3
        assert len(summary.nudge_details) == 3


class TestTurnCounts:
    def test_turn_counts_from_last_snapshot(self):
        """Turn counts should come from the last snapshot's session metrics."""
        snapshots = [
            _snap(elapsed=0, tutor_turn_count=1, student_turn_count=0),
            _snap(elapsed=10, tutor_turn_count=3, student_turn_count=2),
            _snap(elapsed=20, tutor_turn_count=5, student_turn_count=4),
        ]
        summary = generate_summary("test", snapshots)
        assert summary.turn_counts == {"tutor": 5, "student": 4}

    def test_turn_counts_zero_defaults(self):
        """Snapshots with default turn counts should produce zeros."""
        snapshots = [_snap(elapsed=0)]
        summary = generate_summary("test", snapshots)
        assert summary.turn_counts == {"tutor": 0, "student": 0}


class TestSummaryEndToEnd:
    def test_summary_with_all_new_fields_end_to_end(self):
        # Snapshots span 0-120s so that the warmup period (first 30s) passes
        # and the bad metrics at elapsed=90 and 120 produce real flagged moments.
        snapshots = [
            _snap(
                session_id="session-123",
                elapsed=0,
                tutor_eye=0.9,
                student_eye=0.7,
                tutor_talk=0.7,
                student_talk=0.3,
                tutor_energy=0.85,
                student_energy=0.75,
                engagement_score=82.0,
                interruptions=1,
                tutor_attention_state="CAMERA_FACING",
                student_attention_state="SCREEN_ENGAGED",
                tutor_turn_count=1,
                student_turn_count=1,
            ),
            _snap(
                session_id="session-123",
                elapsed=30,
                tutor_eye=0.8,
                student_eye=0.6,
                tutor_talk=0.67,
                student_talk=0.33,
                tutor_energy=0.80,
                student_energy=0.70,
                engagement_score=78.0,
                interruptions=1,
                tutor_attention_state="CAMERA_FACING",
                student_attention_state="SCREEN_ENGAGED",
                tutor_turn_count=2,
                student_turn_count=2,
                student_time_since_spoke=1.0,
            ),
            _snap(
                session_id="session-123",
                elapsed=60,
                tutor_eye=0.7,
                student_eye=0.45,
                tutor_talk=0.64,
                student_talk=0.36,
                tutor_energy=0.74,
                student_energy=0.45,
                engagement_score=68.0,
                interruptions=2,
                tutor_attention_state="SCREEN_ENGAGED",
                student_attention_state="CAMERA_FACING",
                tutor_turn_count=4,
                student_turn_count=3,
                student_time_since_spoke=1.0,
            ),
            _snap(
                session_id="session-123",
                elapsed=90,
                tutor_eye=0.65,
                student_eye=0.30,
                tutor_talk=0.63,
                student_talk=0.37,
                tutor_energy=0.70,
                student_energy=0.12,
                engagement_score=38.0,
                interruptions=4,
                tutor_attention_state="SCREEN_ENGAGED",
                student_attention_state="OFF_TASK_AWAY",
                tutor_turn_count=5,
                student_turn_count=4,
                student_time_since_spoke=1.0,
            ),
            _snap(
                session_id="session-123",
                elapsed=120,
                tutor_eye=0.6,
                student_eye=0.22,
                tutor_talk=0.62,
                student_talk=0.38,
                tutor_energy=0.68,
                student_energy=0.1,
                engagement_score=35.0,
                interruptions=5,
                degraded=True,
                tutor_attention_state="SCREEN_ENGAGED",
                student_attention_state="OFF_TASK_AWAY",
                tutor_turn_count=6,
                student_turn_count=5,
                student_time_since_spoke=1.0,
            ),
        ]
        # Set attention duration & silence on the last two snapshots
        snapshots[3].student.time_in_attention_state_seconds = 65.0
        snapshots[3].student.attention_state_confidence = 0.9
        snapshots[3].session.mutual_silence_duration_current = 46.0
        snapshots[4].student.time_in_attention_state_seconds = 95.0
        snapshots[4].student.attention_state_confidence = 0.9
        snapshots[4].session.mutual_silence_duration_current = 50.0

        first_nudge_time = datetime(2025, 6, 1, 10, 0, 0)
        second_nudge_time = datetime(2025, 6, 1, 10, 3, 0)
        nudges = [
            Nudge(
                nudge_type="silence",
                message="Invite the student back in",
                timestamp=first_nudge_time,
                priority=NudgePriority.HIGH,
            ),
            Nudge(
                nudge_type="eye_contact",
                message="Student camera-facing dropped",
                timestamp=second_nudge_time,
                priority=NudgePriority.MEDIUM,
            ),
        ]

        summary = generate_summary(
            "session-123",
            snapshots,
            tutor_id="alice",
            session_type="practice",
            media_provider=MediaProvider.CUSTOM_WEBRTC,
            nudges=nudges,
        )

        assert summary.session_id == "session-123"
        assert summary.tutor_id == "alice"
        assert summary.session_type == "practice"
        assert summary.media_provider == MediaProvider.CUSTOM_WEBRTC
        assert summary.duration_seconds == 120.0

        # Talk time ratio uses last snapshot's cumulative values
        assert summary.talk_time_ratio == {"tutor": 0.62, "student": 0.38}
        assert summary.total_interruptions == 5
        assert summary.nudges_sent == 2
        assert summary.degradation_events == 1

        assert summary.nudge_details == [
            {
                "nudge_type": "silence",
                "message": "Invite the student back in",
                "timestamp": first_nudge_time.isoformat(),
                "priority": "high",
            },
            {
                "nudge_type": "eye_contact",
                "message": "Student camera-facing dropped",
                "timestamp": second_nudge_time.isoformat(),
                "priority": "medium",
            },
        ]
        assert summary.turn_counts == {"tutor": 6, "student": 5}

        # Flagged moments should fire AFTER warmup (>= 30s) for all five metrics
        flagged_metric_names = {flag.metric_name for flag in summary.flagged_moments}
        assert "engagement" in flagged_metric_names
        assert "interruptions" in flagged_metric_names
        assert "student_energy" in flagged_metric_names
        assert "student_attention" in flagged_metric_names
        assert "mutual_silence" in flagged_metric_names

        # No flag should have a timestamp before 30s
        for flag in summary.flagged_moments:
            assert flag.timestamp >= 30.0, (
                f"Flag '{flag.metric_name}' at {flag.timestamp}s is inside warmup"
            )


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

    def test_empty_snapshots_new_fields_default(self):
        """Empty snapshot input should produce empty defaults for all three new fields."""
        summary = generate_summary("test", [])
        assert summary.attention_state_distribution == {}
        assert summary.nudge_details == []
        assert summary.turn_counts == {}
