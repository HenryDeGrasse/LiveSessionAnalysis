"""POST /api/sessions/{session_id}/ai-summary endpoint.

Generates a post-session AI summary from the stored transcript.
Gated behind ``enable_ai_session_summary`` configuration flag.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.ai_coaching.session_summary import generate_ai_session_summary
from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.config import settings
from app.models import Role
from app.session_manager import session_manager
from app.session_runtime import _session_resources
from app.transcription.models import FinalUtterance, WordTiming

logger = logging.getLogger(__name__)

router = APIRouter()


def _hydrate_final_utterance(data: dict[str, Any]) -> FinalUtterance:
    """Rebuild a ``FinalUtterance`` from stored compact transcript payload."""
    words = [
        WordTiming(**word)
        for word in data.get("words", [])
        if isinstance(word, dict)
    ]
    return FinalUtterance(
        role=data.get("role", "student"),
        text=data.get("text", ""),
        start_time=float(data.get("start_time", 0.0)),
        end_time=float(data.get("end_time", 0.0)),
        utterance_id=data.get("utterance_id", ""),
        words=words,
        confidence=float(data.get("confidence", 1.0)),
        sentiment=data.get("sentiment"),
        sentiment_score=float(data.get("sentiment_score", 0.0)),
        language=data.get("language", "en"),
        channel=int(data.get("channel", 0)),
        speaker_id=data.get("speaker_id"),
        student_index=int(data.get("student_index", 0)),
    )


def _get_transcript_utterances(session_id: str) -> list[FinalUtterance]:
    """Retrieve transcript utterances from memory or persisted session storage."""
    resources = _session_resources.get(session_id)
    if resources is not None:
        transcript_store = resources.get("transcript_store")
        if transcript_store is not None:
            return transcript_store.utterances

    try:
        from app.analytics import get_session_store

        summary = get_session_store().load(session_id)
    except Exception as exc:
        logger.warning(
            "Session %s: failed to load persisted transcript payload: %s",
            session_id,
            exc,
        )
        return []

    if summary is None or not summary.transcript_compact:
        return []

    utterances: list[FinalUtterance] = []
    for item in summary.transcript_compact.get("utterances", []):
        if not isinstance(item, dict):
            continue
        try:
            utterances.append(_hydrate_final_utterance(item))
        except Exception as exc:
            logger.debug(
                "Session %s: skipping malformed persisted utterance: %s",
                session_id,
                exc,
            )
    return utterances


def _build_llm_client() -> Any:
    """Build the appropriate LLM client based on configuration."""
    if settings.ai_coaching_provider == "anthropic" and settings.anthropic_api_key:
        from app.ai_coaching.llm_client import AnthropicLLMClient

        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.ai_coaching_model,
        )
    return None


@router.post("/api/sessions/{session_id}/ai-summary")
async def create_ai_session_summary(
    session_id: str,
    token: str = "",
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Generate a post-session AI summary for a completed session.

    Requires tutor authorization via session token or authenticated user.
    Returns 404 if session not found, 403 if unauthorized, 503 if AI
    summary feature is not enabled or LLM client not available.
    """
    if not settings.enable_ai_session_summary:
        raise HTTPException(
            status_code=503,
            detail="AI session summary feature is not enabled",
        )

    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Auth: require tutor role via session token or authenticated user
    authorized = False
    if token:
        resolved_role = room.get_role_for_token(token)
        authorized = resolved_role == Role.TUTOR
    elif current_user is not None:
        authorized = room.tutor_id == current_user.id

    if not authorized:
        raise HTTPException(
            status_code=403,
            detail="Only the tutor can request an AI session summary",
        )

    # Get transcript utterances
    utterances = _get_transcript_utterances(session_id)
    if not utterances:
        raise HTTPException(
            status_code=404,
            detail="No transcript data available for this session",
        )

    # Build LLM client
    llm_client = _build_llm_client()
    if llm_client is None:
        raise HTTPException(
            status_code=503,
            detail="AI session summary LLM client is not configured",
        )

    # Generate summary
    duration_seconds = room.elapsed_seconds() or 0.0
    ai_summary = await generate_ai_session_summary(
        utterances,
        llm_client,
        session_type=room.session_type,
        duration_seconds=duration_seconds,
    )

    if ai_summary is None:
        return {
            "status": "no_summary",
            "message": "Could not generate an AI summary at this time",
        }

    # Persist summary fields to session summary if available
    try:
        from app.analytics import get_session_store

        store = get_session_store()
        existing = store.load(session_id)
        if existing is not None:
            existing.ai_summary = ai_summary.session_narrative
            existing.topics_covered = ai_summary.topics_covered
            existing.student_understanding_map = ai_summary.student_understanding_map
            existing.key_moments = ai_summary.key_moments
            existing.follow_up_recommendations = ai_summary.recommended_follow_up
            store.save(existing)
    except Exception as exc:
        logger.warning(
            "Session %s: failed to persist AI summary to session store: %s",
            session_id,
            exc,
        )

    return {
        "status": "ok",
        "summary": {
            "topics_covered": ai_summary.topics_covered,
            "key_moments": ai_summary.key_moments,
            "student_understanding_map": ai_summary.student_understanding_map,
            "tutor_strengths": ai_summary.tutor_strengths,
            "tutor_growth_areas": ai_summary.tutor_growth_areas,
            "recommended_follow_up": ai_summary.recommended_follow_up,
            "session_narrative": ai_summary.session_narrative,
        },
    }
