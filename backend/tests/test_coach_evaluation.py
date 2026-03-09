from datetime import datetime

import pytest

from app.coaching_system.coach import Coach
from app.coaching_system.rules import CoachingRule
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
