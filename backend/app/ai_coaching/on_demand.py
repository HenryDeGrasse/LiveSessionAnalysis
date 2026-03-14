"""On-demand AI coaching suggestion endpoint.

POST /api/sessions/{session_id}/suggest — tutor-initiated request that
bypasses the interval check but still respects the hourly budget. Adds a
focused prompt addition: 'The tutor is explicitly asking for help right now.'
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.ai_coaching.context import AICoachingContext
from app.ai_coaching.feedback import register_suggestion_context
from app.ai_coaching.output_validator import CoachingSuggestion
from app.ai_coaching.prompts import build_system_prompt, build_user_prompt
from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.models import Role
from app.session_manager import session_manager
from app.session_runtime import get_or_create_resources

logger = logging.getLogger(__name__)

router = APIRouter()

_ON_DEMAND_PROMPT_ADDITION = "The tutor is explicitly asking for help right now."


def _get_runtime_resource(room: Any, key: str) -> Any:
    """Resolve a runtime resource from session resources or legacy room attrs."""
    resources = get_or_create_resources(room)
    if key in resources:
        return resources[key]
    return getattr(room, key, None)


@router.post("/api/sessions/{session_id}/suggest")
async def on_demand_suggest(
    session_id: str,
    token: str = "",
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Generate an on-demand AI coaching suggestion.

    The tutor can explicitly request a suggestion at any time. This bypasses
    the normal interval gating but still respects the hourly budget ceiling.
    Returns 429 when the budget is exhausted.
    """
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Auth: require tutor role via session token or authenticated user.
    authorized = False
    if token:
        resolved_role = room.get_role_for_token(token)
        authorized = resolved_role == Role.TUTOR
    elif current_user is not None:
        authorized = room.tutor_id == current_user.id

    if not authorized:
        raise HTTPException(status_code=403, detail="Only the tutor can request suggestions")

    copilot = _get_runtime_resource(room, "ai_copilot")
    if copilot is None:
        raise HTTPException(
            status_code=503,
            detail="AI coaching copilot not available for this session",
        )

    now = time.time()
    if copilot.calls_remaining(now) <= 0:
        raise HTTPException(
            status_code=429,
            detail="AI coaching budget exhausted for this session",
        )

    transcript_buffer = _get_runtime_resource(room, "transcript_buffer")
    if transcript_buffer is None:
        raise HTTPException(status_code=503, detail="Transcript buffer not available")

    recent_utterances = transcript_buffer._within(copilot._context_window)
    context = AICoachingContext(
        session_id=session_id,
        session_type=copilot._session_type,
        elapsed_seconds=room.elapsed_seconds() or 0.0,
        recent_utterances=recent_utterances,
        recent_suggestions=list(copilot.recent_suggestions[-5:]),
    )

    system_prompt = build_system_prompt(copilot._session_type)
    user_prompt = f"{_ON_DEMAND_PROMPT_ADDITION}\n\n{build_user_prompt(context)}"

    scrub_result = copilot._pii_scrubber.scrub(user_prompt)
    user_prompt = scrub_result.text

    copilot._record_call(now)

    try:
        raw_response = await copilot._llm.generate(
            system_prompt, user_prompt, max_tokens=512
        )
    except Exception:
        logger.exception("On-demand suggest: LLM call failed")
        raw_response = None

    if raw_response is None:
        logger.warning("On-demand suggest: LLM returned None")
        return {
            "status": "no_suggestion",
            "message": "Could not generate a suggestion at this time",
            "calls_remaining": copilot.calls_remaining(now),
        }

    suggestion = copilot._parse_response(raw_response)
    if suggestion is None:
        logger.warning("On-demand suggest: failed to parse LLM response")
        return {
            "status": "no_suggestion",
            "message": "Could not generate a suggestion at this time",
            "calls_remaining": copilot.calls_remaining(now),
        }

    coaching_suggestion = CoachingSuggestion(
        suggestion=suggestion.suggestion,
        suggested_prompt=suggestion.suggested_prompt or None,
    )
    validated = copilot._validator.validate(coaching_suggestion)
    if validated is None:
        logger.info("On-demand suggest: suggestion rejected by validator")
        return {
            "status": "no_suggestion",
            "message": "Suggestion did not pass validation",
            "calls_remaining": copilot.calls_remaining(now),
        }

    copilot._record_suggestion(suggestion, now)

    suggestion_id = f"ai-sug-{uuid4().hex[:12]}"
    register_suggestion_context(
        session_id=session_id,
        suggestion_id=suggestion_id,
        created_at=now,
        context={
            "source": "on_demand",
            "prompt_addition": _ON_DEMAND_PROMPT_ADDITION,
            "session_type": context.session_type,
            "elapsed_seconds": context.elapsed_seconds,
            "recent_utterances": [
                {
                    "utterance_id": utterance.utterance_id,
                    "role": utterance.role,
                    "text": utterance.text,
                    "start_time": utterance.start_time,
                    "end_time": utterance.end_time,
                    "confidence": utterance.confidence,
                }
                for utterance in recent_utterances
            ],
            "suggestion": {
                "action": suggestion.action,
                "topic": suggestion.topic,
                "observation": suggestion.observation,
                "suggestion": suggestion.suggestion,
                "suggested_prompt": suggestion.suggested_prompt,
                "priority": suggestion.priority,
                "confidence": suggestion.confidence,
            },
        },
    )

    return {
        "status": "ok",
        "suggestion": {
            "id": suggestion_id,
            "action": suggestion.action,
            "topic": suggestion.topic,
            "observation": suggestion.observation,
            "suggestion": suggestion.suggestion,
            "suggested_prompt": suggestion.suggested_prompt,
            "priority": suggestion.priority,
            "confidence": suggestion.confidence,
        },
        "calls_remaining": copilot.calls_remaining(now),
    }
