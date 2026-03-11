from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import mediapipe as mp
import sentry_sdk
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .livekit import (
    LiveKitConfigError,
    LiveKitWebhookAuthError,
    LiveKitWebhookPayloadError,
    apply_livekit_webhook_event,
    build_livekit_join_payload,
    default_media_provider,
    livekit_analytics_worker_enabled,
    verify_livekit_webhook,
)
from .models import MediaProvider, Role, SessionCreateRequest, SessionCreateResponse
from .session_manager import SessionRoom
from .session_manager import session_manager
from .ws import router as ws_router
from .analytics.router import router as analytics_router
from .auth.router import router as auth_router
from .auth.dependencies import get_optional_user
from .auth.models import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Sentry when a DSN is configured (no-op when empty)
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.sentry_environment,
            traces_sample_rate=0.1,
        )

    # Pre-load MediaPipe Face Mesh model on startup
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    app.state.face_mesh_warmup = True
    face_mesh.close()

    app.state.db_connected = None

    # Run retention cleanup on startup
    try:
        from .analytics.session_store import SessionStore
        store = SessionStore()
        deleted = store.cleanup_expired()
        if deleted > 0:
            import logging
            logging.getLogger(__name__).info(
                f"Retention cleanup: deleted {deleted} expired session(s)"
            )
    except Exception:
        pass  # Non-critical — don't block startup

    yield


app = FastAPI(
    title="Live Session Analysis",
    description="AI-Powered Real-Time Engagement Analysis for Video Tutoring",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(analytics_router, prefix="/api/analytics")
app.include_router(auth_router, prefix="/api/auth")


async def _check_db_connectivity() -> bool | None:
    """Return live database connectivity state.

    - ``None``: no database configured
    - ``True``: configured and reachable
    - ``False``: configured but unreachable
    """
    if not settings.database_url:
        return None

    try:
        from .db import get_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception:
        return False


def _health_payload(*, db_connected: bool | None) -> dict[str, object]:
    return {
        "status": "ok" if db_connected is not False else "degraded",
        "mediapipe_loaded": getattr(app.state, "face_mesh_warmup", False),
        "db_connected": db_connected,
        "db_configured": bool(settings.database_url),
        "storage_backend": settings.storage_backend,
        "trace_storage": settings.trace_storage_backend,
        "livekit_configured": bool(
            settings.livekit_url
            and settings.livekit_api_key
            and settings.livekit_api_secret
        ),
        "sentry_enabled": bool(settings.sentry_dsn),
    }


@app.get("/health")
async def health():
    """Fast liveness probe — returns 200 as long as the process is alive.

    No external I/O is performed here. ``db_connected`` reports the most recent
    readiness result cached on the app state, or ``null`` if no readiness check
    has run yet (or no database is configured).
    """
    cached_db_connected = getattr(app.state, "db_connected", None)
    if not settings.database_url:
        cached_db_connected = None
    return _health_payload(db_connected=cached_db_connected)


@app.get("/health/ready")
async def health_ready():
    """Deep readiness probe — tests actual database connectivity.

    Returns 200 when all required backends are reachable.
    Returns 503 when Postgres is configured but unreachable, so Fly.io (or
    any other orchestrator) can hold traffic until the app is truly ready.

    When ``database_url`` is not set the app is running in local/file-backed
    mode; ``db_connected`` is ``null`` (not applicable) and the check passes.
    """
    from fastapi.responses import JSONResponse

    db_connected = await _check_db_connectivity()
    app.state.db_connected = db_connected
    payload = _health_payload(db_connected=db_connected)

    if db_connected is False:
        return JSONResponse(status_code=503, content=payload)

    return payload


@app.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(
    body: Optional[SessionCreateRequest] = None,
    current_user: Optional[User] = Depends(get_optional_user),
):
    # If the caller is authenticated, their user ID is stored in the appropriate
    # field based on their role.  Students creating a session record themselves
    # in student_user_id; tutors (and admins) are recorded as tutor_id.
    # Unauthenticated clients fall back to the explicit body fields for backward compat.
    if current_user is not None and current_user.role == "student":
        # Authenticated student: bind student_user_id to their own identity.
        # Ignore body.tutor_id — an authenticated student cannot forge the tutor.
        student_user_id = current_user.id
        tutor_id = ""
    elif current_user is not None:
        # Authenticated tutor or admin: bind tutor_id to their own identity.
        # Ignore body.student_user_id — an authenticated tutor cannot forge the student.
        tutor_id = current_user.id
        student_user_id = ""
    else:
        # Unauthenticated: only honour the explicit tutor_id for backward compat.
        # Ignore body.student_user_id — accepting it from unauthenticated callers
        # would let guests forge student ownership of any session they create.
        tutor_id = body.tutor_id if body else ""
        student_user_id = ""
    session_type = body.session_type if body else "general"
    media_provider = body.media_provider if body and body.media_provider else default_media_provider()
    coaching_intensity = body.coaching_intensity.value if body and body.coaching_intensity else "normal"
    max_students = body.max_students if body else 1
    if media_provider == MediaProvider.LIVEKIT and not settings.enable_livekit:
        raise HTTPException(status_code=400, detail="LiveKit provider is not enabled")
    return session_manager.create_session(
        tutor_id=tutor_id,
        student_user_id=student_user_id,
        session_type=session_type,
        media_provider=media_provider,
        coaching_intensity=coaching_intensity,
        max_students=max_students,
    )


@app.get("/api/sessions/{session_id}/info")
async def session_info(session_id: str, token: str = ""):
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")
    resolved_role = room.get_role_for_token(token) if token else None
    return {
        "session_id": room.session_id,
        "tutor_connected": room.participants[Role.TUTOR].connected,
        "student_connected": any(
            participant.connected for _idx, participant in room.all_student_participants()
        ),
        "started": room.started_at is not None,
        "ended": room.ended_at is not None,
        "elapsed_seconds": room.elapsed_seconds(),
        "role": resolved_role.value if resolved_role else None,
        "media_provider": room.media_provider.value,
        "analytics_ingest_mode": (
            "livekit_worker"
            if livekit_analytics_worker_enabled(room)
            else "browser_upload"
        ),
        "livekit_room_name": room.livekit_room_name or None,
        "livekit": {
            "room_started": room.livekit_room_started_at is not None,
            "room_finished": room.livekit_room_ended_at is not None,
            "last_event": room.livekit_last_webhook_event,
            "tutor_joined": room.participants[Role.TUTOR].livekit_connected,
            "student_joined": any(
                participant.livekit_connected
                for _idx, participant in room.all_student_participants()
            ),
            "worker_started": room.livekit_worker_started_at is not None,
            "worker_connected": room.livekit_worker_connected_at is not None,
            "worker_last_error": room.livekit_worker_last_error,
        },
    }


@app.post("/api/sessions/{session_id}/livekit-token")
async def create_livekit_token(session_id: str, token: str = "", debug: str = ""):
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")

    role = room.get_role_for_token(token) if token else None
    if role is None:
        raise HTTPException(status_code=403, detail="Invalid token")
    if room.ended_at is not None:
        raise HTTPException(status_code=409, detail="Session already ended")

    student_index = room.get_student_index_for_token(token) if role == Role.STUDENT else 0

    # Enable debug mode when tutor requests token with ?debug=1
    if role == Role.TUTOR and debug == "1":
        room.debug_mode = True

    try:
        return build_livekit_join_payload(room, role, student_index=student_index or 0)
    except LiveKitConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/sessions/{session_id}/student-token")
async def allocate_student_token(session_id: str):
    """Allocate a LiveKit token for the next available student slot.

    This endpoint is intended for multi-student sessions where additional
    students (beyond the first, whose token is returned at session creation)
    need to join.  It iterates over the pre-generated student token list and
    returns the first slot whose participant has not yet connected.

    Returns:
        token: The app-level student token (used for WebSocket auth).
        student_index: Zero-based index of the allocated slot.
        livekit: LiveKit join payload dict (only present when the session
                 uses the LiveKit media provider and LiveKit is configured).
    """
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if room.ended_at is not None:
        raise HTTPException(status_code=409, detail="Session already ended")

    # Find the next student slot that has not yet connected.
    allocated_index: int | None = None
    allocated_token: str | None = None
    for idx, token in enumerate(room.student_tokens):
        participant = room.get_student_participant(idx)
        if not participant.connected:
            allocated_index = idx
            allocated_token = token
            break

    if allocated_index is None:
        raise HTTPException(
            status_code=409,
            detail=f"All {room.max_students} student slot(s) are already occupied",
        )

    response: dict = {
        "token": allocated_token,
        "student_index": allocated_index,
    }

    if room.media_provider == MediaProvider.LIVEKIT:
        try:
            response["livekit"] = build_livekit_join_payload(
                room, Role.STUDENT, student_index=allocated_index
            )
        except LiveKitConfigError:
            pass  # LiveKit not fully configured — omit the livekit key

    return response


@app.post("/api/livekit/webhooks")
async def livekit_webhook(request: Request):
    body = await request.body()
    authorization = request.headers.get("authorization")

    try:
        payload = verify_livekit_webhook(body, authorization)
        return apply_livekit_webhook_event(payload)
    except LiveKitWebhookAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except LiveKitWebhookPayloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LiveKitConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/sessions/{session_id}/end")
async def end_session(session_id: str, token: str = ""):
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")

    role = room.get_role_for_token(token) if token else None
    if role is None:
        raise HTTPException(status_code=403, detail="Invalid token")

    from .ws import _finalize_session

    already_ended = room.ended_at is not None
    if not already_ended:
        recorder = getattr(room, "trace_recorder", None)
        if recorder is not None:
            recorder.record_event(
                "session_end_requested",
                role=role.value,
                data={"source": "api"},
            )
        _finalize_session(room)

    return {
        "status": "already_ended" if already_ended else "ended",
        "session_id": room.session_id,
        "ended": True,
        "ended_by": role.value,
    }


@app.get("/api/debug/latency")
async def debug_latency(session_id: str = ""):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return room.get_latency_stats().model_dump()


@app.get("/api/debug/stats")
async def debug_stats(session_id: str = ""):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")
    room = session_manager.get_session(session_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Session not found")
    stats = room.get_latency_stats()
    return {
        **stats.model_dump(),
        "elapsed_seconds": room.elapsed_seconds(),
        "both_connected": room.both_connected(),
        "nudges_sent": len(room.nudges_sent),
        "metrics_snapshots": len(room.metrics_history),
    }
