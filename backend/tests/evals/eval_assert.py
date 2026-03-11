from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.observability.trace_models import SessionTrace

from .eval_case_schema import EvalExpectation
from .replay import ReplayResult


def load_expectation(path: Path) -> EvalExpectation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return EvalExpectation.model_validate(payload)


def _resolve_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            current = getattr(current, part)
    return current


def _assert_nudges(nudge_types: list[str], expectation: EvalExpectation) -> None:
    for required in expectation.required_nudges:
        assert required in nudge_types, f"Missing required nudge: {required}"

    for forbidden in expectation.forbidden_nudges:
        assert forbidden not in nudge_types, f"Unexpected nudge present: {forbidden}"

    if expectation.max_nudges is not None:
        assert len(nudge_types) <= expectation.max_nudges


def _assert_value_assertions(subject: Any, expectation: EvalExpectation) -> None:
    for assertion in expectation.value_assertions:
        actual = _resolve_path(subject, assertion.path)
        assert actual == assertion.equals


def _recommendation_matches_keywords(
    recommendations: list[str],
    keywords: list[str],
) -> bool:
    normalized_keywords = [keyword.lower() for keyword in keywords]
    normalized_recommendations = [recommendation.lower() for recommendation in recommendations]
    return any(
        any(keyword in recommendation for keyword in normalized_keywords)
        for recommendation in normalized_recommendations
    )


def assert_recommendations(
    recommendations: list[str],
    expectation: EvalExpectation,
) -> None:
    if expectation.min_recommendations is not None:
        assert len(recommendations) >= expectation.min_recommendations

    if expectation.max_recommendations is not None:
        assert len(recommendations) <= expectation.max_recommendations

    for keywords in expectation.required_recommendation_keywords:
        assert _recommendation_matches_keywords(
            recommendations,
            keywords,
        ), f"Missing recommendation matching keywords: {keywords}"

    for keywords in expectation.forbidden_recommendation_keywords:
        assert not _recommendation_matches_keywords(
            recommendations,
            keywords,
        ), f"Unexpected recommendation matching keywords: {keywords}"


def assert_trace_matches_expectation(trace: SessionTrace, expectation: EvalExpectation) -> None:
    _assert_nudges([nudge.nudge_type for nudge in trace.nudges], expectation)

    for field_path, matcher in expectation.summary_fields.items():
        actual = _resolve_path(trace.summary, field_path)
        if matcher.equals is not None:
            assert actual == matcher.equals
        if matcher.approx is not None:
            tolerance = matcher.tolerance or 0.0
            assert abs(float(actual) - matcher.approx) <= tolerance

    assert_recommendations(trace.summary.recommendations, expectation)
    _assert_value_assertions(trace, expectation)

    event_types = [event.event_type for event in trace.events]
    for expected_event_type in expectation.contains_event_types:
        assert expected_event_type in event_types

    for bound in expectation.metric_bounds:
        actual = _resolve_path(trace, bound.path)
        if bound.min is not None:
            assert float(actual) >= bound.min
        if bound.max is not None:
            assert float(actual) <= bound.max


def assert_replay_matches_expectation(replay: ReplayResult, expectation: EvalExpectation) -> None:
    _assert_nudges([nudge.nudge_type for nudge in replay.coach_nudges], expectation)
    _assert_value_assertions(replay, expectation)

    for bound in expectation.metric_bounds:
        actual = _resolve_path(replay, bound.path)
        if bound.min is not None:
            assert float(actual) >= bound.min
        if bound.max is not None:
            assert float(actual) <= bound.max


def assert_replay_matches_trace(
    replay: ReplayResult,
    trace: SessionTrace,
    expectation: EvalExpectation,
) -> None:
    for comparison in expectation.replay_matches_trace:
        replay_value = _resolve_path(replay, comparison.replay_path)
        trace_value = _resolve_path(trace, comparison.trace_path)
        if comparison.tolerance is None:
            assert replay_value == trace_value
        else:
            assert abs(float(replay_value) - float(trace_value)) <= comparison.tolerance
