from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from .config import settings
from .livekit import livekit_analytics_worker_enabled
from .models import Role
from .session_manager import SessionRoom, session_manager
from .session_runtime import (
    cleanup_resources as _cleanup_resources,
    finalize_session as _finalize_session,
    metrics_emit_loop as _metrics_emit_loop,
    process_audio_chunk as _process_audio_chunk,
    process_video_frame_bytes as _process_video_frame,
    trace_recorder as _trace_recorder,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _browser_analytics_ingest_enabled(room: SessionRoom) -> bool:
    return not livekit_analytics_worker_enabled(room)


def _participant_key(role: Role, student_index: int = 0) -> str:
    if role == Role.TUTOR:
        return role.value
    return f"student:{student_index}"


def _participant_for(room: SessionRoom, role: Role, student_index: int = 0):
    if role == Role.STUDENT:
        return room.get_student_participant(student_index)
    return room.participants[role]


async def _grace_period_finalize(room: SessionRoom, role: Role, student_index: int = 0):
    """Wait for reconnect grace period, then finalize if still disconnected."""
    try:
        await asyncio.sleep(settings.reconnect_grace_seconds)
        participant = _participant_for(room, role, student_index)
        if not participant.connected and room.ended_at is None:
            if not room.any_connected():
                logger.info(
                    f"Session {room.session_id}: grace period expired for "
                    f"{_participant_key(role, student_index)}, no participants connected — finalizing"
                )
                _finalize_session(room)
            else:
                logger.info(
                    f"Session {room.session_id}: {_participant_key(role, student_index)} "
                    "did not reconnect, but other participant still connected"
                )
    except asyncio.CancelledError:
        pass


async def _send_json_to_participant(participant, message_type: str, data: dict):
    if participant.connected and participant.websocket:
        try:
            await participant.websocket.send_json({
                "type": message_type,
                "data": data,
            })
        except Exception:
            pass


async def _send_json_to_role(
    room: SessionRoom,
    role: Role,
    message_type: str,
    data: dict,
    *,
    student_index: int = 0,
):
    await _send_json_to_participant(
        _participant_for(room, role, student_index),
        message_type,
        data,
    )


async def _send_json_to_other_participants(
    room: SessionRoom,
    source_role: Role,
    message_type: str,
    data: dict,
    *,
    source_student_index: int = 0,
):
    source_key = _participant_key(source_role, source_student_index)
    if source_key != Role.TUTOR.value:
        await _send_json_to_role(room, Role.TUTOR, message_type, data)
    for student_index, participant in room.all_student_participants():
        if _participant_key(Role.STUDENT, student_index) == source_key:
            continue
        await _send_json_to_participant(participant, message_type, data)


async def _broadcast_json(room: SessionRoom, message_type: str, data: dict):
    await _send_json_to_role(room, Role.TUTOR, message_type, data)
    for _student_index, participant in room.all_student_participants():
        await _send_json_to_participant(participant, message_type, data)


async def _handle_text_message(
    room: SessionRoom,
    role: Role,
    text: str,
    *,
    student_index: int = 0,
):
    """Handle JSON control messages on the session websocket.

    Text frames are reserved for signaling/control. Binary frames continue to carry
    analytics media payloads.
    """
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return

    message_type = message.get("type")
    data = message.get("data") or {}

    if message_type == "user_auth":
        # First-message user authentication over the WebSocket.
        # The client sends its JWT here rather than as a query parameter to
        # avoid leaking credentials into server logs and browser history.
        access_token = data.get("access_token", "")
        if access_token:
            try:
                from .auth import get_user_store
                from .auth.jwt_utils import decode_access_token

                payload = decode_access_token(access_token)
                user_id = payload.get("sub", "")
                if user_id:
                    # Verify the user actually exists in the configured user store
                    # so WebSocket auth follows the same backend-selection logic as
                    # HTTP auth dependencies (SQLite locally, Postgres in production).
                    user_store = get_user_store()
                    user = await asyncio.get_event_loop().run_in_executor(
                        None, user_store.get_by_id, user_id
                    )
                    if user is None:
                        logger.warning(
                            f"Session {room.session_id}: user_auth rejected for "
                            f"{role.value} — user {user_id!r} not found in DB"
                        )
                    else:
                        participant = _participant_for(room, role, student_index)
                        participant.user_id = user_id
                        # For students, propagate the first authenticated student's
                        # user ID to the room-level summary field for backward compatibility.
                        if role == Role.STUDENT and student_index == 0:
                            room.student_user_id = user_id
                        logger.info(
                            f"Session {room.session_id}: {role.value} authenticated as user {user_id}"
                        )
            except Exception as exc:
                logger.warning(
                    f"Session {room.session_id}: user_auth failed for {role.value}: {exc}"
                )
        return

    if message_type == "client_status":
        participant = _participant_for(room, role, student_index)
        if "audio_muted" in data:
            participant.audio_muted = bool(data["audio_muted"])
        if "video_enabled" in data:
            participant.video_enabled = bool(data["video_enabled"])
        if "tab_hidden" in data:
            participant.tab_hidden = bool(data["tab_hidden"])
        return

    # webrtc_signal relay removed — LiveKit handles all media transport.


@router.websocket("/ws/session/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
    debug: str = Query(""),
):
    room = session_manager.get_session(session_id)
    if room is None:
        await websocket.close(code=4004, reason="Session not found")
        return

    role = room.get_role_for_token(token)
    if role is None:
        await websocket.close(code=4001, reason="Invalid token")
        return

    student_index = room.get_student_index_for_token(token) if role == Role.STUDENT else 0
    participant = _participant_for(room, role, student_index)

    if participant.connected:
        old_ws = participant.websocket
        logger.warning(
            f"Session {session_id}: {_participant_key(role, student_index)} forced takeover — "
            "closing stale connection and accepting new one"
        )
        # Detach participant from old socket before closing it, so the old
        # handler's finally block sees a different websocket and skips cleanup.
        participant.websocket = None
        participant.connected = False
        if old_ws is not None:
            async def _close_stale(ws=old_ws):
                try:
                    await ws.close(code=4002, reason="Replaced by new connection")
                except Exception:
                    pass
            asyncio.create_task(_close_stale())

    if room.ended_at is not None:
        await websocket.close(code=4003, reason="Session already ended")
        return

    was_reconnecting = participant.disconnected_at is not None

    # Enable debug mode when tutor connects with ?debug=1
    if role == Role.TUTOR and debug == "1":
        room.debug_mode = True

    await websocket.accept()
    participant.websocket = websocket
    participant.connected = True
    participant.disconnected_at = None
    participant.last_speech_update = time.time()

    participant_key = _participant_key(role, student_index)
    room.cancel_grace_task(participant_key)

    logger.info(f"Session {session_id}: {participant_key} connected")
    recorder = _trace_recorder(room)
    if recorder is not None:
        recorder.record_event(
            f"{role.value}_connected",
            role=role.value,
            data={"student_index": student_index if role == Role.STUDENT else None},
        )

    if was_reconnecting:
        await _send_json_to_other_participants(
            room,
            role,
            "participant_reconnected",
            {
                "role": role.value,
                "session_id": session_id,
                "student_index": student_index if role == Role.STUDENT else None,
            },
            source_student_index=student_index,
        )
        if recorder is not None:
            recorder.record_event(
                "participant_reconnected",
                role=role.value,
                data={"session_id": session_id},
            )

    if room.both_connected():
        if room.started_at is None:
            room.started_at = time.time()
            if recorder is not None:
                recorder.mark_started()
            logger.info(f"Session {session_id}: both participants connected, analysis started")
            room._metrics_task = asyncio.create_task(_metrics_emit_loop(room))
            if livekit_analytics_worker_enabled(room):
                try:
                    from .livekit_worker import maybe_start_livekit_analytics_worker

                    maybe_start_livekit_analytics_worker(room)
                except Exception:
                    pass

        ready_payload = {
            "role": role.value,
            "session_id": session_id,
            "reconnected": was_reconnecting,
            "student_index": student_index if role == Role.STUDENT else None,
        }
        if recorder is not None:
            recorder.record_event(
                "participant_ready",
                role=role.value,
                data=ready_payload,
            )
        await _broadcast_json(room, "participant_ready", ready_payload)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()

            data = message.get("bytes")
            if data is not None:
                if len(data) < 2:
                    continue
                if not _browser_analytics_ingest_enabled(room):
                    continue

                msg_type = data[0]
                payload = data[1:]

                if msg_type == 0x01:
                    await _process_video_frame(
                        room, role, payload, student_index=student_index
                    )
                elif msg_type == 0x02:
                    await _process_audio_chunk(
                        room, role, payload, student_index=student_index
                    )
                continue

            text = message.get("text")
            if text is not None:
                await _handle_text_message(
                    room,
                    role,
                    text,
                    student_index=student_index,
                )
                continue

    except WebSocketDisconnect:
        logger.info(f"Session {session_id}: {participant_key} disconnected")
    except Exception as exc:
        logger.error(f"Session {session_id}: error for {participant_key}: {exc}")
    finally:
        # Identity guard: only clean up state if this websocket is still the
        # current one for this participant.  During a forced takeover the new
        # handler sets participant.websocket to None (and later to the new ws)
        # *before* closing the old socket, so when this finally block runs for
        # the old handler participant.websocket is no longer our websocket — we
        # must skip cleanup to avoid clobbering the replacement connection.
        if participant.websocket is not websocket:
            logger.debug(
                f"Session {session_id}: {participant_key} stale handler cleanup skipped "
                "(participant already taken over by new connection)"
            )
            return

        participant.connected = False
        participant.websocket = None
        participant.disconnected_at = time.time()

        if room.started_at is not None and room.ended_at is None:
            disconnect_payload = {
                "role": role.value,
                "session_id": session_id,
                "grace_seconds": settings.reconnect_grace_seconds,
                "student_index": student_index if role == Role.STUDENT else None,
            }
            recorder = _trace_recorder(room)
            if recorder is not None:
                recorder.record_event(
                    "participant_disconnected",
                    role=role.value,
                    data=disconnect_payload,
                )

            grace_task = asyncio.create_task(
                _grace_period_finalize(room, role, student_index)
            )
            room._grace_tasks[participant_key] = grace_task

            await _send_json_to_other_participants(
                room,
                role,
                "participant_disconnected",
                disconnect_payload,
                source_student_index=student_index,
            )
