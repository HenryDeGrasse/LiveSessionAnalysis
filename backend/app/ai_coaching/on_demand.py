"""On-demand AI coaching suggestion endpoint.

POST /api/sessions/{session_id}/suggest — tutor-initiated request that
bypasses the interval check but still respects the hourly budget. Adds a
focused prompt addition: 'The tutor is explicitly asking for help right now.'

Supports two modes:
- **JSON** (default): returns the full suggestion as a JSON response.
- **SSE streaming** (`Accept: text/event-stream`): streams LLM tokens to
  the frontend in real time, then sends the parsed suggestion as a final
  event.  This gives the tutor visual feedback within ~400ms.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

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


def _authorize_tutor(room: Any, token: str, current_user: Optional[User]) -> bool:
    """Check that the caller is the session's tutor."""
    if token:
        resolved_role = room.get_role_for_token(token)
        if resolved_role == Role.TUTOR:
            return True
    if current_user is not None:
        if room.tutor_id == current_user.id or current_user.role == "tutor":
            return True
    return False


def _build_prompt_context(room: Any, copilot: Any):
    """Build the system/user prompts and return (system, user, context, recent)."""
    transcript_buffer = _get_runtime_resource(room, "transcript_buffer")
    if transcript_buffer is None:
        return None

    recent_utterances = transcript_buffer._within(copilot._context_window)
    context = AICoachingContext(
        session_id=getattr(room, "session_id", ""),
        session_type=copilot._session_type,
        elapsed_seconds=room.elapsed_seconds() or 0.0,
        recent_utterances=recent_utterances,
        recent_suggestions=list(copilot.recent_suggestions[-5:]),
    )

    system_prompt = build_system_prompt(copilot._session_type)
    user_prompt = f"{_ON_DEMAND_PROMPT_ADDITION}\n\n{build_user_prompt(context)}"
    scrub_result = copilot._pii_scrubber.scrub(user_prompt)

    return system_prompt, scrub_result.text, context, recent_utterances


def _build_suggestion_response(
    copilot: Any,
    raw_response: str,
    session_id: str,
    context: Any,
    recent_utterances: Any,
    now: float,
) -> dict:
    """Parse, validate, record, and build the final JSON response dict."""
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
                    "utterance_id": u.utterance_id,
                    "role": u.role,
                    "text": u.text,
                    "start_time": u.start_time,
                    "end_time": u.end_time,
                    "confidence": u.confidence,
                }
                for u in recent_utterances
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


@router.post("/api/sessions/{session_id}/suggest")
async def on_demand_suggest(
    request: Request,
    session_id: str,
    token: str = "",
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Generate an on-demand AI coaching suggestion.

    If the client sends ``Accept: text/event-stream``, the response is
    streamed as SSE events:

    - ``event: token`` / ``data: <text>``  — individual LLM tokens
    - ``event: suggestion`` / ``data: <json>`` — final parsed suggestion
    - ``event: error`` / ``data: <json>`` — error details
    - ``event: done`` / ``data: {}`` — stream complete

    Otherwise returns a normal JSON response.
    """
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not _authorize_tutor(room, token, current_user):
        raise HTTPException(status_code=403, detail="Only the tutor can request suggestions")

    copilot = _get_runtime_resource(room, "ai_copilot")
    if copilot is None:
        raise HTTPException(status_code=503, detail="AI coaching copilot not available for this session")

    now = time.time()
    if copilot.calls_remaining(now) <= 0:
        raise HTTPException(status_code=429, detail="AI coaching budget exhausted for this session")

    prompt_result = _build_prompt_context(room, copilot)
    if prompt_result is None:
        raise HTTPException(status_code=503, detail="Transcript buffer not available")
    system_prompt, user_prompt, context, recent_utterances = prompt_result

    copilot._record_call(now)

    # Pick the fast on-demand LLM or fall back to copilot default
    ondemand_llm = _get_runtime_resource(room, "ondemand_llm")
    llm = ondemand_llm if ondemand_llm is not None else copilot._llm
    model_name = getattr(llm, "_model", "unknown")

    # Check if client wants SSE streaming
    accept = request.headers.get("accept", "")
    wants_stream = "text/event-stream" in accept

    if wants_stream and hasattr(llm, "stream_chunks"):
        logger.info("On-demand suggest: SSE stream, model=%s", model_name)
        return StreamingResponse(
            _sse_stream(llm, system_prompt, user_prompt, copilot, session_id, context, recent_utterances, now),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming JSON path
    logger.info("On-demand suggest: JSON mode, model=%s", model_name)
    t0 = time.monotonic()

    try:
        if hasattr(llm, "generate_stream"):
            raw_response = await llm.generate_stream(system_prompt, user_prompt, max_tokens=300)
        else:
            raw_response = await llm.generate(system_prompt, user_prompt, max_tokens=300)
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.info("On-demand suggest: LLM responded in %.0fms (%d chars)", elapsed_ms, len(raw_response or ""))
    except Exception:
        logger.exception("On-demand suggest: LLM call failed")
        raw_response = None

    if raw_response is None:
        return {
            "status": "no_suggestion",
            "message": "Could not generate a suggestion at this time",
            "calls_remaining": copilot.calls_remaining(now),
        }

    return _build_suggestion_response(copilot, raw_response, session_id, context, recent_utterances, now)


async def _sse_stream(llm, system_prompt, user_prompt, copilot, session_id, context, recent_utterances, now):
    """Async generator that yields SSE-formatted events."""
    chunks: list[str] = []
    t0 = time.monotonic()

    try:
        async for token_text in llm.stream_chunks(system_prompt, user_prompt, max_tokens=300):
            chunks.append(token_text)
            # Send each token as an SSE event
            yield f"event: token\ndata: {json.dumps(token_text)}\n\n"

        elapsed_ms = (time.monotonic() - t0) * 1000
        raw_response = "".join(chunks)
        logger.info("On-demand suggest SSE: LLM streamed in %.0fms (%d chars)", elapsed_ms, len(raw_response))

        if not raw_response:
            yield f"event: error\ndata: {json.dumps({'message': 'No response from model'})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        # Parse and validate the full response
        result = _build_suggestion_response(copilot, raw_response, session_id, context, recent_utterances, now)
        yield f"event: suggestion\ndata: {json.dumps(result)}\n\n"

    except Exception:
        logger.exception("On-demand suggest SSE: stream failed")
        yield f"event: error\ndata: {json.dumps({'message': 'Stream failed'})}\n\n"

    yield "event: done\ndata: {}\n\n"
