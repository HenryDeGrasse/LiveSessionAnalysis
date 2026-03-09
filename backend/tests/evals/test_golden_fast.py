from pathlib import Path

import pytest

from app.observability.trace_models import SessionTrace

from .eval_assert import assert_trace_matches_expectation, load_expectation
from .eval_case_schema import load_eval_cases

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.eval_fast
def test_fast_golden_cases_validate_against_production_models():
    cases = load_eval_cases(FIXTURES_DIR / "golden_sets.json")
    assert cases

    for case in cases:
        trace = SessionTrace.model_validate_json(
            (FIXTURES_DIR / case.fixture).read_text()
        )
        expectation = load_expectation(FIXTURES_DIR / case.expectation)
        assert_trace_matches_expectation(trace, expectation)
