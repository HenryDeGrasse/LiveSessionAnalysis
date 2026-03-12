from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from . import get_session_store
from .recommendations import generate_recommendations, generate_student_insights
from .trends import compute_trends
from ..auth.dependencies import get_optional_user
from ..auth.models import User
from ..models import SessionTitleUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter()
# Test-override hook: several existing backend tests patch this module-level
# name directly. In normal runtime it stays ``None`` and the router resolves
# the configured singleton lazily via ``get_session_store()`` on each request.
store = None


def _session_store():
    return store or get_session_store()


@router.get("/sessions")
async def list_sessions(
    tutor_id: str = "",
    last_n: int = 0,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """List stored sessions with summary stats.

    Auth-aware behaviour:
    - Authenticated tutor → auto-filter to sessions where tutor_id == user.id
    - Authenticated student → auto-filter to sessions where student_user_id == user.id
    - Unauthenticated with explicit tutor_id param → backward compat (home page
      session history, where tutor name is persisted locally and passed explicitly)
    - Unauthenticated with no tutor_id → return [] to prevent unauthenticated
      enumeration of all sessions (e.g. during NextAuth session load race)
    """
    resolved_tutor_id: Optional[str] = None
    resolved_student_id: Optional[str] = None

    if current_user is not None:
        if current_user.role == "student":
            resolved_student_id = current_user.id
        else:
            resolved_tutor_id = current_user.id
    else:
        # Backward compat: unauthenticated callers pass tutor_id explicitly.
        # If no tutor_id is provided and there is no authenticated user, return
        # an empty list rather than all sessions, to prevent the data-leak
        # window that occurs when NextAuth has not yet resolved the session.
        resolved_tutor_id = tutor_id or None
        if not resolved_tutor_id:
            return []

    sessions = _session_store().list_sessions(
        tutor_id=resolved_tutor_id,
        student_user_id=resolved_student_id,
        last_n=last_n if last_n > 0 else None,
    )
    return [s.model_dump() for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Get full session detail with timeline.

    Auth-aware behaviour:
    - Authenticated tutor owner → full detail including nudge_details
    - Authenticated student owner → simplified view: nudge_details scrubbed,
      recommendations scrubbed (coaching content is tutor-only)
    - Not authenticated → 401 Unauthorized (session data is private)
    """
    # Auth check before the store lookup so we never reveal whether a session
    # exists to unauthenticated callers.
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to access session details",
            headers={"WWW-Authenticate": "Bearer"},
        )

    summary = _session_store().load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not summary.is_owner(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = summary.model_dump()

    # Strip tutor-only coaching fields for authenticated student owners.
    # nudge_details are the live coaching nudges sent to the tutor during the
    # session — students should never see this payload.  recommendations are
    # generated coaching suggestions for the tutor's improvement plan.
    if current_user.role == "student":
        data["nudge_details"] = []
        data["recommendations"] = []
        # Enrich the student view with student-facing insights.
        data["student_insights"] = generate_student_insights(summary)

    return data


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: SessionTitleUpdateRequest,
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to update session details",
            headers={"WWW-Authenticate": "Bearer"},
        )

    summary = _session_store().load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not summary.is_owner(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    new_title = body.session_title.strip()
    if not new_title:
        raise HTTPException(status_code=422, detail="session_title cannot be empty")

    summary.session_title = new_title
    _session_store().save(summary)
    return summary.model_dump()


@router.get("/sessions/{session_id}/recommendations")
async def get_recommendations(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Get coaching recommendations for a session.

    Recommendations are tutor-only coaching content.  Authentication is
    required; students are denied access (403).
    """
    # Auth check before the store lookup so we never reveal whether a session
    # exists to unauthenticated callers.
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to access recommendations",
            headers={"WWW-Authenticate": "Bearer"},
        )

    summary = _session_store().load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not summary.is_owner(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Students own their sessions but must not receive tutor coaching content.
    if current_user.role == "student":
        raise HTTPException(
            status_code=403,
            detail="Recommendations are tutor-only content",
        )

    return generate_recommendations(summary)


@router.get("/sessions/{session_id}/student-insights")
async def get_student_insights(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Get student-facing insights for a session.

    Student insights are student-only content: a structured summary of engagement,
    talk-time, and attention, plus actionable tips framed for the student.
    Tutors are denied access (403) — they should use /recommendations instead.
    """
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to access student insights",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Tutors must not see the student-framed insights endpoint.
    if current_user.role == "tutor":
        raise HTTPException(
            status_code=403,
            detail="Student insights are student-only content",
        )

    summary = _session_store().load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not summary.is_owner(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    return generate_student_insights(summary)


@router.get("/trends")
async def get_trends(
    tutor_id: str = "",
    last_n: int = 10,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Get cross-session trend data.

    Auth-aware behaviour:
    - Authenticated user → auto-scope to that user's sessions
    - Not authenticated → existing behaviour (explicit tutor_id param, or all sessions)
    """
    resolved_tutor_id: Optional[str] = None
    resolved_student_id: Optional[str] = None
    trend_scope_id: str = tutor_id

    if current_user is not None:
        if current_user.role == "student":
            resolved_student_id = current_user.id
            trend_scope_id = current_user.id
        else:
            resolved_tutor_id = current_user.id
            trend_scope_id = current_user.id
    else:
        resolved_tutor_id = tutor_id or None

    sessions = _session_store().list_sessions(
        tutor_id=resolved_tutor_id,
        student_user_id=resolved_student_id,
        last_n=last_n if last_n > 0 else None,
    )
    trend_data = compute_trends(trend_scope_id, sessions)
    return trend_data.model_dump()
