from pathlib import Path

import pytest

from app.analytics.recommendations import generate_recommendations
from app.models import SessionSummary

from .eval_assert import assert_recommendations, load_expectation
from .eval_case_schema import load_eval_cases

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.eval_fast
def test_recommendation_eval_cases_validate_against_summary_fixtures():
    cases = load_eval_cases(FIXTURES_DIR / "recommendation_cases.json")
    assert cases

    for case in cases:
        summary = SessionSummary.model_validate_json(
            (FIXTURES_DIR / case.fixture).read_text(encoding="utf-8")
        )
        expectation = load_expectation(FIXTURES_DIR / case.expectation)
        recommendations = generate_recommendations(summary)

        assert isinstance(recommendations, list)
        assert all(isinstance(recommendation, str) for recommendation in recommendations)
        assert_recommendations(recommendations, expectation)
