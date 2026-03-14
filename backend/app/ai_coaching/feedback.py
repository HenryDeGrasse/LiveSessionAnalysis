"""Suggestion feedback endpoint and in-memory eval dataset helpers.

POST /api/sessions/{session_id}/suggestion-feedback — accepts tutor
feedback on a coaching suggestion for eval dataset construction.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.models import Role
from app.session_manager import session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


class SuggestionFeedback(BaseModel):
    """Feedback payload for a coaching suggestion."""

    suggestion_id: str
    helpful: bool
    comment: Optional[str] = None


class SuggestionContextRecord(BaseModel):
    """Captured suggestion + session context for later feedback joins."""

    session_id: str
    suggestion_id: str
    created_at: float = 0.0
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackRecord(BaseModel):
    """Internal record combining feedback with suggestion/session metadata."""

    session_id: str
    suggestion_id: str
    helpful: bool
    comment: Optional[str] = None
    timestamp: float = 0.0
    suggestion_context: Optional[dict[str, Any]] = None


# In-memory stores for feedback records and suggestion context.
# These are intentionally simple for now and can be replaced with DB persistence.
_feedback_store: list[FeedbackRecord] = []
_suggestion_context_store: dict[str, SuggestionContextRecord] = {}


def get_feedback_store() -> list[FeedbackRecord]:
    """Return the feedback store (useful for testing)."""
    return _feedback_store


def clear_feedback_store() -> None:
    """Clear all in-memory feedback/context state (useful for testing)."""
    _feedback_store.clear()
    _suggestion_context_store.clear()


def register_suggestion_context(
    *,
    session_id: str,
    suggestion_id: str,
    context: dict[str, Any],
    created_at: float | None = None,
) -> SuggestionContextRecord:
    """Register context for a generated suggestion.

    This lets the feedback endpoint later persist a labeled example containing
    both the tutor's reaction and the original suggestion/transcript context.
    """
    record = SuggestionContextRecord(
        session_id=session_id,
        suggestion_id=suggestion_id,
        created_at=time.time() if created_at is None else created_at,
        context=context,
    )
    _suggestion_context_store[suggestion_id] = record
    return record


def get_suggestion_context(suggestion_id: str) -> SuggestionContextRecord | None:
    """Return stored context for a suggestion, if available."""
    return _suggestion_context_store.get(suggestion_id)


@router.post("/api/sessions/{session_id}/suggestion-feedback")
async def submit_suggestion_feedback(
    session_id: str,
    body: SuggestionFeedback,
    token: str = "",
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Submit feedback on a coaching suggestion.

    The tutor can mark a suggestion as helpful or not, and optionally add
    a comment. Feedback is stored alongside the previously recorded
    suggestion context for evaluation dataset construction.
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
        raise HTTPException(status_code=403, detail="Only the tutor can submit feedback")

    suggestion_context = get_suggestion_context(body.suggestion_id)
    if suggestion_context is not None and suggestion_context.session_id != session_id:
        # Prevent cross-session feedback joins when clients send the wrong ID.
        suggestion_context = None

    record = FeedbackRecord(
        session_id=session_id,
        suggestion_id=body.suggestion_id,
        helpful=body.helpful,
        comment=body.comment,
        timestamp=time.time(),
        suggestion_context=(
            suggestion_context.context if suggestion_context is not None else None
        ),
    )
    _feedback_store.append(record)

    logger.info(
        "Suggestion feedback recorded: session=%s suggestion=%s helpful=%s has_context=%s",
        session_id,
        body.suggestion_id,
        body.helpful,
        suggestion_context is not None,
    )

    return {
        "status": "ok",
        "session_id": session_id,
        "suggestion_id": body.suggestion_id,
        "helpful": body.helpful,
    }
