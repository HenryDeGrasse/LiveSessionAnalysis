from pathlib import Path

import pytest

from app.observability.trace_models import SessionTrace

from .eval_assert import assert_replay_matches_expectation, load_expectation
from .eval_case_schema import load_eval_cases
from .replay import replay_trace_signals

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.eval_fast
def test_accuracy_pack_replays_signal_traces():
    cases = load_eval_cases(FIXTURES_DIR / "accuracy_cases.json")
    assert cases

    for case in cases:
        trace = SessionTrace.model_validate_json(
            (FIXTURES_DIR / case.fixture).read_text()
        )
        expectation = load_expectation(FIXTURES_DIR / case.expectation)
        replay = replay_trace_signals(trace)
        assert_replay_matches_expectation(replay, expectation)
