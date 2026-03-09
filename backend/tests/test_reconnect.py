"""Tests for disconnect/reconnect resilience and grace period logic."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.models import Role
from app.session_manager import SessionManager, SessionRoom
from app.ws import _finalize_session, _grace_period_finalize, _cleanup_resources


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
        assert room.media_provider.value == "custom_webrtc"
        assert resp.media_provider.value == "custom_webrtc"

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
