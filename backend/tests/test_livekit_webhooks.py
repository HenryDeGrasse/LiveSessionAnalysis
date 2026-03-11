from __future__ import annotations

import hashlib
import json
import time

import jwt

from app.config import settings
from app.livekit import livekit_identity, livekit_role_for_identity
from app.models import Role
from app.session_manager import session_manager


def _configure_livekit(monkeypatch):
    monkeypatch.setattr(settings, "enable_livekit", True)
    monkeypatch.setattr(settings, "livekit_url", "ws://127.0.0.1:7880")
    monkeypatch.setattr(settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(settings, "livekit_api_secret", "secret")


def _signed_webhook(payload: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": settings.livekit_api_key,
            "nbf": now - 5,
            "exp": now + 60,
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        settings.livekit_api_secret,
        algorithm="HS256",
    )
    return body, {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def test_livekit_token_rejects_ended_session(client, monkeypatch):
    _configure_livekit(monkeypatch)

    create = client.post("/api/sessions", json={"media_provider": "livekit"})
    assert create.status_code == 200
    data = create.json()

    end = client.post(
        f"/api/sessions/{data['session_id']}/end?token={data['tutor_token']}"
    )
    assert end.status_code == 200

    token_resp = client.post(
        f"/api/sessions/{data['session_id']}/livekit-token?token={data['tutor_token']}"
    )
    assert token_resp.status_code == 409
    assert token_resp.json()["detail"] == "Session already ended"



def test_livekit_webhook_rejects_bad_signature(client, monkeypatch):
    _configure_livekit(monkeypatch)

    response = client.post(
        "/api/livekit/webhooks",
        content=json.dumps(
            {
                "id": "evt-bad",
                "event": "room_started",
                "room": {"name": "lsa-test"},
            }
        ),
        headers={
            "Authorization": "Bearer definitely-not-valid",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401



def test_livekit_webhook_updates_room_participant_and_track_state(client, monkeypatch):
    _configure_livekit(monkeypatch)

    create = client.post("/api/sessions", json={"media_provider": "livekit"})
    assert create.status_code == 200
    data = create.json()

    room = session_manager.get_session(data["session_id"])
    assert room is not None

    events = [
        {
            "id": "evt-room-started",
            "event": "room_started",
            "room": {"name": data["livekit_room_name"]},
        },
        {
            "id": "evt-tutor-joined",
            "event": "participant_joined",
            "room": {"name": data["livekit_room_name"]},
            "participant": {"identity": f"{data['session_id']}:tutor"},
        },
        {
            "id": "evt-tutor-track",
            "event": "track_published",
            "room": {"name": data["livekit_room_name"]},
            "participant": {"identity": f"{data['session_id']}:tutor"},
            "track": {"sid": "TR_CAM_1", "source": "CAMERA", "type": "VIDEO"},
        },
        {
            "id": "evt-student-joined",
            "event": "participant_joined",
            "room": {"name": data["livekit_room_name"]},
            "participant": {"identity": f"{data['session_id']}:student"},
        },
        {
            "id": "evt-tutor-left",
            "event": "participant_left",
            "room": {"name": data["livekit_room_name"]},
            "participant": {"identity": f"{data['session_id']}:tutor"},
        },
        {
            "id": "evt-room-finished",
            "event": "room_finished",
            "room": {"name": data["livekit_room_name"]},
        },
    ]

    for event in events:
        body, headers = _signed_webhook(event)
        response = client.post("/api/livekit/webhooks", content=body, headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "processed"
        assert payload["session_id"] == data["session_id"]
        assert payload["event"] == event["event"]

    assert room.livekit_room_started_at is not None
    assert room.livekit_room_ended_at is not None
    assert room.livekit_last_webhook_event == "room_finished"
    assert room.participants[Role.TUTOR].livekit_identity == f"{data['session_id']}:tutor"
    assert room.participants[Role.STUDENT].livekit_identity == (
        f"{data['session_id']}:student"
    )
    assert room.participants[Role.TUTOR].livekit_connected is False
    assert room.participants[Role.STUDENT].livekit_connected is True
    assert room.participants[Role.TUTOR].livekit_published_tracks == set()
    assert room.participants[Role.STUDENT].livekit_published_tracks == set()



def test_livekit_webhook_is_idempotent(client, monkeypatch):
    _configure_livekit(monkeypatch)

    create = client.post("/api/sessions", json={"media_provider": "livekit"})
    assert create.status_code == 200
    data = create.json()

    room = session_manager.get_session(data["session_id"])
    assert room is not None

    event = {
        "id": "evt-duplicate",
        "event": "participant_joined",
        "room": {"name": data["livekit_room_name"]},
        "participant": {"identity": f"{data['session_id']}:tutor"},
    }
    body, headers = _signed_webhook(event)

    first = client.post("/api/livekit/webhooks", content=body, headers=headers)
    second = client.post("/api/livekit/webhooks", content=body, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert room.participants[Role.TUTOR].livekit_connected is True
    assert "evt-duplicate" in room.livekit_webhook_event_ids


def test_livekit_identity_for_multi_students():
    """livekit_identity with student_index=2 produces '{sid}:student:2'."""
    sid = "test-session-abc"
    assert livekit_identity(sid, Role.STUDENT, student_index=0) == f"{sid}:student:0"
    assert livekit_identity(sid, Role.STUDENT, student_index=2) == f"{sid}:student:2"
    # Tutor has no index suffix
    assert livekit_identity(sid, Role.TUTOR) == f"{sid}:tutor"


def test_livekit_role_for_identity_multi_students():
    """livekit_role_for_identity returns (Role.STUDENT, 1) for '{sid}:student:1'."""
    sid = "test-session-xyz"
    result = livekit_role_for_identity(sid, f"{sid}:student:1")
    assert result == (Role.STUDENT, 1)

    result_2 = livekit_role_for_identity(sid, f"{sid}:student:2")
    assert result_2 == (Role.STUDENT, 2)

    # Tutor returns (Role.TUTOR, 0)
    tutor_result = livekit_role_for_identity(sid, f"{sid}:tutor")
    assert tutor_result == (Role.TUTOR, 0)

    # Unknown session returns None
    assert livekit_role_for_identity(sid, "other-session:student:1") is None


def test_webhook_participant_joined_extra_student(client, monkeypatch):
    """A participant_joined webhook for identity '{sid}:student:1' updates extra_student_participants."""
    _configure_livekit(monkeypatch)

    create = client.post(
        "/api/sessions",
        json={"media_provider": "livekit", "max_students": 2},
    )
    assert create.status_code == 200
    data = create.json()
    sid = data["session_id"]

    room = session_manager.get_session(sid)
    assert room is not None
    assert 1 in room.extra_student_participants

    event = {
        "id": "evt-extra-student-joined",
        "event": "participant_joined",
        "room": {"name": data["livekit_room_name"]},
        "participant": {"identity": f"{sid}:student:1"},
    }
    body, headers = _signed_webhook(event)
    response = client.post("/api/livekit/webhooks", content=body, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processed"

    # Extra student participant (index 1) should now show as livekit_connected
    extra = room.extra_student_participants[1]
    assert extra.livekit_connected is True
    assert extra.livekit_identity == f"{sid}:student:1"

    # Primary student (index 0) should be unaffected
    assert room.participants[Role.STUDENT].livekit_connected is False
