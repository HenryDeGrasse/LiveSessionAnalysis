"""Tests for the v2 coaching rule set.

Rules:
- check_for_understanding: composite tutor overtalk + student silence
- student_off_task: persistence-based OFF_TASK_AWAY / FACE_MISSING
- let_them_finish: hard interruption/cutoff pattern + tutor dominance
- tech_check: mutual silence + media anomaly

Removed from live nudges (now post-session only):
- energy_drop (too ambiguous for live, especially in lectures)
- standalone low_eye_contact (replaced by persistence-based off-task)
- standalone student_silence (merged into check_for_understanding)
- standalone tutor_overtalk (merged into check_for_understanding)
"""

import time
import pytest
import app.coaching_system.coach as coach_module
from app.coaching_system.coach import Coach
from app.coaching_system.rules import DEFAULT_RULES, CoachingRule
from app.coaching_system.profiles import get_profile, LECTURE, PRACTICE, GENERAL
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


# =========================================================================
# check_for_understanding (composite: tutor overtalk + student silence)
# =========================================================================

class TestCheckForUnderstanding:
    def test_fires_when_tutor_dominates_and_student_silent(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.9,
                energy_score=0.7,
                is_speaking=True,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.1,
                energy_score=0.5,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=200,  # > 180s threshold
                recent_tutor_talk_percent=0.85,  # > 0.80 threshold
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "check_for_understanding" in types

    def test_fires_on_overtalk_even_without_long_silence(self):
        """Tutor overtalk alone is enough to trigger, even without prolonged silence."""
        coach = Coach()
        snapshot = _make_snapshot(
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=10,  # Short silence
                recent_tutor_talk_percent=0.9,  # Above 0.80 threshold
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "check_for_understanding" in types

    def test_does_not_fire_without_overtalk(self):
        coach = Coach()
        snapshot = _make_snapshot(
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=200,
                recent_tutor_talk_percent=0.5,  # Balanced
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "check_for_understanding" not in types

    def test_lecture_profile_has_higher_thresholds(self):
        """In a lecture, tutor talking 85% should NOT trigger (threshold is 92%)."""
        coach = Coach(session_type="lecture")
        snapshot = _make_snapshot(
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=200,
                recent_tutor_talk_percent=0.88,  # Above general threshold but below lecture
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "check_for_understanding" not in types

    def test_practice_profile_has_lower_thresholds(self):
        """In practice, tutor talking 60% should trigger (threshold is 55%)."""
        coach = Coach(session_type="practice")
        snapshot = _make_snapshot(
            session=SessionMetrics(
                interruption_count=0,
                silence_duration_current=70,  # > 60s practice threshold
                recent_tutor_talk_percent=0.60,  # > 0.55 practice threshold
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "check_for_understanding" in types


# =========================================================================
# student_off_task (persistence-based)
# =========================================================================

class TestStudentOffTask:
    def test_fires_when_off_task_sustained(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.8,
                face_presence_score=0.9,
                visual_attention_score=0.2,
                time_in_attention_state_seconds=80,  # > 75s threshold
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_off_task" in types

    def test_does_not_fire_when_briefly_off_task(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.8,
                time_in_attention_state_seconds=10,  # Too brief
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_off_task" not in types

    def test_does_not_fire_when_low_visual_confidence(self):
        """Selective visual suppression: don't fire visual rules when unsure."""
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.3,  # Low confidence
                time_in_attention_state_seconds=100,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_off_task" not in types

    def test_does_not_fire_for_engaged_states(self):
        coach = Coach()
        for state in ("CAMERA_FACING", "SCREEN_ENGAGED", "DOWN_ENGAGED"):
            snapshot = _make_snapshot(
                student=ParticipantMetrics(
                    eye_contact_score=0.1,
                    talk_time_percent=0.4,
                    energy_score=0.5,
                    is_speaking=False,
                    attention_state=state,
                    attention_state_confidence=0.9,
                    time_in_attention_state_seconds=100,
                ),
            )
            nudges = coach.check(snapshot, elapsed_seconds=200)
            types = [n.nudge_type for n in nudges]
            assert "student_off_task" not in types
            coach.reset_all_cooldowns()

    def test_fires_on_face_missing_sustained(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="FACE_MISSING",
                attention_state_confidence=0.9,
                time_in_attention_state_seconds=80,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_off_task" in types

    def test_lecture_allows_longer_off_task(self):
        """Lecture profile has 90s threshold vs general 75s."""
        coach = Coach(session_type="lecture")
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.1,
                talk_time_percent=0.1,
                energy_score=0.5,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.8,
                time_in_attention_state_seconds=80,  # > 75 (general) but < 90 (lecture)
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_off_task" not in types

    def test_does_not_fire_when_gaze_unavailable(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.8,
                time_in_attention_state_seconds=100,
            ),
            gaze_unavailable=True,
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "student_off_task" not in types


# =========================================================================
# let_them_finish (interruption pattern)
# =========================================================================

class TestLetThemFinish:
    def test_fires_on_hard_interruptions(self):
        coach = Coach()
        snapshot = _make_snapshot(
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
        evaluation = coach.evaluate(snapshot, elapsed_seconds=200, now=1000.0)
        # Both let_them_finish and interruption_burst are candidates;
        # severity-based selection picks the higher one.
        assert "let_them_finish" in evaluation.candidate_nudges or "interruption_burst" in evaluation.candidate_nudges

    def test_does_not_fire_when_balanced_talk(self):
        coach = Coach()
        snapshot = _make_snapshot(
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=3,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                recent_tutor_talk_percent=0.4,  # Student-dominated
                engagement_trend="stable",
                engagement_score=60.0,
            )
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "let_them_finish" not in types

    def test_echo_reduces_severity_not_suppresses(self):
        """Echo suspected now applies a 75% severity penalty instead of
        hard-suppressing.  A strong pattern should still fire even with echo.
        The change prevents false negatives when the tutor genuinely
        interrupts but the audio system suspects echo."""
        coach = Coach()

        # Strong pattern WITH echo should still be allowed to fire
        coach.reset_all_cooldowns()
        snapshot_strong = _make_snapshot(
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=4,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                tutor_cutoffs=2,
                echo_suspected=True,
                recent_tutor_talk_percent=0.8,
                engagement_trend="stable",
                engagement_score=60.0,
            )
        )
        evaluation = coach.evaluate(snapshot_strong, elapsed_seconds=200, now=2000.0)
        assert "let_them_finish" in evaluation.candidate_nudges, (
            "Strong interruption pattern should be a candidate even with echo_suspected=True "
            "because echo now applies a severity penalty rather than hard-suppressing."
        )


# =========================================================================
# tech_check (mutual silence + media anomaly)
# =========================================================================

class TestTechCheck:
    def test_fires_on_silence_plus_face_missing(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="FACE_MISSING",
                attention_state_confidence=0.8,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=35,  # > 30s threshold
                engagement_trend="stable",
                engagement_score=50.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "tech_check" in types

    def test_does_not_fire_on_silence_alone(self):
        """Silence without media anomaly should NOT trigger tech check."""
        coach = Coach()
        snapshot = _make_snapshot(
            session=SessionMetrics(
                mutual_silence_duration_current=60,  # Long silence
                engagement_trend="stable",
                engagement_score=50.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "tech_check" not in types

    def test_does_not_fire_on_short_silence(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.4,
                energy_score=0.5,
                is_speaking=False,
                attention_state="FACE_MISSING",
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=10,  # Too short
                engagement_trend="stable",
                engagement_score=50.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "tech_check" not in types

    def test_fires_on_degraded_mode(self):
        coach = Coach()
        snapshot = _make_snapshot(
            degraded=True,
            session=SessionMetrics(
                mutual_silence_duration_current=40,
                engagement_trend="stable",
                engagement_score=50.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        types = [n.nudge_type for n in nudges]
        assert "tech_check" in types


# =========================================================================
# Energy drop is NOT a live nudge anymore
# =========================================================================

class TestEnergyDropNotLiveNudge:
    def test_energy_drop_does_not_fire_as_live_nudge(self):
        """Energy drop was removed from live nudges. Verify it's gone."""
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.4,
                energy_score=0.05,  # Extremely low
                energy_drop_from_baseline=0.5,
                is_speaking=False,
            ),
            tutor=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.6,
                energy_score=0.05,
                energy_drop_from_baseline=0.5,
                is_speaking=False,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "energy_drop" not in types

    def test_quiet_student_in_lecture_gets_no_energy_nudge(self):
        """The specific bug scenario: a quietly attentive student in a
        lecture should never get an energy drop live nudge."""
        coach = Coach(session_type="lecture")
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.7,
                talk_time_percent=0.1,
                energy_score=0.10,  # Low because quiet
                is_speaking=False,
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
                visual_attention_score=1.0,
            ),
            session=SessionMetrics(
                recent_tutor_talk_percent=0.9,  # Tutor-heavy, expected
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        assert len(nudges) == 0


# =========================================================================
# Session-type profile selection
# =========================================================================

class TestProfileSelection:
    def test_default_profile_is_general(self):
        coach = Coach()
        assert coach.session_type == "general"
        assert coach.profile == GENERAL

    def test_lecture_profile_selected(self):
        coach = Coach(session_type="lecture")
        assert coach.profile == LECTURE

    def test_practice_profile_selected(self):
        coach = Coach(session_type="practice")
        assert coach.profile == PRACTICE

    def test_unknown_type_falls_back_to_general(self):
        coach = Coach(session_type="unknown_type")
        assert coach.profile == GENERAL


# =========================================================================
# Global guardrails (preserved from before)
# =========================================================================

class TestNoNudgesEarlyInSession:
    def test_no_nudges_before_min_elapsed(self):
        """No rules should fire before min_session_elapsed."""
        coach = Coach()
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
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.9,
                time_in_attention_state_seconds=200,
            ),
            session=SessionMetrics(
                interruption_count=10,
                recent_hard_interruptions=5,
                recent_tutor_talk_percent=0.95,
                silence_duration_current=300,
                mutual_silence_duration_current=60,
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
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.02,
                energy_score=0.1,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.9,
                time_in_attention_state_seconds=100,
            ),
            session=SessionMetrics(
                interruption_count=5,
                recent_interruptions=3,
                hard_interruption_count=4,
                recent_hard_interruptions=3,
                silence_duration_current=200,
                recent_tutor_talk_percent=0.95,
                mutual_silence_duration_current=60,
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
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.9,
                time_in_attention_state_seconds=100,
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
        # Rules with allow_when_degraded=True can still fire (tech_check,
        # re_engage_silence, interruption_burst, etc.).
        # Visual-gated rules like student_off_task must NOT fire.
        nudge_types = {n.nudge_type for n in nudges}
        assert "student_off_task" not in nudge_types
        assert "session_momentum_loss" not in nudge_types

    def test_status_stays_active_when_degraded_but_globally_eligible(self, monkeypatch):
        coach = Coach()
        monkeypatch.setattr(coach_module.time, "time", lambda: 1000.0)

        status = coach.get_status(
            elapsed_seconds=300,
            rules_evaluated=0,
            degraded=True,
        )

        assert status["active"] is True
        assert status["warmup_remaining_s"] == 0.0
        assert status["next_eligible_s"] == 0.0
        from app.config import settings
        assert status["budget_remaining"] == settings.global_nudge_max_per_session

    def test_global_nudge_interval_applies_across_rules(self, monkeypatch):
        rules = [
            CoachingRule(
                name="r1",
                nudge_type="rule-one",
                condition=lambda s, e, p: True,
                message_template="one",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            ),
            CoachingRule(
                name="r2",
                nudge_type="rule-two",
                condition=lambda s, e, p: True,
                message_template="two",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            ),
        ]
        coach = Coach(rules=rules)
        snapshot = _make_snapshot()

        monkeypatch.setattr(coach_module.time, "time", lambda: 1000.0)
        first = coach.check(snapshot, elapsed_seconds=300)
        assert [n.nudge_type for n in first] == ["rule-one"]

        monkeypatch.setattr(coach_module.time, "time", lambda: 1010.0)
        second = coach.check(snapshot, elapsed_seconds=300)
        assert second == []

    def test_global_nudge_budget_caps_session(self, monkeypatch):
        from app.config import settings

        rules = [
            CoachingRule(
                name="r1",
                nudge_type="rule-one",
                condition=lambda s, e, p: True,
                message_template="one",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            )
        ]
        coach = Coach(rules=rules)
        snapshot = _make_snapshot()
        budget = settings.global_nudge_max_per_session
        gap = settings.global_nudge_min_interval_seconds + 1

        times = [1000.0 + i * gap for i in range(budget)]
        for current_time in times:
            monkeypatch.setattr(coach_module.time, "time", lambda ct=current_time: ct)
            assert len(coach.check(snapshot, elapsed_seconds=300)) == 1

        monkeypatch.setattr(coach_module.time, "time", lambda: times[-1] + gap)
        assert coach.check(snapshot, elapsed_seconds=300) == []

    def test_status_reports_global_cooldown_after_nudge(self, monkeypatch):
        rules = [
            CoachingRule(
                name="r1",
                nudge_type="rule-one",
                condition=lambda s, e, p: True,
                message_template="one",
                priority=NudgePriority.LOW,
                cooldown_seconds=0,
                min_session_elapsed=0,
            )
        ]
        coach = Coach(rules=rules)
        snapshot = _make_snapshot()

        monkeypatch.setattr(coach_module.time, "time", lambda: 1000.0)
        assert len(coach.check(snapshot, elapsed_seconds=300)) == 1

        from app.config import settings
        check_at = 1000.0 + settings.global_nudge_min_interval_seconds * 0.5
        monkeypatch.setattr(coach_module.time, "time", lambda: check_at)
        status = coach.get_status(elapsed_seconds=300, rules_evaluated=1)

        assert status["active"] is False
        expected_remaining = 1000.0 + settings.global_nudge_min_interval_seconds - check_at
        assert abs(status["next_eligible_s"] - expected_remaining) < 0.5
        assert status["budget_remaining"] == settings.global_nudge_max_per_session - 1
        assert status["rules_evaluated"] == 1


# =========================================================================
# re_engage_silence — both present, mutual silence too long
# =========================================================================

class TestReEngageSilence:
    def test_fires_when_both_present_and_mutually_silent(self):
        """Reported live session scenario: mutual_silence=68s, both CAMERA_FACING."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.7,
                talk_time_percent=0.27,
                energy_score=0.5,
                is_speaking=False,
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.73,
                energy_score=0.6,
                is_speaking=False,
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=68,  # > 60s general threshold
                recent_tutor_talk_percent=0.27,
                echo_suspected=True,  # Echo present shouldn't block re_engage_silence
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "re_engage_silence" in types, (
            "re_engage_silence should fire for the reported scenario: "
            "both CAMERA_FACING, mutual_silence=68s, general threshold=60s"
        )

    def test_does_not_fire_below_threshold(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=30,  # < 60s threshold
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "re_engage_silence" not in types

    def test_does_not_fire_when_face_missing(self):
        """When a face is missing, tech_check should fire, not re_engage_silence."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="FACE_MISSING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=90,  # Well above threshold
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "re_engage_silence" not in types

    def test_lecture_profile_has_higher_threshold(self):
        """In a lecture, 75s silence should not trigger (lecture threshold=90s)."""
        coach = Coach(session_type="lecture")
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=75,  # < 90s lecture threshold
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "re_engage_silence" not in types

    def test_practice_profile_has_lower_threshold(self):
        """In practice, 50s silence should trigger (practice threshold=45s)."""
        coach = Coach(session_type="practice")
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=50,  # > 45s practice threshold
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "re_engage_silence" in types

    def test_not_suppressed_when_degraded(self):
        """allow_when_degraded=True: re_engage_silence is audio/presence-based
        and must not be suppressed due to degraded-session gating.

        When degraded=True AND mutual_silence is long, tech_check may outcompete
        re_engage_silence (degraded counts as an anomaly for tech_check), but
        re_engage_silence should be a *candidate* — not suppressed.
        At minimum, a nudge should fire."""
        coach = Coach()
        snapshot = _make_snapshot(
            degraded=True,
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=90,
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        evaluation = coach.evaluate(snapshot, elapsed_seconds=300)
        # re_engage_silence should be a candidate, not suppressed
        assert "re_engage_silence" in evaluation.candidate_nudges, (
            "re_engage_silence should be a candidate when degraded=True "
            "and allow_when_degraded=True"
        )
        # A nudge must fire — either re_engage_silence or tech_check
        assert len(evaluation.nudges) > 0
        # session_degraded:re_engage_silence should NOT be in suppressed reasons
        assert "session_degraded:re_engage_silence" not in evaluation.suppressed_reasons


# =========================================================================
# encourage_student_response — student silent, tutor not dominating
# =========================================================================

class TestEncourageStudentResponse:
    def test_fires_when_student_long_silent_and_tutor_not_dominant(self):
        """Student quiet for 120s while tutor talk < 60%."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                time_since_student_spoke=120,  # > 90s general threshold
                recent_tutor_talk_percent=0.45,  # < 60% — not dominant
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "encourage_student_response" in types

    def test_does_not_fire_when_tutor_dominant(self):
        """When tutor talk >= 60%, check_for_understanding should fire instead."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                time_since_student_spoke=120,
                recent_tutor_talk_percent=0.75,  # >= 60% — dominant
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "encourage_student_response" not in types

    def test_does_not_fire_when_student_silence_below_threshold(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                time_since_student_spoke=30,  # < 90s threshold
                recent_tutor_talk_percent=0.40,
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "encourage_student_response" not in types

    def test_does_not_fire_when_student_face_missing(self):
        """Student visually absent → tech_check should handle it."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="FACE_MISSING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                time_since_student_spoke=120,
                recent_tutor_talk_percent=0.40,
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "encourage_student_response" not in types

    def test_lecture_profile_has_higher_threshold(self):
        """In a lecture, student silence is expected; threshold is 300s."""
        coach = Coach(session_type="lecture")
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                time_since_student_spoke=150,  # < 300s lecture threshold
                recent_tutor_talk_percent=0.40,
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "encourage_student_response" not in types

    def test_not_suppressed_when_degraded(self):
        coach = Coach()
        snapshot = _make_snapshot(
            degraded=True,
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                time_since_student_spoke=120,
                recent_tutor_talk_percent=0.45,
                engagement_trend="stable",
                engagement_score=60.0,
            ),
        )

        evaluation = coach.evaluate(snapshot, elapsed_seconds=300)

        assert "encourage_student_response" in evaluation.candidate_nudges
        assert "session_degraded:encourage_student_response" not in evaluation.suppressed_reasons
        assert len(evaluation.nudges) > 0


# =========================================================================
# session_momentum_loss — gradual disengagement
# =========================================================================

class TestSessionMomentumLoss:
    def test_fires_on_low_engagement_declining_trend(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=35.0,  # < 50 threshold
                engagement_trend="declining",
                mutual_silence_duration_current=30,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" in types

    def test_does_not_fire_when_stable_trend(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=35.0,  # Low, but...
                engagement_trend="stable",  # ...not declining
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" not in types

    def test_does_not_fire_when_interaction_is_still_active(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=30.0,
                engagement_trend="declining",
                mutual_silence_duration_current=5,
                student_response_latency_last_seconds=4,
                tutor_response_latency_last_seconds=3,
                tutor_turn_count=10,
                student_turn_count=8,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" not in types

    def test_does_not_fire_when_engagement_above_threshold(self):
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=65.0,  # >= 50 — above threshold
                engagement_trend="declining",
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" not in types

    def test_does_not_fire_early_in_session(self):
        """Needs at least 120s to judge momentum."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=20.0,
                engagement_trend="declining",
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=90)  # < 120s
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" not in types

    def test_does_not_fire_when_face_missing(self):
        """If a participant is missing, tech_check handles it."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="FACE_MISSING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=20.0,
                engagement_trend="declining",
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" not in types

    def test_lecture_has_lower_engagement_threshold(self):
        """In a lecture, low engagement is more expected — threshold is 40."""
        coach = Coach(session_type="lecture")
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                engagement_score=45.0,  # < 50 (general) but >= 40 (lecture)
                engagement_trend="declining",
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=300)
        types = [n.nudge_type for n in nudges]
        assert "session_momentum_loss" not in types


# =========================================================================
# Reported live session scenario — all gates should now be passable
# =========================================================================

class TestReportedLiveSessionScenario:
    """Regression test for the real session where NO nudge ever fired.

    Conditions reported:
    - both participants CAMERA_FACING
    - recent_hard_interruptions=0, tutor_cutoffs=0
    - echo_suspected=True
    - engagement_trend=normal, engagement_score=? (not low)
    - mutual_silence ~68s
    - student silent ~68s, tutor silent ~396s
    - recent_tutor_talk_percent ~0.268

    Expected: re_engage_silence fires (mutual_silence 68s > 60s general threshold)
    and/or encourage_student_response fires (student silent > 90s general threshold).
    """

    def test_re_engage_fires_for_reported_session(self):
        """re_engage_silence must fire for the exact reported metrics."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                eye_contact_score=0.7,
                talk_time_percent=0.268,
                energy_score=0.5,
                is_speaking=False,
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.8,
                talk_time_percent=0.732,
                energy_score=0.6,
                is_speaking=False,
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=68,
                time_since_student_spoke=68,
                recent_tutor_talk_percent=0.268,
                recent_hard_interruptions=0,
                tutor_cutoffs=0,
                echo_suspected=True,
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=400)
        types = [n.nudge_type for n in nudges]
        assert len(nudges) > 0, "At least one nudge should fire for the reported scenario"
        assert "re_engage_silence" in types or "encourage_student_response" in types

    def test_encourage_fires_when_student_silent_longer(self):
        """When student silence > 90s and tutor not dominant."""
        coach = Coach()
        snapshot = _make_snapshot(
            tutor=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            student=ParticipantMetrics(
                attention_state="CAMERA_FACING",
                attention_state_confidence=0.9,
            ),
            session=SessionMetrics(
                mutual_silence_duration_current=30,  # Below re_engage threshold
                time_since_student_spoke=100,  # Above encourage threshold
                recent_tutor_talk_percent=0.268,
                echo_suspected=True,
                engagement_trend="stable",
                engagement_score=65.0,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=400)
        types = [n.nudge_type for n in nudges]
        assert "encourage_student_response" in types


class TestNudgeContent:
    def test_nudge_has_required_fields(self):
        coach = Coach()
        snapshot = _make_snapshot(
            student=ParticipantMetrics(
                eye_contact_score=0.0,
                talk_time_percent=0.1,
                energy_score=0.5,
                is_speaking=False,
                attention_state="OFF_TASK_AWAY",
                attention_state_confidence=0.9,
                time_in_attention_state_seconds=100,
            ),
        )
        nudges = coach.check(snapshot, elapsed_seconds=200)
        assert len(nudges) > 0
        nudge = nudges[0]
        assert nudge.id  # UUID
        assert nudge.message
        assert nudge.nudge_type
        assert nudge.priority in [NudgePriority.LOW, NudgePriority.MEDIUM, NudgePriority.HIGH]
        assert isinstance(nudge.trigger_metrics, dict)
        # New: trigger features include session context
        assert "session_type" in nudge.trigger_metrics
        assert "student_attention_state" in nudge.trigger_metrics
        assert "student_time_in_state" in nudge.trigger_metrics
