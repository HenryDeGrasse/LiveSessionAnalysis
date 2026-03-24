"""AI coaching suggestion grader — deterministic checks + LLM-as-judge.

Two layers of evaluation:

1. **Deterministic checks** (fast, no LLM needed):
   - JSON parses correctly
   - Has all required fields
   - suggested_prompt is non-empty and speakable length
   - No answer leakage (reuses AIOutputValidator)
   - References the topic when required
   - Doesn't repeat previous suggestions

2. **LLM-as-judge** (requires API key, slower):
   - Naturalness: Does the suggested_prompt sound like a real person?
   - Specificity: Does it reference the actual conversation / topic?
   - Actionability: Can the tutor say this immediately with zero editing?
   - Appropriateness: Does it address the right issue for this scenario?
   - Safety: Does it avoid giving academic answers?

Each dimension is scored 1-5.  The judge LLM receives the scenario
description, the transcript, and the suggestion, but NOT the system
prompt that generated it — preventing bias toward either variant.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ai_coaching.output_validator import AIOutputValidator, CoachingSuggestion

from .scenarios import EvalScenario

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Deterministic grading
# --------------------------------------------------------------------------- #

_ANSWER_LEAK_PATTERNS = [
    r"\bthe\s+answer\s+is\b",
    r"\bthe\s+solution\s+is\b",
    r"\bit\s+equals\b",
    r"\bthe\s+correct\s+answer\b",
    r"=\s*-?\d+(?:\.\d+)?(?:\s|$|[,;.!?])",
]


@dataclass
class DeterministicResult:
    """Results of deterministic (non-LLM) checks on a suggestion."""

    valid_json: bool = False
    has_all_fields: bool = False
    has_suggested_prompt: bool = False
    prompt_speakable_length: bool = False  # 10-300 chars
    no_answer_leak: bool = False
    references_topic: bool = False
    not_duplicate: bool = False
    passes_validator: bool = False

    @property
    def all_pass(self) -> bool:
        return all([
            self.valid_json,
            self.has_all_fields,
            self.has_suggested_prompt,
            self.prompt_speakable_length,
            self.no_answer_leak,
            self.passes_validator,
        ])

    @property
    def pass_count(self) -> int:
        checks = [
            self.valid_json,
            self.has_all_fields,
            self.has_suggested_prompt,
            self.prompt_speakable_length,
            self.no_answer_leak,
            self.references_topic,
            self.not_duplicate,
            self.passes_validator,
        ]
        return sum(checks)

    @property
    def total_checks(self) -> int:
        return 8


def _extract_json_from_llm(raw: str) -> Optional[dict]:
    """Try to parse JSON from an LLM response, stripping code fences."""
    stripped = raw.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        data = json.loads(stripped)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def grade_deterministic(
    raw_response: str,
    scenario: EvalScenario,
    previous_prompts: Optional[List[str]] = None,
) -> DeterministicResult:
    """Run all deterministic checks on a raw LLM response."""
    result = DeterministicResult()
    data = _extract_json_from_llm(raw_response)

    if data is None:
        return result
    result.valid_json = True

    required_fields = {"action", "topic", "suggestion", "suggested_prompt"}
    result.has_all_fields = required_fields.issubset(data.keys())

    prompt = data.get("suggested_prompt", "")
    suggestion_text = data.get("suggestion", "")
    topic = data.get("topic", "")

    result.has_suggested_prompt = bool(prompt and len(prompt.strip()) > 0)
    result.prompt_speakable_length = 10 <= len(prompt) <= 300

    # Answer leak check
    combined = f"{suggestion_text} {prompt}"
    result.no_answer_leak = not any(
        re.search(p, combined, re.IGNORECASE)
        for p in _ANSWER_LEAK_PATTERNS
    )

    # Validator check
    validator = AIOutputValidator()
    cs = CoachingSuggestion(
        suggestion=suggestion_text,
        suggested_prompt=prompt or None,
    )
    result.passes_validator = validator.validate(cs) is not None

    # Topic reference check (uses scenario keywords)
    if scenario.must_reference_topic and scenario.context.topic_keywords:
        topic_lower = topic.lower()
        prompt_lower = prompt.lower()
        combined_lower = f"{topic_lower} {prompt_lower} {suggestion_text.lower()}"
        result.references_topic = any(
            kw.lower() in combined_lower
            for kw in scenario.context.topic_keywords
        )
    else:
        result.references_topic = True

    # Duplicate check
    if previous_prompts:
        result.not_duplicate = prompt.strip().lower() not in [
            p.strip().lower() for p in previous_prompts
        ]
    else:
        result.not_duplicate = True

    return result


# --------------------------------------------------------------------------- #
# LLM-as-judge
# --------------------------------------------------------------------------- #

JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator of AI-generated coaching suggestions for live tutoring sessions.

You will receive:
1. A scenario description (what's happening in the session)
2. The recent transcript
3. An AI-generated coaching suggestion

Score the suggestion on these 5 dimensions (1-5 each):

**naturalness** — Does the suggested_prompt sound like a real tutor talking? (1=robotic/formal, 5=completely natural)
**specificity** — Does it reference the actual topic and what was said? (1=generic, 5=highly specific to this moment)
**actionability** — Can the tutor read it out loud immediately with zero editing? (1=needs heavy editing, 5=ready to speak)
**appropriateness** — Does it address the right issue for this situation? (1=wrong issue, 5=nails the issue)
**safety** — Does it avoid giving academic answers or being condescending? (1=leaks answer or bad tone, 5=perfect pedagogy)

Respond with ONLY a JSON object:
```json
{
  "naturalness": <1-5>,
  "specificity": <1-5>,
  "actionability": <1-5>,
  "appropriateness": <1-5>,
  "safety": <1-5>,
  "reasoning": "<1-2 sentences explaining your scores>"
}
```\
"""


def build_judge_prompt(scenario: EvalScenario, suggestion_data: dict) -> str:
    """Build the judge prompt for a scenario + suggestion pair."""
    parts = []

    parts.append("## Scenario")
    parts.append(f"**{scenario.name}**: {scenario.description}")
    if scenario.ideal_prompt_intent:
        parts.append(f"**What a good suggestion would do**: {scenario.ideal_prompt_intent}")

    parts.append("\n## Recent Transcript")
    for utt in scenario.context.recent_utterances:
        parts.append(f"[{utt.role.upper()}] {utt.text}")

    parts.append("\n## AI Suggestion to Evaluate")
    parts.append(f"Action: {suggestion_data.get('action', 'N/A')}")
    parts.append(f"Topic: {suggestion_data.get('topic', 'N/A')}")
    parts.append(f"Observation: {suggestion_data.get('observation', 'N/A')}")
    parts.append(f"Suggestion: {suggestion_data.get('suggestion', 'N/A')}")
    parts.append(f"Suggested prompt: \"{suggestion_data.get('suggested_prompt', 'N/A')}\"")

    return "\n".join(parts)


@dataclass
class JudgeScores:
    """LLM-as-judge quality scores (1-5 each)."""

    naturalness: int = 0
    specificity: int = 0
    actionability: int = 0
    appropriateness: int = 0
    safety: int = 0
    reasoning: str = ""
    judge_error: str = ""

    @property
    def total(self) -> int:
        return (
            self.naturalness
            + self.specificity
            + self.actionability
            + self.appropriateness
            + self.safety
        )

    @property
    def max_total(self) -> int:
        return 25

    @property
    def average(self) -> float:
        return self.total / 5.0 if self.total > 0 else 0.0


def parse_judge_response(raw: str) -> JudgeScores:
    """Parse the judge LLM's JSON response into scores."""
    data = _extract_json_from_llm(raw)
    if data is None:
        return JudgeScores(judge_error=f"Failed to parse judge response: {raw[:200]}")

    def _clamp(val: Any) -> int:
        try:
            return max(1, min(5, int(val)))
        except (ValueError, TypeError):
            return 0

    return JudgeScores(
        naturalness=_clamp(data.get("naturalness")),
        specificity=_clamp(data.get("specificity")),
        actionability=_clamp(data.get("actionability")),
        appropriateness=_clamp(data.get("appropriateness")),
        safety=_clamp(data.get("safety")),
        reasoning=str(data.get("reasoning", "")),
    )


# --------------------------------------------------------------------------- #
# Combined result
# --------------------------------------------------------------------------- #


@dataclass
class SuggestionEvalResult:
    """Complete evaluation of a single suggestion for a single scenario."""

    scenario_id: str
    variant: str  # "v1_old" or "v2_new"
    raw_response: str = ""
    parsed_data: Optional[Dict[str, Any]] = None
    deterministic: DeterministicResult = field(default_factory=DeterministicResult)
    judge: JudgeScores = field(default_factory=JudgeScores)
    prompt_used: str = ""  # the user prompt sent to the LLM (for debugging)
    latency_ms: float = 0.0

    @property
    def composite_score(self) -> float:
        """Composite: deterministic pass rate (30%) + judge average (70%)."""
        det_pct = self.deterministic.pass_count / max(1, self.deterministic.total_checks)
        judge_pct = self.judge.average / 5.0 if self.judge.total > 0 else 0.0
        return 0.30 * det_pct + 0.70 * judge_pct
