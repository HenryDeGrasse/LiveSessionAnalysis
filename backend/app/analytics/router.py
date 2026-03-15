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
api_router = APIRouter()
# Test-override hook: several existing backend tests patch this module-level
# name directly. In normal runtime it stays ``None`` and the router resolves
# the configured singleton lazily via ``get_session_store()`` on each request.
store = None


def _session_store():
    return store or get_session_store()


def _serialize_session_summary(summary, *, include_transcript: bool = False) -> dict:
    """Convert a SessionSummary to an API payload.

    ``transcript_compact`` remains backend-only storage data. For detail views we
    expose a sanitized, UI-friendly ``transcript_segments`` array instead.
    """
    data = summary.model_dump()
    transcript_compact = data.pop("transcript_compact", None)

    utterances = []
    if isinstance(transcript_compact, dict):
        raw_utterances = transcript_compact.get("utterances")
        if isinstance(raw_utterances, list):
            utterances = [u for u in raw_utterances if isinstance(u, dict)]

    data["transcript_available"] = bool(utterances) or bool(data.get("transcript_word_count", 0))

    if include_transcript and utterances:
        data["transcript_segments"] = [
            {
                "utterance_id": item.get("utterance_id", ""),
                "role": item.get("role", "student"),
                "text": item.get("text", ""),
                "start_time": float(item.get("start_time", 0.0) or 0.0),
                "end_time": float(item.get("end_time", 0.0) or 0.0),
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "sentiment": item.get("sentiment"),
                "student_index": int(item.get("student_index", 0) or 0),
            }
            for item in utterances
            if item.get("text")
        ]

    return data


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
    return [
        _serialize_session_summary(summary, include_transcript=False)
        for summary in sessions
    ]


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

    data = _serialize_session_summary(summary, include_transcript=True)

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
    return _serialize_session_summary(summary, include_transcript=True)


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


async def _delete_transcript_impl(
    session_id: str,
    current_user: Optional[User],
):
    """Delete transcript data for a session (Postgres + S3)."""
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to delete transcript data",
            headers={"WWW-Authenticate": "Bearer"},
        )

    summary = _session_store().load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not summary.is_owner(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    store = _session_store()
    pg_cleared = False
    s3_key_deleted: str | None = None

    # 1. Clear transcript/enrichment data from the configured session store.
    if hasattr(store, "clear_transcript_data"):
        pg_cleared = store.clear_transcript_data(session_id)
    else:
        summary.transcript_compact = None
        summary.transcript_word_count = 0
        summary.transcript_available = False
        summary.ai_summary = None
        summary.topics_covered = []
        summary.student_understanding_map = {}
        summary.key_moments = []
        summary.uncertainty_timeline = []
        summary.follow_up_recommendations = []
        store.save(summary)
        pg_cleared = True

    # 2. Delete transcript artifact from S3/R2 when trace storage uses S3.
    try:
        from ..config import settings as _settings

        if _settings.trace_storage_backend == "s3":
            from ..observability import get_trace_store

            trace_store = get_trace_store()
            s3_key = f"{trace_store._prefix}transcripts/{session_id}.json"
            try:
                trace_store._client.delete_object(
                    Bucket=trace_store._bucket,
                    Key=s3_key,
                )
                s3_key_deleted = s3_key
                logger.info(
                    "Deleted S3 transcript artifact for session %s: %s",
                    session_id,
                    s3_key,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to delete S3 transcript for session %s: %s",
                    session_id,
                    exc,
                )
    except Exception as exc:
        logger.warning(
            "S3 transcript deletion skipped for session %s: %s",
            session_id,
            exc,
        )

    # 3. Audit log with who/when/what was deleted.
    if hasattr(store, "log_transcript_deletion"):
        store.log_transcript_deletion(
            session_id,
            current_user.id,
            s3_key_deleted=s3_key_deleted,
            pg_cleared=pg_cleared,
        )
    else:
        logger.info(
            "Transcript deletion audit: session=%s user=%s pg_cleared=%s s3_key=%s",
            session_id,
            current_user.id,
            pg_cleared,
            s3_key_deleted,
        )

    return None


@router.delete("/sessions/{session_id}/transcript", status_code=204)
@api_router.delete("/sessions/{session_id}/transcript", status_code=204)
async def delete_transcript(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Delete transcript data for a session (Postgres + S3).

    Exposed at both ``/api/analytics/sessions/{id}/transcript`` and
    ``/api/sessions/{id}/transcript`` for compatibility with the step spec and
    existing analytics routes.
    """
    return await _delete_transcript_impl(session_id, current_user)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Delete a session.

    Only the session owner (tutor or student) can delete it.
    Returns 204 No Content on success.
    """
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required to delete a session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    summary = _session_store().load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if not summary.is_owner(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    _session_store().delete(session_id)
    return None


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
