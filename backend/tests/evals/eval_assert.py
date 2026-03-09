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


def assert_trace_matches_expectation(trace: SessionTrace, expectation: EvalExpectation) -> None:
    _assert_nudges([nudge.nudge_type for nudge in trace.nudges], expectation)

    for field_path, matcher in expectation.summary_fields.items():
        actual = _resolve_path(trace.summary, field_path)
        if matcher.equals is not None:
            assert actual == matcher.equals
        if matcher.approx is not None:
            tolerance = matcher.tolerance or 0.0
            assert abs(float(actual) - matcher.approx) <= tolerance

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
