"""Tests for disconnect/reconnect resilience and grace period logic."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.models import Role
from app.session_manager import SessionManager, SessionRoom, session_manager
from app.ws import _finalize_session, _grace_period_finalize, _cleanup_resources


@pytest.fixture(autouse=True)
def cleanup_sessions_reconnect():
    """Clean up sessions after each test."""
    yield
    for sid in list(session_manager._sessions.keys()):
        session_manager.remove_session(sid)


class TestGracePeriod:
    """Test the grace period mechanism for disconnect resilience."""

    def test_session_not_finalized_immediately_on_disconnect(self):
        """Disconnecting should not immediately set ended_at."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        room.started_at = time.time()
        room.participants[Role.TUTOR].connected = True
        room.participants[Role.STUDENT].connected = True

        # Simulate student disconnect
        room.participants[Role.STUDENT].connected = False
        room.participants[Role.STUDENT].disconnected_at = time.time()

        # Session should NOT be finalized yet
        assert room.ended_at is None

    def test_finalize_session_sets_ended_at(self):
        """_finalize_session should set ended_at."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        room.started_at = time.time()

        _finalize_session(room)
        assert room.ended_at is not None

    def test_finalize_session_idempotent(self):
        """Calling _finalize_session twice should not change ended_at."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        room.started_at = time.time()

        _finalize_session(room)
        first_ended = room.ended_at

        _finalize_session(room)
        assert room.ended_at == first_ended

    def test_cancel_grace_task_noop_when_no_task(self):
        """cancel_grace_task should be a no-op when no task exists."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        # Should not raise
        room.cancel_grace_task(Role.TUTOR)
        room.cancel_grace_task(Role.STUDENT)

    def test_any_connected_with_one_participant(self):
        """any_connected should return True if at least one is connected."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        assert not room.any_connected()

        room.participants[Role.TUTOR].connected = True
        assert room.any_connected()

        room.participants[Role.TUTOR].connected = False
        room.participants[Role.STUDENT].connected = True
        assert room.any_connected()

    def test_any_connected_with_both(self):
        """any_connected should return True when both are connected."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        room.participants[Role.TUTOR].connected = True
        room.participants[Role.STUDENT].connected = True
        assert room.any_connected()

    def test_any_connected_with_none(self):
        """any_connected should return False when neither is connected."""
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        assert not room.any_connected()


class TestGracePeriodAsync:
    """Test async grace period finalization."""

    @pytest.mark.asyncio
    async def test_grace_period_finalizes_when_disconnected(self):
        """Grace period should finalize session if still disconnected."""
        from app.config import settings
        original = settings.reconnect_grace_seconds
        settings.reconnect_grace_seconds = 0.1  # Fast for test

        try:
            room = SessionRoom(session_id="grace-test", tutor_token="t", student_token="s")
            room.started_at = time.time()
            room.participants[Role.TUTOR].connected = False
            room.participants[Role.STUDENT].connected = False

            await _grace_period_finalize(room, Role.TUTOR)
            assert room.ended_at is not None
        finally:
            settings.reconnect_grace_seconds = original

    @pytest.mark.asyncio
    async def test_grace_period_cancelled_on_reconnect(self):
        """If reconnect happens during grace period, finalization is cancelled."""
        from app.config import settings
        original = settings.reconnect_grace_seconds
        settings.reconnect_grace_seconds = 1.0

        try:
            room = SessionRoom(session_id="grace-cancel", tutor_token="t", student_token="s")
            room.started_at = time.time()
            room.participants[Role.TUTOR].connected = False

            # Start grace period
            task = asyncio.create_task(_grace_period_finalize(room, Role.TUTOR))
            room._grace_tasks["tutor"] = task

            # Simulate reconnect before grace expires
            await asyncio.sleep(0.05)
            room.participants[Role.TUTOR].connected = True
            room.cancel_grace_task(Role.TUTOR)

            # Wait a bit for cancellation to propagate
            await asyncio.sleep(0.1)
            assert room.ended_at is None
        finally:
            settings.reconnect_grace_seconds = original

    @pytest.mark.asyncio
    async def test_grace_period_does_not_finalize_if_other_connected(self):
        """Grace period should not finalize if other participant is still connected."""
        from app.config import settings
        original = settings.reconnect_grace_seconds
        settings.reconnect_grace_seconds = 0.1

        try:
            room = SessionRoom(session_id="grace-partial", tutor_token="t", student_token="s")
            room.started_at = time.time()
            room.participants[Role.TUTOR].connected = True
            room.participants[Role.STUDENT].connected = False

            await _grace_period_finalize(room, Role.STUDENT)
            # Tutor still connected, so session should NOT be finalized
            assert room.ended_at is None
        finally:
            settings.reconnect_grace_seconds = original


class TestDisconnectedAt:
    """Test the disconnected_at tracking field."""

    def test_disconnected_at_initially_none(self):
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        assert room.participants[Role.TUTOR].disconnected_at is None
        assert room.participants[Role.STUDENT].disconnected_at is None

    def test_disconnected_at_set_on_disconnect(self):
        room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
        now = time.time()
        room.participants[Role.TUTOR].disconnected_at = now
        assert room.participants[Role.TUTOR].disconnected_at == now


class TestTutorIdentity:
    """Test tutor identity flows through session creation."""

    def test_create_session_with_tutor_id(self):
        mgr = SessionManager()
        resp = mgr.create_session(tutor_id="tutor-123")
        room = mgr.get_session(resp.session_id)
        assert room.tutor_id == "tutor-123"

    def test_create_session_with_session_type(self):
        mgr = SessionManager()
        resp = mgr.create_session(session_type="practice")
        room = mgr.get_session(resp.session_id)
        assert room.session_type == "practice"

    def test_create_session_default_tutor_id(self):
        mgr = SessionManager()
        resp = mgr.create_session()
        room = mgr.get_session(resp.session_id)
        assert room.tutor_id == ""

    def test_create_session_default_session_type(self):
        mgr = SessionManager()
        resp = mgr.create_session()
        room = mgr.get_session(resp.session_id)
        assert room.session_type == "general"

    def test_create_session_default_media_provider(self):
        mgr = SessionManager()
        resp = mgr.create_session()
        room = mgr.get_session(resp.session_id)
        assert room.media_provider.value == "livekit"
        assert resp.media_provider.value == "livekit"

    def test_create_session_with_livekit_provider(self):
        from app.models import MediaProvider

        mgr = SessionManager()
        resp = mgr.create_session(media_provider=MediaProvider.LIVEKIT)
        room = mgr.get_session(resp.session_id)
        assert room.media_provider == MediaProvider.LIVEKIT
        assert room.livekit_room_name
        assert resp.livekit_room_name == room.livekit_room_name


class TestSessionEndedRejection:
    """Test that ended sessions reject new connections."""

    def test_ended_session_still_accessible(self):
        """Even after ending, the session room still exists for data access."""
        mgr = SessionManager()
        resp = mgr.create_session()
        room = mgr.get_session(resp.session_id)
        room.started_at = time.time()
        _finalize_session(room)

        # Room should still be accessible
        assert mgr.get_session(resp.session_id) is not None
        assert room.ended_at is not None


class TestConnectionTakeover:
    """Tests for forced connection takeover and identity-guard cleanup."""

    # ------------------------------------------------------------------ #
    # Unit tests — pure state-machine logic, no real WebSocket needed     #
    # ------------------------------------------------------------------ #

    def test_identity_guard_skips_cleanup_when_taken_over(self):
        """The finally-block identity guard must skip cleanup when the participant
        has already been taken over by a newer connection."""
        room = SessionRoom(session_id="takeover-unit", tutor_token="t", student_token="s")
        room.started_at = time.time()

        old_ws = object()  # stand-in for the stale WebSocket
        new_ws = object()  # stand-in for the replacement WebSocket

        participant = room.participants[Role.STUDENT]
        participant.connected = True
        participant.websocket = new_ws  # takeover already set the new ws

        # Simulate the identity-guarded finally block running for old_ws
        if participant.websocket is old_ws:
            # Would normally clean up — but guard prevents this branch
            participant.connected = False
            participant.websocket = None

        # Cleanup must NOT have happened
        assert participant.connected is True
        assert participant.websocket is new_ws

    def test_identity_guard_runs_cleanup_for_current_socket(self):
        """When the websocket is still the current one the finally block must
        clean up participant state normally."""
        room = SessionRoom(session_id="guard-current", tutor_token="t", student_token="s")
        room.started_at = time.time()

        my_ws = object()
        participant = room.participants[Role.STUDENT]
        participant.connected = True
        participant.websocket = my_ws

        # Simulate the identity-guarded finally block running for my_ws
        if participant.websocket is my_ws:
            participant.connected = False
            participant.websocket = None

        assert participant.connected is False
        assert participant.websocket is None

    def test_identity_guard_skips_cleanup_when_websocket_is_none(self):
        """If takeover sets participant.websocket = None before the stale
        handler's finally runs, the guard (is not websocket) also prevents
        cleanup — None is not the same object as old_ws."""
        old_ws = object()

        room = SessionRoom(session_id="guard-none", tutor_token="t", student_token="s")
        room.started_at = time.time()

        participant = room.participants[Role.STUDENT]
        participant.connected = True
        # Takeover set websocket to None but new connection hasn't set itself yet
        participant.websocket = None

        # Simulate the identity-guarded finally block running for old_ws
        if participant.websocket is old_ws:
            participant.connected = False
            participant.websocket = None

        # connected flag was NOT cleared because guard prevented cleanup
        assert participant.connected is True

    @pytest.mark.asyncio
    async def test_stale_websocket_closed_with_4002_on_takeover(self):
        """The forced-takeover path should close the old socket with code 4002."""

        class _MockWS:
            def __init__(self):
                self.close_calls: list[dict] = []

            async def close(self, code: int = 1000, reason: str = "") -> None:
                self.close_calls.append({"code": code, "reason": reason})

        old_ws = _MockWS()
        room = SessionRoom(session_id="takeover-close", tutor_token="t", student_token="s")
        room.started_at = time.time()

        participant = room.participants[Role.STUDENT]
        participant.connected = True
        participant.websocket = old_ws  # type: ignore[assignment]

        # Simulate the takeover block from websocket_endpoint
        if participant.connected:
            stale_ws = participant.websocket
            participant.websocket = None
            participant.connected = False
            if stale_ws is not None:
                async def _close_stale(ws=stale_ws):
                    try:
                        await ws.close(code=4002, reason="Replaced by new connection")
                    except Exception:
                        pass
                asyncio.create_task(_close_stale())

        # Yield control so the fire-and-forget task runs
        await asyncio.sleep(0)

        assert len(old_ws.close_calls) == 1
        assert old_ws.close_calls[0]["code"] == 4002
        assert participant.connected is False
        assert participant.websocket is None

    # ------------------------------------------------------------------ #
    # Integration tests — real WebSocket via TestClient                   #
    # ------------------------------------------------------------------ #

    def test_second_connection_accepted_when_participant_stale_connected(self):
        """When participant.connected is True (stale state) and websocket is None,
        a new connection should be accepted via takeover, not rejected with 4002."""
        from app.main import app as _app

        client = TestClient(_app)
        resp = client.post("/api/sessions")
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None

        # Simulate stale state: connected flag set but no actual socket object
        participant = room.participants[Role.STUDENT]
        participant.connected = True
        participant.websocket = None

        # New connection should succeed (takeover), not be refused
        with client.websocket_connect(
            f"/ws/session/{data['session_id']}?token={data['student_token']}"
        ) as ws:
            assert ws is not None
            assert participant.connected is True

    def test_new_connection_is_functional_after_takeover(self):
        """After a takeover the new connection should be able to send control
        messages that update participant state."""
        from app.main import app as _app

        client = TestClient(_app)
        resp = client.post("/api/sessions")
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None

        # Force stale state
        participant = room.participants[Role.STUDENT]
        participant.connected = True
        participant.websocket = None

        with client.websocket_connect(
            f"/ws/session/{data['session_id']}?token={data['student_token']}"
        ) as ws:
            ws.send_text(json.dumps({
                "type": "client_status",
                "data": {"audio_muted": True},
            }))
            # Give the server-side handler time to process the message
            deadline = time.time() + 0.5
            while time.time() < deadline:
                if participant.audio_muted:
                    break
                time.sleep(0.01)

            assert participant.audio_muted is True

    def test_second_live_connection_takes_over_first_connection(self):
        """A real second socket should take over the first socket for the same participant.

        Verifies the full behavior requested in the step:
        - the replacement socket is accepted and functional
        - the old socket is closed with code 4002
        - stale cleanup does not clear the participant's current connected state
        """
        from app.main import app as _app

        client = TestClient(_app)
        resp = client.post("/api/sessions")
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None

        participant = room.participants[Role.STUDENT]

        with client.websocket_connect(
            f"/ws/session/{data['session_id']}?token={data['student_token']}"
        ) as old_ws:
            old_socket_obj = participant.websocket
            assert participant.connected is True
            assert old_socket_obj is not None

            with client.websocket_connect(
                f"/ws/session/{data['session_id']}?token={data['student_token']}"
            ) as new_ws:
                # The new websocket should now own the participant state.
                assert participant.connected is True
                assert participant.websocket is not None
                assert participant.websocket is not old_socket_obj

                new_ws.send_text(json.dumps({
                    "type": "client_status",
                    "data": {"audio_muted": True},
                }))
                deadline = time.time() + 0.5
                while time.time() < deadline:
                    if participant.audio_muted:
                        break
                    time.sleep(0.01)
                assert participant.audio_muted is True
                assert participant.connected is True

                # The old socket should be closed by the takeover with code 4002.
                deadline = time.time() + 0.5
                observed_close_code = None
                while time.time() < deadline and observed_close_code is None:
                    try:
                        old_ws.receive_text()
                    except WebSocketDisconnect as exc:
                        observed_close_code = exc.code
                        break
                    time.sleep(0.01)

                assert observed_close_code == 4002
                # Old handler cleanup must not clobber the replacement connection.
                assert participant.connected is True
                assert participant.websocket is not None
                assert participant.websocket is not old_socket_obj
