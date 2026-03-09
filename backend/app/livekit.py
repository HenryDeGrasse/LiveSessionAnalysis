from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

import jwt

from .config import settings
from .models import MediaProvider, Role
from .session_manager import SessionRoom, session_manager


class LiveKitConfigError(RuntimeError):
    pass


class LiveKitWebhookAuthError(RuntimeError):
    pass


class LiveKitWebhookPayloadError(RuntimeError):
    pass


def default_media_provider() -> MediaProvider:
    raw = settings.default_media_provider.strip().lower()
    if raw == MediaProvider.LIVEKIT.value:
        return MediaProvider.LIVEKIT
    return MediaProvider.CUSTOM_WEBRTC



def livekit_enabled() -> bool:
    return (
        settings.enable_livekit
        and bool(settings.livekit_url)
        and bool(settings.livekit_api_key)
        and bool(settings.livekit_api_secret)
    )



def livekit_analytics_worker_enabled(room: SessionRoom | None = None) -> bool:
    if not livekit_enabled() or not settings.enable_livekit_analytics_worker:
        return False
    if room is not None and room.media_provider != MediaProvider.LIVEKIT:
        return False
    return True



def livekit_room_name_for_session(session_id: str) -> str:
    return f"{settings.livekit_room_prefix}-{session_id}"



def livekit_identity(session_id: str, role: Role) -> str:
    return f"{session_id}:{role.value}"



def livekit_worker_identity(session_id: str) -> str:
    return f"worker:{session_id}"



def livekit_role_for_identity(session_id: str, identity: str) -> Role | None:
    prefix = f"{session_id}:"
    if not identity.startswith(prefix):
        return None

    suffix = identity[len(prefix):]
    if suffix == Role.TUTOR.value:
        return Role.TUTOR
    if suffix == Role.STUDENT.value:
        return Role.STUDENT
    return None



def build_livekit_join_payload(room: SessionRoom, role: Role) -> dict[str, Any]:
    if room.media_provider != MediaProvider.LIVEKIT:
        raise LiveKitConfigError("Session is not configured for LiveKit")

    if not livekit_enabled():
        raise LiveKitConfigError("LiveKit is not configured")

    room_name = room.livekit_room_name or livekit_room_name_for_session(room.session_id)
    now = int(time.time())
    exp = now + settings.livekit_token_ttl_seconds

    token = jwt.encode(
        {
            "iss": settings.livekit_api_key,
            "sub": livekit_identity(room.session_id, role),
            "nbf": now - 5,
            "exp": exp,
            "name": role.value,
            "metadata": json.dumps(
                {
                    "session_id": room.session_id,
                    "role": role.value,
                    "tutor_id": room.tutor_id,
                    "session_type": room.session_type,
                }
            ),
            "video": {
                "roomJoin": True,
                "room": room_name,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            },
        },
        settings.livekit_api_secret,
        algorithm="HS256",
    )

    return {
        "url": settings.livekit_url,
        "room_name": room_name,
        "identity": livekit_identity(room.session_id, role),
        "token": token,
        "expires_at": exp,
    }



def build_livekit_worker_join_payload(room: SessionRoom) -> dict[str, Any]:
    if room.media_provider != MediaProvider.LIVEKIT:
        raise LiveKitConfigError("Session is not configured for LiveKit")

    if not livekit_analytics_worker_enabled(room):
        raise LiveKitConfigError("LiveKit analytics worker is not configured")

    room_name = room.livekit_room_name or livekit_room_name_for_session(room.session_id)
    identity = livekit_worker_identity(room.session_id)
    now = int(time.time())
    exp = now + settings.livekit_token_ttl_seconds

    token = jwt.encode(
        {
            "iss": settings.livekit_api_key,
            "sub": identity,
            "nbf": now - 5,
            "exp": exp,
            "name": "analytics-worker",
            "metadata": json.dumps(
                {
                    "session_id": room.session_id,
                    "role": "worker",
                    "tutor_id": room.tutor_id,
                    "session_type": room.session_type,
                }
            ),
            "video": {
                "roomJoin": True,
                "room": room_name,
                "canPublish": False,
                "canSubscribe": True,
                "canPublishData": True,
                "hidden": True,
                "agent": True,
            },
        },
        settings.livekit_api_secret,
        algorithm="HS256",
    )

    return {
        "url": settings.livekit_url,
        "room_name": room_name,
        "identity": identity,
        "token": token,
        "expires_at": exp,
    }



def _strip_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        return ""

    value = authorization.strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value



def _webhook_body_hashes(body: bytes) -> set[str]:
    digest = hashlib.sha256(body).digest()
    return {
        digest.hex(),
        base64.b64encode(digest).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    }



def verify_livekit_webhook(body: bytes, authorization: str | None) -> dict[str, Any]:
    if not livekit_enabled():
        raise LiveKitConfigError("LiveKit is not configured")

    token = _strip_bearer_token(authorization)
    if not token:
        raise LiveKitWebhookAuthError("Missing LiveKit webhook authorization")

    try:
        claims = jwt.decode(
            token,
            settings.livekit_api_secret,
            algorithms=["HS256"],
            issuer=settings.livekit_api_key,
            options={"require": ["iss", "exp", "nbf", "sha256"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise LiveKitWebhookAuthError("Invalid LiveKit webhook signature") from exc

    body_hash = claims.get("sha256")
    if body_hash not in _webhook_body_hashes(body):
        raise LiveKitWebhookAuthError("LiveKit webhook body hash mismatch")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveKitWebhookPayloadError("Invalid LiveKit webhook payload") from exc

    if not isinstance(payload, dict):
        raise LiveKitWebhookPayloadError("Invalid LiveKit webhook payload")

    return payload



def _event_timestamp(payload: dict[str, Any]) -> float:
    raw = payload.get("createdAt", payload.get("created_at"))
    if not isinstance(raw, (int, float)):
        return time.time()

    value = float(raw)
    if value > 1e17:
        value /= 1e9
    elif value > 1e14:
        value /= 1e6
    elif value > 1e11:
        value /= 1e3
    return value



def _track_sid(payload: dict[str, Any]) -> str:
    track = payload.get("track")
    if not isinstance(track, dict):
        return ""

    sid = track.get("sid")
    return sid if isinstance(sid, str) else ""



def apply_livekit_webhook_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_name = payload.get("event")
    room_payload = payload.get("room")

    if not isinstance(event_name, str) or not event_name:
        raise LiveKitWebhookPayloadError("Webhook payload missing event")
    if not isinstance(room_payload, dict):
        raise LiveKitWebhookPayloadError("Webhook payload missing room")

    room_name = room_payload.get("name")
    if not isinstance(room_name, str) or not room_name:
        raise LiveKitWebhookPayloadError("Webhook payload missing room name")

    room = session_manager.get_session_by_livekit_room(room_name)
    if room is None:
        return {
            "status": "ignored",
            "reason": "unknown_room",
            "event": event_name,
            "room_name": room_name,
        }

    event_id = payload.get("id")
    if isinstance(event_id, str) and event_id:
        if event_id in room.livekit_webhook_event_ids:
            return {
                "status": "duplicate",
                "session_id": room.session_id,
                "event": event_name,
            }
        room.livekit_webhook_event_ids.add(event_id)

    event_at = _event_timestamp(payload)
    room.livekit_last_webhook_event = event_name
    room.livekit_last_webhook_at = event_at

    participant_payload = payload.get("participant")
    participant_identity = (
        participant_payload.get("identity", "")
        if isinstance(participant_payload, dict)
        else ""
    )
    role = (
        livekit_role_for_identity(room.session_id, participant_identity)
        if participant_identity
        else None
    )
    participant = room.participants[role] if role is not None else None

    if participant is not None:
        participant.livekit_identity = participant_identity

    if event_name == "room_started":
        room.livekit_room_started_at = room.livekit_room_started_at or event_at
    elif event_name == "room_finished":
        room.livekit_room_ended_at = room.livekit_room_ended_at or event_at
    elif participant is not None and event_name == "participant_joined":
        participant.livekit_connected = True
        participant.livekit_last_joined_at = event_at
    elif participant is not None and event_name == "participant_left":
        participant.livekit_connected = False
        participant.livekit_last_left_at = event_at
        participant.livekit_published_tracks.clear()
    elif participant is not None and event_name == "track_published":
        track_sid = _track_sid(payload)
        if track_sid:
            participant.livekit_published_tracks.add(track_sid)
    elif participant is not None and event_name == "track_unpublished":
        track_sid = _track_sid(payload)
        if track_sid:
            participant.livekit_published_tracks.discard(track_sid)

    recorder = getattr(room, "trace_recorder", None)
    if recorder is not None:
        recorder.record_event(
            "livekit_webhook",
            data={
                "event": event_name,
                "event_id": event_id if isinstance(event_id, str) else None,
                "room_name": room_name,
                "participant_identity": participant_identity or None,
                "role": role.value if role is not None else None,
                "track_sid": _track_sid(payload) or None,
            },
        )

    if event_name in {"participant_joined", "track_published", "room_started"}:
        try:
            from .livekit_worker import maybe_start_livekit_analytics_worker

            maybe_start_livekit_analytics_worker(room)
        except Exception:
            pass

    return {
        "status": "processed",
        "session_id": room.session_id,
        "event": event_name,
    }
