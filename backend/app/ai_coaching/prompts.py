"""Prompt templates for the AI coaching copilot.

Architecture: The rule engine and metrics system handle signal
interpretation and situation analysis.  The LLM's ONE job is to
write natural dialogue — a sentence the tutor can say right now.

The context builder pre-interprets signals into a focused narrative
brief so the LLM doesn't waste tokens re-analyzing raw numbers.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.ai_coaching.context import AICoachingContext

# --------------------------------------------------------------------------- #
# System prompt — lean, focused on the ONE job
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
You write real-time coaching scripts for live tutoring sessions.

You receive a brief describing what is happening and what the tutor needs to do. \
Your job is to write a natural, conversational sentence the tutor can say OUT LOUD \
to the student right now.

## Hard Rules
1. Sound like a real person — warm, natural, not robotic or formal.
2. Reference what was actually said or the specific topic when possible.
3. The tutor should be able to glance at your output and say it immediately.
4. Use the FULL range of coaching actions — don't just ask questions. \
Scaffold with concrete steps, give analogies, walk through examples, \
offer encouragement, or redirect approach. Match the action to the moment.

## Session Context
{session_type_guidance}

## Output — MANDATORY FORMAT
Your ENTIRE response must be a single JSON object. No text before or after it. \
No explanation. No markdown headers. Just the JSON:

{{"action": "<probe|scaffold|redirect|encourage|check_understanding|re_engage|wait>", "topic": "<specific topic>", "observation": "<1 sentence>", "suggestion": "<1-2 sentences explaining the coaching strategy>", "suggested_prompt": "<THE MAIN OUTPUT: complete sentence the tutor says to student>", "priority": "<high|medium|low>", "confidence": <0.0-1.0>}}

The `suggested_prompt` is your primary deliverable — a natural sentence the tutor says out loud.

## Action Guide
- **probe**: Ask a targeted question to find out what the student is thinking or where they're stuck.
- **scaffold**: Walk the student through a concrete step, technique, analogy, or worked example. \
Give them a specific method they can follow — not just a question.
- **redirect**: Steer the student away from a dead end or misconception toward a better approach.
- **encourage**: Recognize effort or progress to build confidence and momentum.
- **check_understanding**: Verify the student actually got it — ask them to explain back or apply it.
- **re_engage**: Pull a distracted or silent student back into the conversation.
- **wait**: Nothing needed right now — session is flowing well.

## Example Responses

Scaffold — giving a concrete method:
{{"action": "scaffold", "topic": "adding fractions", "observation": "Student is trying to add one-third and one-fourth but adding the denominators.", "suggestion": "Walk through finding a common denominator step by step.", "suggested_prompt": "Okay so when we add fractions with different bottoms, we need to find a common denominator first — what's a number that both three and four go into evenly?", "priority": "high", "confidence": 0.9}}

Scaffold — offering an analogy:
{{"action": "scaffold", "topic": "variables in algebra", "observation": "Student doesn't understand what x represents in the equation.", "suggestion": "Use a concrete analogy to make variables tangible.", "suggested_prompt": "Think of x like a mystery box — there's a number hiding inside it, and our job is to figure out what number makes the equation balance. So if we have x plus three equals seven, what number would you put in the box?", "priority": "high", "confidence": 0.88}}

Probe — finding the gap:
{{"action": "probe", "topic": "fractions", "observation": "Student said they don't understand why both numbers get divided.", "suggestion": "Find out which part of simplification is confusing before re-explaining.", "suggested_prompt": "When I said we divide both the top and bottom by two, what part felt confusing — the dividing part, or why we pick the number two?", "priority": "high", "confidence": 0.85}}

Redirect — steering away from a misconception:
{{"action": "redirect", "topic": "photosynthesis", "observation": "Student thinks plants eat sunlight like food.", "suggestion": "Redirect with an analogy that separates energy source from food.", "suggested_prompt": "That's a cool way to think about it — but sunlight is more like the power outlet than the food itself. The plant uses that energy to build its own food from CO2 and water. So what do you think the actual 'food' the plant makes is?", "priority": "medium", "confidence": 0.82}}

Encourage — building confidence:
{{"action": "encourage", "topic": "essay structure", "observation": "Student just reorganized their paragraph order and it improved the flow.", "suggestion": "Reinforce the good instinct before moving on.", "suggested_prompt": "Nice — see how moving that paragraph up front makes the whole argument click? That was a really good call. Now let's look at your conclusion with that same eye.", "priority": "medium", "confidence": 0.8}}\
"""

# --------------------------------------------------------------------------- #
# Session type guidance — compact, behavior-focused
# --------------------------------------------------------------------------- #

SESSION_TYPE_GUIDANCE: Dict[str, str] = {
    "general": (
        "General tutoring. Student should talk 30-40%+ of the time. "
        "Balance explanation with questions. When the student is stuck, "
        "scaffold with concrete steps or analogies — don't just keep asking questions."
    ),
    "math": (
        "Math session. Mix scaffolding with questions — when a student is stuck, "
        "walk them through the METHOD, not just ask what they think. "
        "For example: show how to find common denominators step by step, "
        "explain why we invert and multiply for division, "
        "or use real-world analogies (pizza slices for fractions, balance scales for equations). "
        "Push for think-alouds: 'Walk me through your thinking.' "
        "When they get a step right, name what they did well before moving on."
    ),
    "reading": (
        "Reading/literacy. Ask comprehension at multiple levels: "
        "what happened (literal), why (inferential), what do you think (evaluative). "
        "Model think-alouds. When a student misreads a passage, scaffold by pointing to "
        "context clues or key sentences — don't just ask them to re-read."
    ),
    "science": (
        "Science session. Use concrete analogies to make abstract concepts click "
        "(e.g. electrons like marbles in a track, cells like factories). "
        "Drive with hypothesis questions: 'What do you think would happen if...?' "
        "When confused, break the concept into a simpler example first, then build back up."
    ),
    "writing": (
        "Writing session. Guide the process (brainstorm → organize → draft → revise). "
        "When a student's paragraph is unclear, help them find the core idea: "
        "'What's the one thing you want the reader to take away from this paragraph?' "
        "Offer structural scaffolds like topic-sentence patterns or transition phrases."
    ),
    "test_prep": (
        "Test prep. Focus on strategy/process, not just answers. "
        "When wrong, explore WHY they chose that answer, then scaffold the correct approach. "
        "Teach elimination techniques, time management, and how to break complex problems into parts."
    ),
    "lecture": (
        "Lecture format (tutor-heavy is expected). "
        "Still check comprehension every 3-5 minutes. "
        "Use quick scaffolding checks: 'So if I change this one thing, what would happen?'"
    ),
    "practice": (
        "Practice session — student does most of the work. "
        "When stuck, give a hint or the next step rather than the full solution. "
        "Let them struggle productively but don't let them spin for too long."
    ),
    "socratic": (
        "Socratic method. Tutor asks questions, rarely makes statements. "
        "Respond to wrong answers with questions that expose the flaw. "
        "Give wait time. If student is truly stuck after 2+ attempts, offer a scaffold."
    ),
}

# --------------------------------------------------------------------------- #
# Situation briefs — pre-interpreted narratives for each scenario
# --------------------------------------------------------------------------- #

# Maps rule names to templates that produce focused narrative briefs.
# The templates reference context fields to produce specific, grounded text.
# Fallback handles ambient suggestions when no rule fired.

_ATTENTION_LABELS: Dict[str, str] = {
    "CAMERA_FACING": "looking at the camera",
    "SCREEN_ENGAGED": "looking at their screen",
    "DOWN_ENGAGED": "looking down (maybe writing)",
    "OFF_TASK_AWAY": "looking away from the screen",
    "FACE_MISSING": "not visible on camera",
    "LOW_CONFIDENCE": "unclear visual signal",
}


def _student_last_words(context: AICoachingContext) -> str:
    """Extract the student's last meaningful utterance text."""
    for utt in reversed(context.recent_utterances):
        if utt.role == "student" and len(utt.text.strip()) > 3:
            return utt.text.strip()
    return ""


def _tutor_last_words(context: AICoachingContext) -> str:
    """Extract the tutor's last utterance text."""
    for utt in reversed(context.recent_utterances):
        if utt.role == "tutor" and len(utt.text.strip()) > 3:
            return utt.text.strip()
    return ""


def _topic_label(context: AICoachingContext) -> str:
    """Best available topic label."""
    if context.uncertainty_topic:
        return context.uncertainty_topic
    if context.topic_keywords:
        return ", ".join(context.topic_keywords[:3])
    return "the current topic"


def _build_situation_brief_for_rule(context: AICoachingContext) -> str:
    """Build a pre-interpreted situation brief when a coaching rule fired.

    Returns a focused 2-4 sentence narrative that tells the LLM exactly
    what happened and what the tutor needs to do — no raw numbers.
    """
    rule = context.active_rule_nudge
    student_said = _student_last_words(context)
    topic = _topic_label(context)
    elapsed_min = context.elapsed_seconds / 60.0

    if rule == "check_for_understanding":
        brief = (
            f"The tutor has been explaining {topic} for a while without checking "
            f"if the student is following."
        )
        if student_said:
            brief += (
                f' The student\'s last comment was: "{student_said}" '
                f"— but the tutor kept going."
            )
        if context.time_since_student_spoke > 30:
            brief += (
                f" The student hasn't spoken in "
                f"{int(context.time_since_student_spoke)} seconds."
            )
        brief += (
            "\n\nWrite something the tutor can say to check understanding. "
            "Options (pick the best fit): "
            "(a) Ask the student to explain back a specific part in their own words, "
            "(b) Give a quick worked example and ask them to try the next step, "
            "(c) Use an analogy that makes the concept more concrete, then check if it clicks. "
            "Reference the specific topic — not a generic 'does that make sense.'"
        )
        return brief

    if rule == "student_off_task":
        state_desc = _ATTENTION_LABELS.get(
            context.student_attention_state, "away"
        )
        brief = (
            f"The student has been {state_desc} for "
            f"{int(context.student_time_in_attention_state)} seconds. "
            f"They may be distracted or having a technical issue."
        )
        brief += (
            "\n\nWrite something the tutor can say to gently re-engage "
            f"the student. Pull them back to {topic} — try an interesting "
            "hook, a quick example, or a low-stakes question rather than "
            "just asking if they're still there."
        )
        return brief

    if rule in ("let_them_finish", "interruption_burst"):
        brief = (
            f"The tutor has been cutting off the student — "
            f"{context.recent_hard_interruptions} interruptions detected recently."
        )
        if context.tutor_cutoffs > 0:
            brief += (
                f" The tutor has talked over the student "
                f"{context.tutor_cutoffs} time(s)."
            )
        brief += (
            "\n\nWrite something the tutor can say to give the student "
            "space to finish their thought. It should feel natural, "
            "not like an apology — just an invitation to continue."
        )
        return brief

    if rule == "tech_check":
        brief = (
            f"Both participants have been silent for "
            f"{int(context.mutual_silence_seconds)} seconds "
            f"and something seems off technically "
            f"(student is {_ATTENTION_LABELS.get(context.student_attention_state, 'unclear')})."
        )
        brief += (
            "\n\nWrite a quick check-in the tutor can say to see "
            "if the student can hear/see them, without sounding alarmed."
        )
        return brief

    if rule == "re_engage_silence":
        brief = (
            f"Both the tutor and student have been quiet for "
            f"{int(context.mutual_silence_seconds)} seconds. "
            f"Both are present on camera — this is conversational dead air, "
            f"not a tech issue."
        )
        brief += (
            f"\n\nWrite a low-pressure question about {topic} to restart "
            "the conversation. Make it easy to answer — something the student "
            "can respond to without feeling put on the spot."
        )
        return brief

    if rule == "encourage_student_response":
        brief = (
            f"The student has been quiet for "
            f"{int(context.time_since_student_spoke)} seconds even though "
            f"they're visually present "
            f"({_ATTENTION_LABELS.get(context.student_attention_state, 'on camera')}). "
            f"The tutor isn't dominating — the student just isn't participating."
        )
        if student_said:
            brief += f' Their last comment was: "{student_said}".'
        brief += (
            "\n\nWrite a direct but warm question the tutor can ask to "
            "draw the student into the conversation. Reference the topic."
        )
        return brief

    if rule == "session_momentum_loss":
        brief = (
            f"The session momentum is fading — engagement has been declining "
            f"and interaction has slowed down significantly. "
            f"They've been at this for {elapsed_min:.0f} minutes."
        )
        brief += (
            "\n\nWrite something the tutor can say to shift energy. Options: "
            "(a) Propose a different approach or real-world example for the same topic, "
            "(b) Acknowledge the grind and suggest a quick mental break, "
            "(c) Switch to a more interactive exercise ('let me give you a quick challenge'). "
            "Pick whatever best fits the moment."
        )
        return brief

    # Unknown rule — generic fallback
    brief = f"A coaching alert fired: {rule}."
    if context.active_rule_message:
        brief += f" {context.active_rule_message}"
    brief += (
        f"\n\nWrite a natural sentence the tutor can say to address this. "
        f"The topic is {topic}."
    )
    return brief


def _build_ambient_situation_brief(context: AICoachingContext) -> str:
    """Build a situation brief when NO rule fired (ambient evaluation).

    Identifies the single most notable signal and frames it as a
    focused directive for the LLM.
    """
    student_said = _student_last_words(context)
    topic = _topic_label(context)
    signals: List[Tuple[float, str]] = []  # (urgency, brief)

    # 1. High uncertainty — most actionable
    if context.uncertainty_score >= 0.5:
        urgency = context.uncertainty_score
        brief = (
            f"The student seems confused about {context.uncertainty_topic or topic} "
            f"(uncertainty score: {context.uncertainty_score:.0%})."
        )
        if student_said:
            brief += f' They said: "{student_said}".'
        brief += (
            "\n\nHelp the tutor address the confusion. Options (pick the best fit): "
            "(a) Scaffold with a concrete example, analogy, or step-by-step walkthrough, "
            "(b) Probe with a targeted question to pinpoint the specific gap, "
            "(c) Redirect by reframing the concept from a different angle. "
            "If the student's confusion is about a procedure (like how to solve something), "
            "prefer scaffolding with a worked example over just asking more questions."
        )
        signals.append((urgency, brief))

    # 2. Student energy drop
    if context.student_energy_drop > 0.2:
        urgency = min(0.9, 0.5 + context.student_energy_drop)
        brief = (
            "The student's vocal energy has dropped noticeably — "
            "they may be losing focus, getting frustrated, or just tired."
        )
        brief += (
            "\n\nWrite something encouraging the tutor can say. "
            "Acknowledge effort, suggest a shift, or check how they're feeling."
        )
        signals.append((urgency, brief))

    # 3. Tutor monologue (no rule fired but getting long)
    if context.tutor_monologue_seconds > 60:
        urgency = min(0.85, 0.4 + context.tutor_monologue_seconds / 300)
        brief = (
            f"The tutor has been talking for {int(context.tutor_monologue_seconds)} "
            f"seconds straight about {topic}."
        )
        if student_said:
            brief += f' The student last said: "{student_said}".'
        brief += (
            "\n\nBreak the monologue. Options: "
            "(a) Give the student a quick hands-on task ('try this one'), "
            "(b) Ask them to explain back the last thing in their own words, "
            "(c) Offer a concrete example and ask them to predict the next step."
        )
        signals.append((urgency, brief))

    # 4. Student quiet + visually disengaged
    if (
        context.time_since_student_spoke > 45
        and context.student_attention_state in ("OFF_TASK_AWAY", "FACE_MISSING")
    ):
        urgency = 0.75
        state_desc = _ATTENTION_LABELS.get(
            context.student_attention_state, "away"
        )
        brief = (
            f"The student hasn't spoken in {int(context.time_since_student_spoke)}s "
            f"and is {state_desc}."
        )
        brief += (
            f"\n\nWrite a gentle re-engagement question about {topic}."
        )
        signals.append((urgency, brief))

    # 5. Turn imbalance (student barely talking)
    if (
        context.student_turn_count > 0
        and context.tutor_turn_count > 0
        and context.tutor_turn_count > context.student_turn_count * 3
    ):
        urgency = 0.5
        brief = (
            f"The conversation is very tutor-heavy: {context.tutor_turn_count} "
            f"tutor turns vs {context.student_turn_count} student turns."
        )
        brief += (
            "\n\nGet the student doing something. Options: "
            f"(a) Give them a small problem to try on {topic}, "
            "(b) Ask them to walk through the last example in their own words, "
            "(c) Ask an open-ended question that requires more than a yes/no."
        )
        signals.append((urgency, brief))

    # 6. Mutual silence (not long enough for a rule but notable)
    if context.mutual_silence_seconds > 15:
        urgency = 0.4
        brief = (
            f"There's been a {int(context.mutual_silence_seconds)}-second "
            f"silence in the conversation about {topic}."
        )
        brief += (
            "\n\nWrite a natural conversation-restarter about the topic."
        )
        signals.append((urgency, brief))

    # Pick the most urgent signal
    if signals:
        signals.sort(key=lambda x: x[0], reverse=True)
        return signals[0][1]

    # Nothing notable — generic pedagogical prompt
    brief = f"The session is going normally. The topic is {topic}."
    if student_said:
        brief += f' The student recently said: "{student_said}".'
    brief += (
        "\n\nIf there's a natural coaching opportunity based on the "
        "transcript (a chance to probe deeper, scaffold, or encourage), "
        "write a suggested prompt. Otherwise set confidence below 0.3."
    )
    return brief


# --------------------------------------------------------------------------- #
# Prompt builders
# --------------------------------------------------------------------------- #


def _recent_exchanges(context: AICoachingContext, max_turns: int = 6) -> str:
    """Format the last N utterances as a compact transcript excerpt.

    Focuses on the most recent exchanges since that's what the tutor's
    script should reference.  Includes sentiment tags when available.
    """
    utterances = context.recent_utterances[-max_turns:]
    if not utterances:
        return "(no transcript yet)"

    lines: List[str] = []
    for utt in utterances:
        role = utt.role.upper()
        sentiment_tag = ""
        if (
            hasattr(utt, "sentiment")
            and utt.sentiment
            and utt.sentiment != "neutral"
        ):
            sentiment_tag = f" [{utt.sentiment}]"
        lines.append(f"[{role}]{sentiment_tag} {utt.text}")
    return "\n".join(lines)


def build_user_prompt(context: AICoachingContext) -> str:
    """Build a focused user prompt with a pre-interpreted situation brief.

    Structure:
    1. Situation brief (what's happening + what to do) — the core directive
    2. Recent transcript (last few exchanges for reference)
    3. Previous suggestions (for dedup)

    The LLM's job is to write dialogue, not analyze data.
    """
    parts: List[str] = []

    # ── Situation brief (pre-interpreted) ─────────────────────────────
    if context.active_rule_nudge:
        brief = _build_situation_brief_for_rule(context)
    else:
        brief = _build_ambient_situation_brief(context)

    parts.append("## Situation")
    parts.append(brief)

    # ── Recent transcript (compact) ───────────────────────────────────
    parts.append("\n## Recent Conversation")
    parts.append(_recent_exchanges(context, max_turns=6))

    # ── Dedup: previous suggestions ───────────────────────────────────
    if context.recent_suggestions:
        parts.append("\n## Already Suggested (don't repeat)")
        for sug in context.recent_suggestions:
            parts.append(f"- {sug.suggested_prompt or sug.suggestion}")

    return "\n".join(parts)


def build_system_prompt(session_type: str = "general") -> str:
    """Build the system prompt with session-type guidance interpolated."""
    guidance = SESSION_TYPE_GUIDANCE.get(
        session_type, SESSION_TYPE_GUIDANCE["general"]
    )
    return SYSTEM_PROMPT.format(session_type_guidance=guidance)
