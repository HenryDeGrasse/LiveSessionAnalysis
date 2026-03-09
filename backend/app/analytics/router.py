from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .session_store import SessionStore
from .recommendations import generate_recommendations
from .trends import compute_trends

router = APIRouter()
store = SessionStore()


@router.get("/sessions")
async def list_sessions(tutor_id: str = "", last_n: int = 0):
    """List all stored sessions with summary stats."""
    sessions = store.list_sessions(
        tutor_id=tutor_id or None,
        last_n=last_n if last_n > 0 else None,
    )
    return [s.model_dump() for s in sessions]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get full session detail with timeline."""
    summary = store.load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return summary.model_dump()


@router.get("/sessions/{session_id}/recommendations")
async def get_recommendations(session_id: str):
    """Get coaching recommendations for a session."""
    summary = store.load(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return generate_recommendations(summary)


@router.get("/trends")
async def get_trends(tutor_id: str = "", last_n: int = 10):
    """Get cross-session trend data.

    If tutor_id is omitted, compute trends across the most recent sessions
    in the store. This keeps the demo usable before tutor auth exists.
    """
    sessions = store.list_sessions(
        tutor_id=tutor_id or None,
        last_n=last_n if last_n > 0 else None,
    )
    trend_data = compute_trends(tutor_id, sessions)
    return trend_data.model_dump()
