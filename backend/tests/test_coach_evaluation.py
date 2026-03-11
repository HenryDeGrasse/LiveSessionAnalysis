from datetime import datetime
from unittest.mock import patch

import pytest

from app.coaching_system.coach import Coach
from app.coaching_system.rules import CoachingRule
from app.config import settings
from app.models import MetricsSnapshot, NudgePriority, ParticipantMetrics, SessionMetrics


def _snapshot(*, degraded: bool = False) -> MetricsSnapshot:
    return MetricsSnapshot(
        session_id="session-1",
        timestamp=datetime(2025, 1, 1, 12, 0, 0),
        tutor=ParticipantMetrics(
            talk_time_percent=0.9,
            eye_contact_score=0.7,
            energy_score=0.6,
        ),
        student=ParticipantMetrics(
            talk_time_percent=0.1,
            eye_contact_score=0.4,
            energy_score=0.5,
        ),
        session=SessionMetrics(
            recent_tutor_talk_percent=0.9,
            engagement_score=62.0,
        ),
        degraded=degraded,
    )


def test_evaluate_records_global_suppression_reason():
    coach = Coach()

    evaluation = coach.evaluate(
        _snapshot(degraded=True),
        elapsed_seconds=300,
        now=1000.0,
    )

    assert evaluation.nudges == []
    assert evaluation.emitted_nudge_type is None
    assert "session_degraded" in evaluation.suppressed_reasons


def test_evaluate_returns_candidate_and_emitted_nudge_metadata():
    rule = CoachingRule(
        name="traceable_rule",
        nudge_type="traceable_rule",
        condition=lambda snapshot, elapsed, profile: True,
        message_template="Trace me",
        priority=NudgePriority.LOW,
        cooldown_seconds=60,
        min_session_elapsed=60,
    )
    coach = Coach(rules=[rule])

    evaluation = coach.evaluate(_snapshot(), elapsed_seconds=300, now=1000.0)

    assert [n.nudge_type for n in evaluation.nudges] == ["traceable_rule"]
    assert evaluation.emitted_nudge_type == "traceable_rule"
    assert evaluation.candidate_nudges == ["traceable_rule"]
    assert evaluation.trigger_features["tutor_talk"] == pytest.approx(0.9)
    assert "session_type" in evaluation.trigger_features


def test_evaluate_records_global_interval_suppression_after_first_nudge():
    rule = CoachingRule(
        name="traceable_rule",
        nudge_type="traceable_rule",
        condition=lambda snapshot, elapsed, profile: True,
        message_template="Trace me",
        priority=NudgePriority.LOW,
        cooldown_seconds=60,
        min_session_elapsed=60,
    )
    coach = Coach(rules=[rule])

    first = coach.evaluate(_snapshot(), elapsed_seconds=300, now=1000.0)
    second = coach.evaluate(_snapshot(), elapsed_seconds=300, now=1100.0)

    assert [n.nudge_type for n in first.nudges] == ["traceable_rule"]
    assert second.nudges == []
    assert second.emitted_nudge_type is None
    assert "global_min_interval" in second.suppressed_reasons


def test_off_intensity_never_emits_nudges():
    rule = CoachingRule(
        name="always_on",
        nudge_type="always_on",
        condition=lambda snapshot, elapsed, profile: True,
        message_template="Never emit",
        priority=NudgePriority.LOW,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )
    coach = Coach(rules=[rule], intensity="off")

    evaluation = coach.evaluate(_snapshot(), elapsed_seconds=999, now=1000.0)

    assert coach.intensity == "off"
    assert evaluation.nudges == []
    assert evaluation.emitted_nudge_type is None
    assert "global_nudge_budget_exhausted" in evaluation.suppressed_reasons


def test_subtle_intensity_scales_global_interval_and_rule_cooldown():
    rule = CoachingRule(
        name="traceable_rule",
        nudge_type="traceable_rule",
        condition=lambda snapshot, elapsed, profile: True,
        message_template="Trace me",
        priority=NudgePriority.LOW,
        cooldown_seconds=60,
        min_session_elapsed=0,
    )
    coach = Coach(rules=[rule], intensity="subtle")

    with patch.object(settings, "global_nudge_warmup_seconds", 10), patch.object(
        settings, "global_nudge_min_interval_seconds", 100
    ), patch.object(settings, "global_nudge_max_per_session", 5):
        assert coach.evaluate(_snapshot(), elapsed_seconds=19, now=1000.0).nudges == []
        assert "global_warmup" in coach.evaluate(
            _snapshot(), elapsed_seconds=19, now=1000.0
        ).suppressed_reasons

        first = coach.evaluate(_snapshot(), elapsed_seconds=20, now=1000.0)
        second = coach.evaluate(_snapshot(), elapsed_seconds=20, now=1119.0)
        third = coach.evaluate(_snapshot(), elapsed_seconds=20, now=1201.0)

    assert [n.nudge_type for n in first.nudges] == ["traceable_rule"]
    assert "global_min_interval" in second.suppressed_reasons
    assert [n.nudge_type for n in third.nudges] == ["traceable_rule"]


def test_aggressive_intensity_uses_shorter_interval_and_higher_budget():
    rule = CoachingRule(
        name="traceable_rule",
        nudge_type="traceable_rule",
        condition=lambda snapshot, elapsed, profile: True,
        message_template="Trace me",
        priority=NudgePriority.LOW,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )
    coach = Coach(rules=[rule], intensity="aggressive")

    with patch.object(settings, "global_nudge_warmup_seconds", 10), patch.object(
        settings, "global_nudge_min_interval_seconds", 100
    ), patch.object(settings, "global_nudge_max_per_session", 1):
        warmup_eval = coach.evaluate(_snapshot(), elapsed_seconds=4, now=1000.0)
        first = coach.evaluate(_snapshot(), elapsed_seconds=5, now=1000.0)
        too_soon = coach.evaluate(_snapshot(), elapsed_seconds=5, now=1049.0)
        second = coach.evaluate(_snapshot(), elapsed_seconds=5, now=1051.0)
        exhausted = coach.evaluate(_snapshot(), elapsed_seconds=5, now=1200.0)

    assert "global_warmup" in warmup_eval.suppressed_reasons
    assert [n.nudge_type for n in first.nudges] == ["traceable_rule"]
    assert "global_min_interval" in too_soon.suppressed_reasons
    assert [n.nudge_type for n in second.nudges] == ["traceable_rule"]
    assert exhausted.nudges == []
    assert "global_nudge_budget_exhausted" in exhausted.suppressed_reasons


def test_invalid_intensity_falls_back_to_normal():
    coach = Coach(intensity="extreme")

    assert coach.intensity == "normal"


def test_evaluation_includes_candidates_evaluated():
    """All evaluated rule names should appear in candidates_evaluated."""
    rule_a = CoachingRule(
        name="rule_alpha",
        nudge_type="rule_alpha",
        condition=lambda snapshot, elapsed, profile: False,
        message_template="Alpha",
        priority=NudgePriority.LOW,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )
    rule_b = CoachingRule(
        name="rule_beta",
        nudge_type="rule_beta",
        condition=lambda snapshot, elapsed, profile: False,
        message_template="Beta",
        priority=NudgePriority.LOW,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )
    coach = Coach(rules=[rule_a, rule_b])

    evaluation = coach.evaluate(_snapshot(), elapsed_seconds=300, now=1000.0)

    assert "rule_alpha" in evaluation.candidates_evaluated
    assert "rule_beta" in evaluation.candidates_evaluated
    assert evaluation.candidates_evaluated == ["rule_alpha", "rule_beta"]


def test_evaluation_includes_fired_rule_name():
    """When a rule fires, fired_rule should contain the rule's name."""
    rule = CoachingRule(
        name="always_fires",
        nudge_type="always_fires",
        condition=lambda snapshot, elapsed, profile: True,
        message_template="This fires",
        priority=NudgePriority.LOW,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )
    coach = Coach(rules=[rule])

    evaluation = coach.evaluate(_snapshot(), elapsed_seconds=300, now=1000.0)

    assert evaluation.fired_rule == "always_fires"
    assert evaluation.emitted_nudge_type == "always_fires"


def test_evaluation_fired_rule_none_when_no_match():
    """When no rule fires, fired_rule should be None."""
    rule = CoachingRule(
        name="never_fires",
        nudge_type="never_fires",
        condition=lambda snapshot, elapsed, profile: False,
        message_template="Never",
        priority=NudgePriority.LOW,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )
    coach = Coach(rules=[rule])

    evaluation = coach.evaluate(_snapshot(), elapsed_seconds=300, now=1000.0)

    assert evaluation.fired_rule is None
    assert evaluation.nudges == []
    assert "never_fires" in evaluation.candidates_evaluated
