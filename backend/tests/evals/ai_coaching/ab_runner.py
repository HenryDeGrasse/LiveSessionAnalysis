"""A/B test runner for AI coaching suggestions.

Runs every scenario through two prompt strategies:
- **v1_old**: Raw signal dump (the original approach)
- **v2_new**: Pre-interpreted situation briefs (the new approach)

Both use the same LLM, same scenarios, same grading rubric.
The judge LLM is blind to which variant produced the suggestion.
"""

from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

from app.ai_coaching.context import AICoachingContext
from app.ai_coaching.prompts import build_system_prompt, build_user_prompt

from .grader import (
    JUDGE_SYSTEM_PROMPT,
    SuggestionEvalResult,
    build_judge_prompt,
    grade_deterministic,
    parse_judge_response,
    _extract_json_from_llm,
)
from .scenarios import EvalScenario

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# V1 (old) prompt builder — reconstructed from the original approach
# --------------------------------------------------------------------------- #

_V1_SYSTEM_PROMPT = """\
You are an expert pedagogical coaching assistant embedded in a live tutoring session.

## Role
You observe the tutoring session and provide real-time coaching suggestions to the \
TUTOR (not the student). Your suggestions help the tutor improve their teaching \
approach in the moment.

## Constraints
- NEVER provide direct answers to academic questions.
- NEVER suggest the tutor tell the student an answer directly.
- Focus ONLY on pedagogy: questioning techniques, scaffolding, pacing, engagement.
- Keep suggestions actionable and concise (1-2 sentences).
- Prioritize suggestions that address observed student confusion or uncertainty.
- Do not repeat suggestions that have already been given recently.

## Session Type Guidance
{session_type_guidance}

## Output Format
Respond with a JSON object matching this schema:
```json
{{
  "action": "<short action verb: probe | scaffold | redirect | encourage | pace | check_understanding>",
  "topic": "<topic area being discussed>",
  "observation": "<what you observed that prompted this suggestion>",
  "suggestion": "<coaching suggestion for the tutor, 1-2 sentences>",
  "suggested_prompt": "<a complete sentence the tutor can read word-for-word to the student — natural, conversational, ready to speak aloud as-is>",
  "priority": "<high | medium | low>",
  "confidence": <float 0-1>
}}
```

## Critical: suggested_prompt
The `suggested_prompt` field is **required** and is the most important part. \
The tutor will read it out loud verbatim to the student mid-session. It must:
- Be a complete, natural-sounding sentence or question addressed directly to the student.
- Sound like something a real tutor would actually say in conversation (not robotic or formal).
- Never reveal an answer — only guide, probe, or encourage.
- Be ready to speak with zero editing.

Respond ONLY with the JSON object, no additional text.\
"""

_V1_SESSION_GUIDANCE = {
    "general": "This is a general tutoring session. Focus on engagement, pacing, and effective questioning techniques.",
    "math": "This is a math tutoring session. Encourage scaffolding, break problems into steps, ask for reasoning.",
    "reading": "This is a reading/literacy session. Ask comprehension questions, make connections, use think-alouds.",
    "science": "This is a science tutoring session. Encourage hypothesis-driven questioning and predicting outcomes.",
    "writing": "This is a writing session. Guide the writing process rather than dictating text.",
    "test_prep": "This is a test prep session. Focus on strategy, time management, and identifying knowledge gaps.",
    "lecture": "This is a lecture-style session. Check comprehension periodically.",
    "practice": "This is a practice session. The student should do most of the work.",
    "socratic": "This is a Socratic session. Use questions, not statements.",
}


def _build_v1_system_prompt(session_type: str) -> str:
    guidance = _V1_SESSION_GUIDANCE.get(session_type, _V1_SESSION_GUIDANCE["general"])
    return _V1_SYSTEM_PROMPT.format(session_type_guidance=guidance)


def _build_v1_user_prompt(context: AICoachingContext) -> str:
    """Original v1 user prompt: raw signal dump."""
    parts = []
    elapsed_min = context.elapsed_seconds / 60.0
    parts.append(f"Session elapsed: {elapsed_min:.1f} minutes")

    if context.recent_utterances:
        parts.append("\n## Recent Transcript")
        for utt in context.recent_utterances:
            parts.append(f"[{utt.role.upper()}] {utt.text}")
    else:
        parts.append("\n## Recent Transcript\n(no transcript available yet)")

    if context.uncertainty_score > 0:
        parts.append(f"\n## Uncertainty Signal")
        parts.append(f"Score: {context.uncertainty_score:.2f}")
        if context.uncertainty_topic:
            parts.append(f"Topic: {context.uncertainty_topic}")

    parts.append(f"\n## Session Metrics")
    parts.append(f"Tutor talk ratio: {context.tutor_talk_ratio:.0%}")
    parts.append(f"Student talk ratio: {context.student_talk_ratio:.0%}")
    if context.student_engagement_score > 0:
        parts.append(f"Student engagement: {context.student_engagement_score:.2f}")

    if context.recent_suggestions:
        parts.append(f"\n## Previously Given Suggestions (avoid repeating)")
        for sug in context.recent_suggestions:
            parts.append(f"- [{sug.action}] {sug.suggestion}")

    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


async def run_single_scenario(
    scenario: EvalScenario,
    llm_client,
    *,
    variant: str,
    max_tokens: int = 350,
) -> SuggestionEvalResult:
    """Run a single scenario through one prompt variant and grade it."""
    context = scenario.context

    if variant == "v1_old":
        system_prompt = _build_v1_system_prompt(context.session_type)
        user_prompt = _build_v1_user_prompt(context)
    else:
        system_prompt = build_system_prompt(context.session_type)
        user_prompt = build_user_prompt(context)

    result = SuggestionEvalResult(
        scenario_id=scenario.id,
        variant=variant,
        prompt_used=user_prompt,
    )

    t0 = time.monotonic()
    try:
        raw = await llm_client.generate(
            system_prompt, user_prompt, max_tokens=max_tokens,
        )
    except Exception as exc:
        result.raw_response = f"ERROR: {exc}"
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    result.latency_ms = (time.monotonic() - t0) * 1000
    result.raw_response = raw or ""

    if raw is None:
        return result

    result.parsed_data = _extract_json_from_llm(raw)
    result.deterministic = grade_deterministic(raw, scenario)

    return result


async def judge_suggestion(
    scenario: EvalScenario,
    result: SuggestionEvalResult,
    judge_llm,
) -> None:
    """Run LLM-as-judge scoring on an already-generated suggestion.

    Mutates ``result.judge`` in place.
    """
    if result.parsed_data is None:
        result.judge.judge_error = "No parsed suggestion to judge"
        return

    judge_prompt = build_judge_prompt(scenario, result.parsed_data)
    try:
        raw_judge = await judge_llm.generate(
            JUDGE_SYSTEM_PROMPT, judge_prompt, max_tokens=300,
        )
    except Exception as exc:
        result.judge.judge_error = f"Judge call failed: {exc}"
        return

    if raw_judge is None:
        result.judge.judge_error = "Judge returned None"
        return

    result.judge = parse_judge_response(raw_judge)


async def run_ab_test(
    scenarios: List[EvalScenario],
    llm_client,
    judge_llm,
    *,
    skip_judge: bool = False,
) -> List[tuple[SuggestionEvalResult, SuggestionEvalResult]]:
    """Run full A/B eval across all scenarios.

    Returns a list of (v1_result, v2_result) pairs.
    """
    pairs = []

    for scenario in scenarios:
        logger.info("Evaluating scenario: %s", scenario.id)

        v1 = await run_single_scenario(scenario, llm_client, variant="v1_old")
        v2 = await run_single_scenario(scenario, llm_client, variant="v2_new")

        if not skip_judge:
            await judge_suggestion(scenario, v1, judge_llm)
            await judge_suggestion(scenario, v2, judge_llm)

        pairs.append((v1, v2))

    return pairs


# --------------------------------------------------------------------------- #
# Report formatting
# --------------------------------------------------------------------------- #


def format_report(
    pairs: List[tuple[SuggestionEvalResult, SuggestionEvalResult]],
) -> str:
    """Format A/B test results as a human-readable report."""
    lines = []
    lines.append("=" * 80)
    lines.append("AI COACHING SUGGESTION A/B TEST REPORT")
    lines.append("=" * 80)
    lines.append("")

    v1_composites = []
    v2_composites = []
    v1_det_passes = 0
    v2_det_passes = 0
    v1_judge_totals = []
    v2_judge_totals = []

    for v1, v2 in pairs:
        lines.append(f"--- {v1.scenario_id} ---")

        # Deterministic
        lines.append(f"  Deterministic:  v1={v1.deterministic.pass_count}/{v1.deterministic.total_checks}  "
                     f"v2={v2.deterministic.pass_count}/{v2.deterministic.total_checks}")
        if v1.deterministic.all_pass:
            v1_det_passes += 1
        if v2.deterministic.all_pass:
            v2_det_passes += 1

        # Judge
        if v1.judge.total > 0 or v2.judge.total > 0:
            lines.append(f"  Judge scores:   v1={v1.judge.total}/{v1.judge.max_total} ({v1.judge.average:.1f})  "
                         f"v2={v2.judge.total}/{v2.judge.max_total} ({v2.judge.average:.1f})")
            dims = ["naturalness", "specificity", "actionability", "appropriateness", "safety"]
            for dim in dims:
                s1 = getattr(v1.judge, dim, 0)
                s2 = getattr(v2.judge, dim, 0)
                winner = "←" if s1 > s2 else ("→" if s2 > s1 else "=")
                lines.append(f"    {dim:18s}  v1={s1}  {winner}  v2={s2}")
            if v1.judge.total > 0:
                v1_judge_totals.append(v1.judge.total)
            if v2.judge.total > 0:
                v2_judge_totals.append(v2.judge.total)

        # Composite
        lines.append(f"  Composite:      v1={v1.composite_score:.2f}  v2={v2.composite_score:.2f}  "
                     f"{'v1 WINS' if v1.composite_score > v2.composite_score else ('v2 WINS' if v2.composite_score > v1.composite_score else 'TIE')}")
        v1_composites.append(v1.composite_score)
        v2_composites.append(v2.composite_score)

        # Latency
        lines.append(f"  Latency (ms):   v1={v1.latency_ms:.0f}  v2={v2.latency_ms:.0f}")

        # Suggested prompts
        v1_prompt = v1.parsed_data.get("suggested_prompt", "N/A") if v1.parsed_data else "PARSE FAILED"
        v2_prompt = v2.parsed_data.get("suggested_prompt", "N/A") if v2.parsed_data else "PARSE FAILED"
        lines.append(f'  v1 prompt: "{v1_prompt}"')
        lines.append(f'  v2 prompt: "{v2_prompt}"')

        # Judge reasoning
        if v1.judge.reasoning:
            lines.append(f"  v1 judge: {v1.judge.reasoning}")
        if v2.judge.reasoning:
            lines.append(f"  v2 judge: {v2.judge.reasoning}")

        lines.append("")

    # Summary
    n = len(pairs)
    v1_wins = sum(1 for v1, v2 in pairs if v1.composite_score > v2.composite_score)
    v2_wins = sum(1 for v1, v2 in pairs if v2.composite_score > v1.composite_score)
    ties = n - v1_wins - v2_wins

    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"  Scenarios tested:    {n}")
    lines.append(f"  v1 (old) wins:       {v1_wins}/{n}")
    lines.append(f"  v2 (new) wins:       {v2_wins}/{n}")
    lines.append(f"  Ties:                {ties}/{n}")
    lines.append("")
    lines.append(f"  Deterministic pass:  v1={v1_det_passes}/{n}  v2={v2_det_passes}/{n}")

    if v1_composites:
        lines.append(f"  Avg composite:       v1={sum(v1_composites)/len(v1_composites):.3f}  "
                     f"v2={sum(v2_composites)/len(v2_composites):.3f}")

    if v1_judge_totals and v2_judge_totals:
        lines.append(f"  Avg judge score:     v1={sum(v1_judge_totals)/len(v1_judge_totals):.1f}/25  "
                     f"v2={sum(v2_judge_totals)/len(v2_judge_totals):.1f}/25")

        # Per-dimension averages
        dims = ["naturalness", "specificity", "actionability", "appropriateness", "safety"]
        lines.append("")
        lines.append("  Per-dimension averages:")
        for dim in dims:
            v1_avg = sum(getattr(r.judge, dim, 0) for r, _ in pairs) / max(1, n)
            v2_avg = sum(getattr(r.judge, dim, 0) for _, r in pairs) / max(1, n)
            delta = v2_avg - v1_avg
            indicator = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
            lines.append(f"    {dim:18s}  v1={v1_avg:.1f}  v2={v2_avg:.1f}  ({indicator})")

    lines.append("")
    return "\n".join(lines)
