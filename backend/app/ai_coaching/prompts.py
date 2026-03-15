"""Prompt templates for the AI coaching copilot.

Contains the system prompt with pedagogy-only constraints and structured
JSON output schema, session type guidance, and the user prompt builder.
"""

from __future__ import annotations

from typing import Dict, List

from app.ai_coaching.context import AICoachingContext

# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
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
- Be ready to speak with zero editing. The tutor should be able to glance at it and say it immediately.

Good: "What if we tried drawing out what three-fourths looks like — could you sketch that for me?"
Bad: "Ask the student to visualize fractions" (this is a coaching note, not speakable)

Respond ONLY with the JSON object, no additional text.\
"""

# --------------------------------------------------------------------------- #
# Session type guidance
# --------------------------------------------------------------------------- #

SESSION_TYPE_GUIDANCE: Dict[str, str] = {
    "general": (
        "This is a general tutoring session. Focus on engagement, pacing, "
        "and effective questioning techniques."
    ),
    "math": (
        "This is a math tutoring session. Encourage the tutor to use scaffolding, "
        "break problems into steps, and ask the student to explain their reasoning. "
        "Watch for procedural vs. conceptual understanding gaps."
    ),
    "reading": (
        "This is a reading/literacy session. Encourage the tutor to ask "
        "comprehension questions, make connections to prior knowledge, and use "
        "think-aloud strategies."
    ),
    "science": (
        "This is a science tutoring session. Encourage hypothesis-driven questioning, "
        "connecting observations to theory, and having the student predict outcomes."
    ),
    "writing": (
        "This is a writing session. Focus on guiding the student through the writing "
        "process — brainstorming, organizing ideas, revising — rather than dictating text."
    ),
    "test_prep": (
        "This is a test preparation session. Focus on strategy, time management, "
        "and identifying knowledge gaps. Encourage the tutor to use practice problems "
        "and explain reasoning for wrong answers."
    ),
}

# --------------------------------------------------------------------------- #
# User prompt builder
# --------------------------------------------------------------------------- #


def build_user_prompt(context: AICoachingContext) -> str:
    """Build the user prompt from the current session context.

    Formats recent transcript lines, uncertainty information, and session
    metrics into a prompt the LLM can act on.
    """
    parts: List[str] = []

    # Session metadata
    elapsed_min = context.elapsed_seconds / 60.0
    parts.append(f"Session elapsed: {elapsed_min:.1f} minutes")

    # Transcript (last utterances)
    if context.recent_utterances:
        parts.append("\n## Recent Transcript")
        for utt in context.recent_utterances:
            role_label = utt.role.upper()
            parts.append(f"[{role_label}] {utt.text}")
    else:
        parts.append("\n## Recent Transcript\n(no transcript available yet)")

    # Uncertainty
    if context.uncertainty_score > 0:
        parts.append(f"\n## Uncertainty Signal")
        parts.append(f"Score: {context.uncertainty_score:.2f}")
        if context.uncertainty_topic:
            parts.append(f"Topic: {context.uncertainty_topic}")

    # Session metrics
    parts.append(f"\n## Session Metrics")
    parts.append(f"Tutor talk ratio: {context.tutor_talk_ratio:.0%}")
    parts.append(f"Student talk ratio: {context.student_talk_ratio:.0%}")
    if context.student_engagement_score > 0:
        parts.append(
            f"Student engagement: {context.student_engagement_score:.2f}"
        )

    # Recent suggestions (for deduplication)
    if context.recent_suggestions:
        parts.append(f"\n## Previously Given Suggestions (avoid repeating)")
        for sug in context.recent_suggestions:
            parts.append(f"- [{sug.action}] {sug.suggestion}")

    return "\n".join(parts)


def build_system_prompt(session_type: str = "general") -> str:
    """Build the full system prompt with session-type guidance interpolated."""
    guidance = SESSION_TYPE_GUIDANCE.get(
        session_type, SESSION_TYPE_GUIDANCE["general"]
    )
    return SYSTEM_PROMPT.format(session_type_guidance=guidance)
