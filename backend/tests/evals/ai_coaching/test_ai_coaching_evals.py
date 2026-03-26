"""AI coaching suggestion e2e evaluation tests.

Three test tiers:

1. ``test_prompt_structure_*`` (eval_fast) — Deterministic checks on prompt
   construction. No LLM calls. Run on every CI push.

2. ``test_deterministic_grading_*`` (eval_fast) — Verify the grading rubric
   itself works correctly with known-good/known-bad mock responses.

3. ``test_ab_*`` (eval_ab) — Live A/B comparison: v1 (old prompt) vs v2 (new
   prompt) with real LLM calls + LLM-as-judge scoring. Run manually or in
   nightly CI.

Usage:
    # Fast deterministic checks (no API key needed)
    make eval-fast

    # Full A/B test (needs OPENROUTER_API_KEY)
    cd backend && uv run --python 3.11 --with-requirements requirements.txt \\
        pytest tests/evals/ai_coaching/ -m eval_ab -v --tb=short 2>&1 | tee ab_report.txt
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from app.ai_coaching.context import AICoachingContext, AISuggestion
from app.ai_coaching.prompts import build_system_prompt, build_user_prompt
from app.transcription.models import FinalUtterance

from .grader import (
    DeterministicResult,
    JudgeScores,
    SuggestionEvalResult,
    grade_deterministic,
    parse_judge_response,
)
from .scenarios import SCENARIOS, EvalScenario

# Re-export for collection
from .ab_runner import (
    _build_v1_system_prompt,
    _build_v1_user_prompt,
    format_report,
    judge_suggestion,
    run_ab_test,
    run_single_scenario,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_good_response(**overrides) -> str:
    data = {
        "action": "probe",
        "topic": "fractions",
        "observation": "Student seems unsure about denominators",
        "suggestion": "Ask the student to explain what a denominator represents.",
        "suggested_prompt": "Can you tell me in your own words what the bottom number in a fraction means?",
        "priority": "medium",
        "confidence": 0.85,
    }
    data.update(overrides)
    return json.dumps(data)


def _make_bad_response_answer_leak() -> str:
    return json.dumps({
        "action": "scaffold",
        "topic": "fractions",
        "observation": "Student is stuck",
        "suggestion": "The answer is three fourths.",
        "suggested_prompt": "The answer is three fourths, so just write that down.",
        "priority": "high",
        "confidence": 0.9,
    })


def _make_bad_response_no_prompt() -> str:
    return json.dumps({
        "action": "probe",
        "topic": "fractions",
        "observation": "Student hesitated",
        "suggestion": "Ask the student a question",
        "suggested_prompt": "",
        "priority": "medium",
        "confidence": 0.5,
    })


# --------------------------------------------------------------------------- #
# 1. Prompt structure tests (eval_fast — no LLM needed)
# --------------------------------------------------------------------------- #


class TestPromptStructure:
    """Verify prompt construction for every scenario."""

    @pytest.mark.eval_fast
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
    def test_v2_prompt_has_situation_section(self, scenario: EvalScenario):
        prompt = build_user_prompt(scenario.context)
        assert "## Situation" in prompt
        assert "## Recent Conversation" in prompt

    @pytest.mark.eval_fast
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
    def test_v2_prompt_includes_transcript(self, scenario: EvalScenario):
        prompt = build_user_prompt(scenario.context)
        if scenario.context.recent_utterances:
            assert "[TUTOR]" in prompt or "[STUDENT]" in prompt

    @pytest.mark.eval_fast
    @pytest.mark.parametrize(
        "scenario",
        [s for s in SCENARIOS if s.triggered_rule],
        ids=[s.id for s in SCENARIOS if s.triggered_rule],
    )
    def test_v2_rule_scenarios_have_focused_directive(self, scenario: EvalScenario):
        """Rule-triggered prompts should contain a clear directive sentence."""
        prompt = build_user_prompt(scenario.context)
        # Every rule brief should have a "Write ..." directive
        assert "Write " in prompt or "write " in prompt

    @pytest.mark.eval_fast
    @pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
    def test_v2_prompt_is_concise(self, scenario: EvalScenario):
        """User prompt should stay under 2000 chars (focused, not a data dump)."""
        prompt = build_user_prompt(scenario.context)
        assert len(prompt) < 2000, f"Prompt too long: {len(prompt)} chars"

    @pytest.mark.eval_fast
    def test_v2_system_prompt_is_lean(self):
        """System prompt should stay under 5500 chars (includes diverse action examples)."""
        for stype in ["general", "math", "science", "reading", "writing"]:
            sp = build_system_prompt(stype)
            assert len(sp) < 5500, f"System prompt for {stype} too long: {len(sp)} chars"

    @pytest.mark.eval_fast
    @pytest.mark.parametrize(
        "scenario",
        [s for s in SCENARIOS if s.context.recent_suggestions],
        ids=[s.id for s in SCENARIOS if s.context.recent_suggestions],
    )
    def test_v2_prompt_includes_dedup(self, scenario: EvalScenario):
        prompt = build_user_prompt(scenario.context)
        assert "Already Suggested" in prompt

    @pytest.mark.eval_fast
    def test_v1_and_v2_produce_different_prompts(self):
        """V1 and V2 should produce meaningfully different prompts."""
        for scenario in SCENARIOS[:3]:
            v1 = _build_v1_user_prompt(scenario.context)
            v2 = build_user_prompt(scenario.context)
            # They should share the transcript but differ structurally
            assert "## Situation" not in v1
            assert "## Situation" in v2


# --------------------------------------------------------------------------- #
# 2. Deterministic grading tests (eval_fast)
# --------------------------------------------------------------------------- #


class TestDeterministicGrading:
    """Verify the grading rubric works correctly with known inputs."""

    @pytest.mark.eval_fast
    def test_good_response_passes_all(self):
        scenario = SCENARIOS[0]  # check_for_understanding_math
        raw = _make_good_response(topic="fractions")
        result = grade_deterministic(raw, scenario)
        assert result.valid_json
        assert result.has_all_fields
        assert result.has_suggested_prompt
        assert result.prompt_speakable_length
        assert result.no_answer_leak
        assert result.passes_validator
        assert result.references_topic

    @pytest.mark.eval_fast
    def test_answer_leak_detected(self):
        scenario = SCENARIOS[0]
        raw = _make_bad_response_answer_leak()
        result = grade_deterministic(raw, scenario)
        assert result.valid_json
        assert not result.no_answer_leak
        assert not result.passes_validator

    @pytest.mark.eval_fast
    def test_empty_prompt_fails(self):
        scenario = SCENARIOS[0]
        raw = _make_bad_response_no_prompt()
        result = grade_deterministic(raw, scenario)
        assert result.valid_json
        assert not result.has_suggested_prompt
        assert not result.prompt_speakable_length

    @pytest.mark.eval_fast
    def test_invalid_json_fails(self):
        scenario = SCENARIOS[0]
        result = grade_deterministic("not json at all", scenario)
        assert not result.valid_json
        assert result.pass_count == 0

    @pytest.mark.eval_fast
    def test_code_fenced_json_passes(self):
        scenario = SCENARIOS[0]
        raw = "```json\n" + _make_good_response(topic="fractions") + "\n```"
        result = grade_deterministic(raw, scenario)
        assert result.valid_json
        assert result.has_all_fields

    @pytest.mark.eval_fast
    def test_topic_reference_check(self):
        scenario = SCENARIOS[0]  # keywords: fractions, denominator, simplify, etc.
        # Good: mentions topic
        raw = _make_good_response(topic="fractions", suggested_prompt="Tell me about fractions.")
        result = grade_deterministic(raw, scenario)
        assert result.references_topic

        # Bad: no topic mention anywhere in any field
        raw = json.dumps({
            "action": "probe",
            "topic": "weather",
            "observation": "Something happened",
            "suggestion": "Ask the student about their day.",
            "suggested_prompt": "How are you feeling today?",
            "priority": "medium",
            "confidence": 0.5,
        })
        result = grade_deterministic(raw, scenario)
        assert not result.references_topic

    @pytest.mark.eval_fast
    def test_prompt_length_bounds(self):
        scenario = SCENARIOS[0]
        # Too short
        raw = _make_good_response(suggested_prompt="Hi?", topic="fractions")
        result = grade_deterministic(raw, scenario)
        assert not result.prompt_speakable_length

        # Too long (>300 chars)
        raw = _make_good_response(suggested_prompt="x " * 200, topic="fractions")
        result = grade_deterministic(raw, scenario)
        assert not result.prompt_speakable_length

    @pytest.mark.eval_fast
    def test_duplicate_detection(self):
        scenario = SCENARIOS[0]
        raw = _make_good_response(
            suggested_prompt="Can you explain that to me?",
            topic="fractions",
        )
        result = grade_deterministic(
            raw, scenario,
            previous_prompts=["Can you explain that to me?"],
        )
        assert not result.not_duplicate


# --------------------------------------------------------------------------- #
# 3. Judge response parsing tests (eval_fast)
# --------------------------------------------------------------------------- #


class TestJudgeParsing:
    """Verify judge response parsing."""

    @pytest.mark.eval_fast
    def test_valid_judge_response(self):
        raw = json.dumps({
            "naturalness": 4,
            "specificity": 5,
            "actionability": 4,
            "appropriateness": 5,
            "safety": 5,
            "reasoning": "Excellent suggestion that references the specific topic.",
        })
        scores = parse_judge_response(raw)
        assert scores.naturalness == 4
        assert scores.specificity == 5
        assert scores.total == 23
        assert scores.average == 4.6

    @pytest.mark.eval_fast
    def test_judge_clamps_values(self):
        raw = json.dumps({
            "naturalness": 0,  # below min
            "specificity": 10,  # above max
            "actionability": 3,
            "appropriateness": 4,
            "safety": 5,
            "reasoning": "Test",
        })
        scores = parse_judge_response(raw)
        assert scores.naturalness == 1  # clamped to 1
        assert scores.specificity == 5  # clamped to 5

    @pytest.mark.eval_fast
    def test_judge_parse_failure(self):
        scores = parse_judge_response("not json")
        assert scores.judge_error
        assert scores.total == 0

    @pytest.mark.eval_fast
    def test_composite_score_math(self):
        result = SuggestionEvalResult(scenario_id="test", variant="v2_new")
        # 8/8 deterministic = 1.0, judge avg 4.0/5.0 = 0.8
        result.deterministic = DeterministicResult(
            valid_json=True, has_all_fields=True, has_suggested_prompt=True,
            prompt_speakable_length=True, no_answer_leak=True,
            references_topic=True, not_duplicate=True, passes_validator=True,
        )
        result.judge = JudgeScores(
            naturalness=4, specificity=4, actionability=4,
            appropriateness=4, safety=4,
        )
        # 0.30 * 1.0 + 0.70 * 0.8 = 0.30 + 0.56 = 0.86
        assert abs(result.composite_score - 0.86) < 0.01


# --------------------------------------------------------------------------- #
# 4. Live A/B test (eval_ab — needs API key)
# --------------------------------------------------------------------------- #


def _get_llm_client():
    """Create a real OpenRouter LLM client from env."""
    api_key = os.environ.get("LSA_OPENROUTER_API_KEY", "")
    if not api_key:
        pytest.skip("LSA_OPENROUTER_API_KEY not set")

    from app.ai_coaching.llm_client import OpenRouterLLMClient

    model = os.environ.get("LSA_AI_COACHING_MODEL", "anthropic/claude-3.5-haiku")
    return OpenRouterLLMClient(api_key=api_key, model=model)


def _get_judge_client():
    """Create a separate LLM client for judging (uses a strong model)."""
    api_key = os.environ.get("LSA_OPENROUTER_API_KEY", "")
    if not api_key:
        pytest.skip("LSA_OPENROUTER_API_KEY not set")

    from app.ai_coaching.llm_client import OpenRouterLLMClient

    judge_model = os.environ.get("LSA_EVAL_JUDGE_MODEL", "anthropic/claude-3.5-sonnet")
    return OpenRouterLLMClient(api_key=api_key, model=judge_model)


@pytest.mark.eval_ab
class TestABComparison:
    """Full A/B test comparing v1 vs v2 prompt strategies with real LLM."""

    @pytest.mark.asyncio
    async def test_ab_all_scenarios(self, tmp_path):
        """Run all scenarios through both variants and produce a report."""
        llm = _get_llm_client()
        judge = _get_judge_client()

        pairs = await run_ab_test(SCENARIOS, llm, judge)

        report = format_report(pairs)
        print("\n" + report)

        # Save report
        report_path = tmp_path / "ab_report.txt"
        report_path.write_text(report)

        # Save raw results as JSON
        raw_results = []
        for v1, v2 in pairs:
            raw_results.append({
                "scenario_id": v1.scenario_id,
                "v1": {
                    "raw_response": v1.raw_response,
                    "deterministic_pass": v1.deterministic.pass_count,
                    "judge_total": v1.judge.total,
                    "judge_reasoning": v1.judge.reasoning,
                    "composite": v1.composite_score,
                    "latency_ms": v1.latency_ms,
                    "suggested_prompt": (v1.parsed_data or {}).get("suggested_prompt", ""),
                },
                "v2": {
                    "raw_response": v2.raw_response,
                    "deterministic_pass": v2.deterministic.pass_count,
                    "judge_total": v2.judge.total,
                    "judge_reasoning": v2.judge.reasoning,
                    "composite": v2.composite_score,
                    "latency_ms": v2.latency_ms,
                    "suggested_prompt": (v2.parsed_data or {}).get("suggested_prompt", ""),
                },
            })
        (tmp_path / "ab_results.json").write_text(
            json.dumps(raw_results, indent=2)
        )

        # --- Assertions ---
        # V2 should win or tie on composite across the board
        v2_wins = sum(1 for v1, v2 in pairs if v2.composite_score > v1.composite_score)
        v1_wins = sum(1 for v1, v2 in pairs if v1.composite_score > v2.composite_score)
        n = len(pairs)
        # V2 should win at least 40% of scenarios (conservative — real threshold
        # should be higher but this prevents regressions)
        assert v2_wins >= n * 0.4 or v2_wins >= v1_wins, (
            f"v2 underperforming: v1 won {v1_wins}/{n}, v2 won {v2_wins}/{n}"
        )

    @pytest.mark.asyncio
    async def test_ab_deterministic_only(self):
        """Quick run: deterministic checks only, no judge (cheaper)."""
        llm = _get_llm_client()

        pairs = await run_ab_test(SCENARIOS, llm, llm, skip_judge=True)

        v1_pass = sum(1 for v1, _ in pairs if v1.deterministic.all_pass)
        v2_pass = sum(1 for _, v2 in pairs if v2.deterministic.all_pass)

        print(f"\nDeterministic pass rate: v1={v1_pass}/{len(pairs)}  v2={v2_pass}/{len(pairs)}")

        # Both should pass basic structural checks on most scenarios
        assert v2_pass >= len(pairs) * 0.7, (
            f"v2 failing too many deterministic checks: {v2_pass}/{len(pairs)}"
        )


@pytest.mark.eval_ab
class TestSingleScenarioDeep:
    """Deep-dive tests for individual scenarios (useful for debugging)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scenario",
        [s for s in SCENARIOS if s.triggered_rule],
        ids=[s.id for s in SCENARIOS if s.triggered_rule],
    )
    async def test_rule_scenario_produces_valid_suggestion(self, scenario: EvalScenario):
        """Each rule-triggered scenario should produce a structurally valid suggestion."""
        llm = _get_llm_client()
        result = await run_single_scenario(scenario, llm, variant="v2_new")

        assert result.deterministic.valid_json, (
            f"Failed to produce valid JSON for {scenario.id}: {result.raw_response[:200]}"
        )
        assert result.deterministic.has_suggested_prompt, (
            f"Missing suggested_prompt for {scenario.id}"
        )
        assert result.deterministic.no_answer_leak, (
            f"Answer leak in {scenario.id}: {result.raw_response[:200]}"
        )
        assert result.deterministic.passes_validator, (
            f"Validator rejected suggestion for {scenario.id}"
        )
