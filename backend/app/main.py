from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import mediapipe as mp
from fastapi import FastAPI, HTTPException, Request
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
from .session_manager import session_manager
from .ws import router as ws_router
from .analytics.router import router as analytics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-load MediaPipe Face Mesh model on startup
    face_mesh = mp.solutions.face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    app.state.face_mesh_warmup = True
    face_mesh.close()

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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mediapipe_loaded": getattr(app.state, "face_mesh_warmup", False),
    }


@app.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(body: Optional[SessionCreateRequest] = None):
    tutor_id = body.tutor_id if body else ""
    session_type = body.session_type if body else "general"
    media_provider = body.media_provider if body and body.media_provider else default_media_provider()
    if media_provider == MediaProvider.LIVEKIT and not settings.enable_livekit:
        raise HTTPException(status_code=400, detail="LiveKit provider is not enabled")
    return session_manager.create_session(
        tutor_id=tutor_id,
        session_type=session_type,
        media_provider=media_provider,
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
        "student_connected": room.participants[Role.STUDENT].connected,
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
            "student_joined": room.participants[Role.STUDENT].livekit_connected,
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

    # Enable debug mode when tutor requests token with ?debug=1
    if role == Role.TUTOR and debug == "1":
        room.debug_mode = True

    try:
        return build_livekit_join_payload(room, role)
    except LiveKitConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
