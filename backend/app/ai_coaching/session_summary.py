"""Post-session AI summary generation.

Produces an ``AISessionSummary`` from the full session transcript by running
it through the LLM with PII scrubbing.  Gated behind the
``enable_ai_session_summary`` configuration flag.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.ai_coaching.llm_client import LLMClient
from app.ai_coaching.pii_scrubber import PIIScrubber
from app.transcription.models import FinalUtterance

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class AISessionSummary:
    """Structured AI-generated post-session summary."""

    topics_covered: List[str] = field(default_factory=list)
    key_moments: List[Dict[str, Any]] = field(default_factory=list)
    student_understanding_map: Dict[str, float] = field(default_factory=dict)
    tutor_strengths: List[str] = field(default_factory=list)
    tutor_growth_areas: List[str] = field(default_factory=list)
    recommended_follow_up: List[str] = field(default_factory=list)
    session_narrative: str = ""


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """\
You are an expert tutoring session analyst. You will be given the full \
transcript of a tutoring session and must produce a structured JSON summary.

## Output Format
Respond with a JSON object matching this schema:
```json
{
  "topics_covered": ["<topic1>", "<topic2>"],
  "key_moments": [
    {
      "time": "<approximate session time, e.g. '2:30'>",
      "description": "<what happened>",
      "significance": "<why it matters>"
    }
  ],
  "student_understanding_map": {
    "<topic>": <float 0-1 representing student's understanding level>
  },
  "tutor_strengths": ["<strength1>", "<strength2>"],
  "tutor_growth_areas": ["<area1>", "<area2>"],
  "recommended_follow_up": ["<recommendation1>", "<recommendation2>"],
  "session_narrative": "<2-3 sentence narrative summary of the session>"
}
```

## Guidelines
- Identify 2-6 main topics covered in the session.
- Key moments should highlight breakthroughs, confusion points, or notable interactions.
- Student understanding map scores: 0.0 = no understanding, 1.0 = full mastery.
- Tutor strengths and growth areas should be specific and actionable.
- Recommended follow-up should suggest what to cover in the next session.
- Keep the narrative concise and professional.
- Respond ONLY with the JSON object, no additional text.\
"""


def _build_transcript_prompt(
    utterances: List[FinalUtterance],
    session_type: str = "general",
    duration_seconds: float = 0.0,
) -> str:
    """Build the user prompt containing the full transcript."""
    parts: List[str] = []

    duration_min = duration_seconds / 60.0
    parts.append(f"Session type: {session_type}")
    parts.append(f"Session duration: {duration_min:.1f} minutes")
    parts.append(f"Total utterances: {len(utterances)}")
    parts.append("")
    parts.append("## Full Transcript")

    for utt in utterances:
        role_label = utt.role.upper() if isinstance(utt.role, str) else utt.role.value.upper()
        timestamp = f"{utt.start_time:.1f}s"
        parts.append(f"[{timestamp}] [{role_label}] {utt.text}")

    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Generation function
# --------------------------------------------------------------------------- #


async def generate_ai_session_summary(
    utterances: List[FinalUtterance],
    llm_client: LLMClient,
    *,
    session_type: str = "general",
    duration_seconds: float = 0.0,
) -> Optional[AISessionSummary]:
    """Generate an AI session summary from the full transcript.

    PII is scrubbed from the transcript before sending to the LLM.
    Returns ``None`` if the LLM call fails or the response cannot be parsed.
    """
    if not utterances:
        return None

    # Build prompt
    user_prompt = _build_transcript_prompt(
        utterances,
        session_type=session_type,
        duration_seconds=duration_seconds,
    )

    # PII scrub
    scrubber = PIIScrubber()
    scrub_result = scrubber.scrub(user_prompt)
    user_prompt = scrub_result.text
    if scrub_result.redaction_count > 0:
        logger.info(
            "Session summary: scrubbed %d PII items (%s)",
            scrub_result.redaction_count,
            scrub_result.redacted_types,
        )

    # LLM call
    try:
        raw_response = await llm_client.generate(
            _SYSTEM_PROMPT,
            user_prompt,
            max_tokens=2048,
        )
    except Exception:
        logger.exception("Session summary: LLM call failed")
        return None

    if raw_response is None:
        logger.warning("Session summary: LLM returned None")
        return None

    # Parse JSON response
    return _parse_summary_response(raw_response)


def _parse_summary_response(raw: str) -> Optional[AISessionSummary]:
    """Parse the LLM JSON response into an AISessionSummary."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Session summary: failed to parse JSON response")
        return None

    if not isinstance(data, dict):
        logger.warning("Session summary: response is not a dict")
        return None

    try:
        return AISessionSummary(
            topics_covered=data.get("topics_covered", []),
            key_moments=data.get("key_moments", []),
            student_understanding_map=data.get("student_understanding_map", {}),
            tutor_strengths=data.get("tutor_strengths", []),
            tutor_growth_areas=data.get("tutor_growth_areas", []),
            recommended_follow_up=data.get("recommended_follow_up", []),
            session_narrative=data.get("session_narrative", ""),
        )
    except Exception:
        logger.warning("Session summary: failed to construct AISessionSummary")
        return None
