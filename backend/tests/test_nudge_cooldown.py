import time
from unittest.mock import patch

from app.coaching_system.coach import Coach
from app.coaching_system.rules import CoachingRule
from app.config import settings
from app.models import (
    MetricsSnapshot, ParticipantMetrics, SessionMetrics, NudgePriority,
)


def _make_snapshot(**overrides) -> MetricsSnapshot:
    tutor = overrides.pop("tutor", None) or ParticipantMetrics(
        eye_contact_score=0.8, talk_time_percent=0.6,
        energy_score=0.7, is_speaking=False,
    )
    student = overrides.pop("student", None) or ParticipantMetrics(
        eye_contact_score=0.1, talk_time_percent=0.4,
        energy_score=0.5, is_speaking=False,
    )
    session = overrides.pop("session", None) or SessionMetrics(
        interruption_count=0, engagement_trend="stable", engagement_score=70.0,
    )
    return MetricsSnapshot(
        session_id="test", tutor=tutor, student=student, session=session,
        **overrides,
    )


def _always_true_rule(name: str = "test_rule", cooldown: int = 60) -> CoachingRule:
    return CoachingRule(
        name=name,
        nudge_type=name,
        condition=lambda s, e: True,
        message_template="Test nudge",
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=cooldown,
        min_session_elapsed=0,
    )


def test_same_rule_does_not_refire_within_cooldown():
    """Same rule should not fire again within cooldown window."""
    rule = _always_true_rule(cooldown=60)
    coach = Coach(rules=[rule])
    snapshot = _make_snapshot()

    with patch.object(settings, "global_nudge_min_interval_seconds", 0), patch.object(settings, "global_nudge_max_per_session", 10):
        nudges1 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges1) == 1

        nudges2 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges2) == 0


def test_rule_fires_again_after_cooldown():
    """Rule should fire again after cooldown expires."""
    rule = _always_true_rule(cooldown=2)
    coach = Coach(rules=[rule])
    snapshot = _make_snapshot()

    with patch.object(settings, "global_nudge_min_interval_seconds", 0), patch.object(settings, "global_nudge_max_per_session", 10):
        nudges1 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges1) == 1

        time.sleep(2.1)

        nudges2 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges2) == 1


def test_reset_cooldown():
    """Resetting cooldown should allow immediate re-fire."""
    rule = _always_true_rule(cooldown=9999)
    coach = Coach(rules=[rule])
    snapshot = _make_snapshot()

    with patch.object(settings, "global_nudge_min_interval_seconds", 0), patch.object(settings, "global_nudge_max_per_session", 10):
        nudges1 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges1) == 1

        nudges2 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges2) == 0

        coach.reset_cooldown("test_rule")

        nudges3 = coach.check(snapshot, elapsed_seconds=120)
        assert len(nudges3) == 1


def test_reset_all_cooldowns_also_resets_global_budget_and_interval():
    rule = _always_true_rule(cooldown=9999)
    coach = Coach(rules=[rule])
    snapshot = _make_snapshot()

    with patch.object(settings, "global_nudge_min_interval_seconds", 9999), patch.object(settings, "global_nudge_max_per_session", 1):
        assert len(coach.check(snapshot, elapsed_seconds=120)) == 1
        assert coach.check(snapshot, elapsed_seconds=120) == []

        coach.reset_all_cooldowns()
        assert len(coach.check(snapshot, elapsed_seconds=120)) == 1


def test_global_interval_blocks_other_rules_too():
    """A recent nudge should block all other rules until the global interval expires."""
    rule1 = _always_true_rule(name="rule_a", cooldown=0)
    rule2 = _always_true_rule(name="rule_b", cooldown=0)
    coach = Coach(rules=[rule1, rule2])
    snapshot = _make_snapshot()

    with patch.object(settings, "global_nudge_min_interval_seconds", 60), patch.object(settings, "global_nudge_max_per_session", 10):
        first = coach.check(snapshot, elapsed_seconds=120)
        assert len(first) == 1
        assert first[0].nudge_type == "rule_a"

        second = coach.check(snapshot, elapsed_seconds=120)
        assert second == []


def test_condition_false_does_not_trigger_or_set_cooldown():
    """A rule whose condition is False should not fire or start cooldown."""
    rule = CoachingRule(
        name="conditional", nudge_type="cond",
        condition=lambda s, e: False,
        message_template="Never", priority=NudgePriority.LOW,
        cooldown_seconds=1, min_session_elapsed=0,
    )
    coach = Coach(rules=[rule])
    snapshot = _make_snapshot()

    nudges = coach.check(snapshot, elapsed_seconds=120)
    assert len(nudges) == 0
    assert "conditional" not in coach._last_fired


def test_min_elapsed_respected():
    """Rule should not fire before min_session_elapsed."""
    rule = CoachingRule(
        name="delayed", nudge_type="delayed",
        condition=lambda s, e: True,
        message_template="Delayed", priority=NudgePriority.LOW,
        cooldown_seconds=0, min_session_elapsed=300,
    )
    coach = Coach(rules=[rule])
    snapshot = _make_snapshot()

    with patch.object(settings, "global_nudge_warmup_seconds", 0):
        nudges_early = coach.check(snapshot, elapsed_seconds=100)
        assert len(nudges_early) == 0

        nudges_late = coach.check(snapshot, elapsed_seconds=301)
        assert len(nudges_late) == 1
