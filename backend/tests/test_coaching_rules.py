import time
import pytest
import app.coaching_system.coach as coach_module
from app.coaching_system.coach import Coach
from app.coaching_system.rules import DEFAULT_RULES, CoachingRule
from app.models import (
    MetricsSnapshot, ParticipantMetrics, SessionMetrics, NudgePriority,
)


def _make_snapshot(**overrides) -> MetricsSnapshot:
    """Create a MetricsSnapshot with sensible defaults, overridable."""
    tutor = overrides.pop("tutor", None) or ParticipantMetrics(
        eye_contact_score=0.8,
        talk_time_percent=0.6,
        energy_score=0.7,
        is_speaking=False,
    )
    student = overrides.pop("student", None) or ParticipantMetrics(
        eye_contact_score=0.7,
        talk_time_percent=0.4,
        energy_score=0.6,
        is_speaking=False,
    )
    session = overrides.pop("session", None) or SessionMetrics(
        interruption_count=0,
        engagement_trend="stable",
        engagement_score=70.0,
    )
    return MetricsSnapshot(
        session_id="test",
        tutor=tutor,
        student=student,
        session=session,
        **overrides,
    )


class TestStudentSilenceRule:
    def test_fires_when_student_silent(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.02,
                energy_score=0.5,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=181,
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)  # > 180s threshold
        types = [n.nudge_type for n in nudges]
        assert "student_silence" in types

    def test_does_not_fire_when_student_speaking(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.3,
                energy_score=0.5,
                is_speaking=True,
            ),
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=0,
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_silence" not in types

    def test_does_not_fire_early_in_session(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.02,
                energy_score=0.5,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=181,
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=30)  # Too early
        types = [n.nudge_type for n in nudges]
        assert "student_silence" not in types


class TestLowEyeContactRule:
    def test_fires_on_low_contact(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,  # Very low
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "low_eye_contact" in types

    def test_does_not_fire_on_good_contact(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.8,  # Good
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "low_eye_contact" not in types

    def test_does_not_fire_when_gaze_is_unavailable(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
            ),
            gaze_unavailable=True,
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "low_eye_contact" not in types

    def test_does_not_fire_for_down_engaged_student(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="DOWN_ENGAGED",
                attention_state_confidence=0.9,
                face_presence_score=1.0,
                visual_attention_score=0.72,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "low_eye_contact" not in types


class TestTutorOvertalkRule:
    def test_fires_when_tutor_dominates(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.9,
                energy_score=0.7,
                is_speaking=True,
            ),
            session=SessionMetrics(
                interruption_count=0,
                recent_tutor_talk_percent=0.9,  # 90% > 80% threshold
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "tutor_overtalk" in types

    def test_does_not_fire_balanced(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.6,
                energy_score=0.7,
                is_speaking=True,
            ),
            session=SessionMetrics(
                interruption_count=0,
                recent_tutor_talk_percent=0.6,  # 60% < 80% threshold
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "tutor_overtalk" not in types


class TestEnergyDropRule:
    def test_fires_on_low_energy(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.4,
                energy_score=0.1,  # Very low
                is_speaking=False,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "energy_drop" in types

    def test_does_not_fire_on_good_energy(self):
        coach = Coach()
        snapshot = _make_snapshot()  # Default has good energy
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "energy_drop" not in types


class TestInterruptionSpikeRule:
    def test_fires_on_many_recent_interruptions(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.6,
                energy_score=0.7,
                is_speaking=True,
            ),
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=3,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                recent_tutor_talk_percent=0.7,
                engagement_trend="stable",
                engagement_score=60.0,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "interruption_spike" in types

    def test_does_not_fire_on_old_interruptions_alone(self):
        coach = Coach()
        snapshot = _make_snapshot(
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=1,
                hard_interruption_count=1,
                recent_hard_interruptions=1,
                recent_tutor_talk_percent=0.7,
                engagement_trend="stable",
                engagement_score=70.0,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "interruption_spike" not in types

    def test_does_not_fire_while_both_currently_silent(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.6,
                energy_score=0.7,
                is_speaking=False,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.7,
                talk_time_percent=0.4,
                energy_score=0.6,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=3,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                recent_tutor_talk_percent=0.4,
                engagement_trend="stable",
                engagement_score=60.0,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        types = [n.nudge_type for n in nudges]
        assert "interruption_spike" not in types


class TestNoNudgesEarlyInSession:
    def test_no_nudges_before_min_elapsed(self):
        """No rules should fire before min_session_elapsed."""
        coach = Coach()
        # Create worst-case scenario
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.99,
                energy_score=0.0,
                is_speaking=True,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.01,
                energy_score=0.0,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=10,
                engagement_trend="declining",
                engagement_score=5.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=10)  # Very early
        assert len(nudges) == 0


class TestMultipleRulesCanFire:
    def test_only_one_live_nudge_is_shown_per_check(self):
        """Live coaching should emit at most one nudge per evaluation."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.95,
                energy_score=0.1,
                is_speaking=True,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.02,
                energy_score=0.1,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=3,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                silence_duration_current=200,
                recent_tutor_talk_percent=0.95,
                engagement_trend="declining",
                engagement_score=10.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        assert len(nudges) == 1


class TestGlobalCoachGuardrails:
    def test_no_nudges_when_degraded(self):
        coach = Coach()
        snapshot = _make_snapshot(
            degraded=True,
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.02,
                energy_score=0.1,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=3,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                silence_duration_current=200,
                recent_tutor_talk_percent=0.9,
                engagement_trend="declining",
                engagement_score=10.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        assert nudges == []

    def test_global_nudge_interval_applies_across_rules(self, monkeypatch):
        rules = [
            CoachingRule(
                name="r1",
                nudge_type="rule-one",
                condition=lambda snapshot, elapsed: True,
                message_template="one",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            ),
            CoachingRule(
                name="r2",
                nudge_type="rule-two",
                condition=lambda snapshot, elapsed: True,
                message_template="two",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            ),
        ]
        coach = Coach(rules)
        snapshot = _make_snapshot()

        monkeypatch.setattr(coach_module.time, "time", lambda: 1000.0)
        first = coach.check(snapshot, elapsed_seconds=300)
        assert [n.nudge_type for n in first] == ["rule-one"]

        monkeypatch.setattr(coach_module.time, "time", lambda: 1010.0)
        second = coach.check(snapshot, elapsed_seconds=300)
        assert second == []

    def test_global_nudge_budget_caps_session_to_three(self, monkeypatch):
        rules = [
            CoachingRule(
                name="r1",
                nudge_type="rule-one",
                condition=lambda snapshot, elapsed: True,
                message_template="one",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            )
        ]
        coach = Coach(rules)
        snapshot = _make_snapshot()

        for current_time in (1000.0, 1400.0, 1800.0):
            monkeypatch.setattr(coach_module.time, "time", lambda current_time=current_time: current_time)
            assert len(coach.check(snapshot, elapsed_seconds=300)) == 1

        monkeypatch.setattr(coach_module.time, "time", lambda: 2200.0)
        assert coach.check(snapshot, elapsed_seconds=300) == []


class TestNudgeContent:
    def test_nudge_has_required_fields(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges) > 0
        nudge = nudges[0]
        assert nudge.id  # UUID
        assert nudge.message
        assert nudge.nudge_type
        assert nudge.priority in [NudgePriority.LOW, NudgePriority.MEDIUM, NudgePriority.HIGH]
        assert isinstance(nudge.trigger_metrics, dict)
