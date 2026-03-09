from pathlib import Path

import pytest

from app.observability.trace_models import SessionTrace

from .eval_assert import (
    assert_replay_matches_expectation,
    assert_replay_matches_trace,
    assert_trace_matches_expectation,
    load_expectation,
)
from .eval_case_schema import load_eval_cases
from .replay import replay_trace_signals

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.eval_replay
def test_recorded_replay_cases_remain_consistent_with_expectations_and_recorded_outputs():
    cases = load_eval_cases(FIXTURES_DIR / "replay_cases.json")
    assert cases

    for case in cases:
        trace = SessionTrace.model_validate_json(
            (FIXTURES_DIR / case.fixture).read_text()
        )
        expectation = load_expectation(FIXTURES_DIR / case.expectation)

        replay = replay_trace_signals(trace)

        assert_trace_matches_expectation(trace, expectation)
        assert_replay_matches_expectation(replay, expectation)
        assert_replay_matches_trace(replay, trace, expectation)
