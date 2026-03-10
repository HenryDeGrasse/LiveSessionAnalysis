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


async def _grace_period_finalize(room: SessionRoom, role: Role):
    """Wait for reconnect grace period, then finalize if still disconnected."""
    try:
        await asyncio.sleep(settings.reconnect_grace_seconds)
        participant = room.participants[role]
        if not participant.connected and room.ended_at is None:
            if not room.any_connected():
                logger.info(
                    f"Session {room.session_id}: grace period expired for {role.value}, "
                    "no participants connected — finalizing"
                )
                _finalize_session(room)
            else:
                logger.info(
                    f"Session {room.session_id}: {role.value} did not reconnect, "
                    "but other participant still connected"
                )
    except asyncio.CancelledError:
        pass


def _opposite_role(role: Role) -> Role:
    return Role.STUDENT if role == Role.TUTOR else Role.TUTOR


async def _send_json_to_role(
    room: SessionRoom,
    role: Role,
    message_type: str,
    data: dict,
):
    participant = room.participants[role]
    if participant.connected and participant.websocket:
        try:
            await participant.websocket.send_json({
                "type": message_type,
                "data": data,
            })
        except Exception:
            pass


async def _send_json_to_other_participant(
    room: SessionRoom,
    source_role: Role,
    message_type: str,
    data: dict,
):
    await _send_json_to_role(room, _opposite_role(source_role), message_type, data)


async def _broadcast_json(room: SessionRoom, message_type: str, data: dict):
    for role in (Role.TUTOR, Role.STUDENT):
        await _send_json_to_role(room, role, message_type, data)


async def _handle_text_message(room: SessionRoom, role: Role, text: str):
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

    if message_type == "client_status":
        participant = room.participants[role]
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

    participant = room.participants[role]

    if participant.connected:
        await websocket.close(code=4002, reason="Role already connected")
        return

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

    room.cancel_grace_task(role)

    logger.info(f"Session {session_id}: {role.value} connected")
    recorder = _trace_recorder(room)
    if recorder is not None:
        recorder.record_event(f"{role.value}_connected", role=role.value)

    if was_reconnecting:
        await _send_json_to_other_participant(
            room,
            role,
            "participant_reconnected",
            {
                "role": role.value,
                "session_id": session_id,
            },
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
                    await _process_video_frame(room, role, payload)
                elif msg_type == 0x02:
                    await _process_audio_chunk(room, role, payload)
                continue

            text = message.get("text")
            if text is not None:
                await _handle_text_message(room, role, text)
                continue

    except WebSocketDisconnect:
        logger.info(f"Session {session_id}: {role.value} disconnected")
    except Exception as exc:
        logger.error(f"Session {session_id}: error for {role.value}: {exc}")
    finally:
        participant.connected = False
        participant.websocket = None
        participant.disconnected_at = time.time()

        if room.started_at is not None and room.ended_at is None:
            disconnect_payload = {
                "role": role.value,
                "session_id": session_id,
                "grace_seconds": settings.reconnect_grace_seconds,
            }
            recorder = _trace_recorder(room)
            if recorder is not None:
                recorder.record_event(
                    "participant_disconnected",
                    role=role.value,
                    data=disconnect_payload,
                )

            grace_task = asyncio.create_task(_grace_period_finalize(room, role))
            room._grace_tasks[role.value] = grace_task

            await _send_json_to_other_participant(
                room,
                role,
                "participant_disconnected",
                disconnect_payload,
            )
