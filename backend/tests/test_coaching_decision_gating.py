"""Tests for coaching_decision debug-mode gating in emit_metrics_snapshot.

Verifies that:
- coaching_decision is None in normal (non-debug) mode
- coaching_decision is populated in debug mode with expected sub-fields
- Trace recording of coaching decisions works regardless of debug mode
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.metrics_engine.engine import MetricsEngine
from app.models import Role
from app.session_manager import SessionRoom
from app.session_runtime import (
    _session_resources,
    emit_metrics_snapshot,
)


def _make_room(*, debug_mode: bool = False) -> SessionRoom:
    """Create a minimal SessionRoom ready for emit_metrics_snapshot."""
    room = SessionRoom(
        session_id="test-coaching-gating",
        tutor_token="tutor-tok",
        student_token="student-tok",
        session_type="practice",
        coaching_intensity="subtle",
    )
    room.started_at = 1.0
    room.debug_mode = debug_mode
    # Mark tutor as connected with a mock websocket
    tutor = room.participants[Role.TUTOR]
    tutor.connected = True
    tutor.websocket = AsyncMock()
    tutor.websocket.send_json = AsyncMock()
    return room


def _install_resources(room: SessionRoom) -> dict:
    """Install session resources so emit_metrics_snapshot can find them."""
    resources = {
        "video_tutor": MagicMock(),
        "video_student": MagicMock(),
        "audio_tutor": MagicMock(),
        "audio_student": MagicMock(),
        "metrics_engine": MetricsEngine(room.session_id),
    }
    _session_resources[room.session_id] = resources
    return resources


def _teardown(room: SessionRoom):
    _session_resources.pop(room.session_id, None)


def _sent_payload(room: SessionRoom) -> "dict | None":
    """Extract the metrics payload that was sent to the tutor websocket."""
    ws = room.participants[Role.TUTOR].websocket
    if ws.send_json.call_count == 0:
        return None
    # First positional arg of first call
    call_args = ws.send_json.call_args_list[0]
    return call_args[0][0]


@pytest.mark.asyncio
async def test_coaching_decision_absent_in_normal_mode():
    """In normal (non-debug) mode, coaching_decision must be None/null
    in the metrics payload sent to the tutor."""
    room = _make_room(debug_mode=False)
    _install_resources(room)

    try:
        snapshot = await emit_metrics_snapshot(
            room,
            record_history=True,
            allow_coaching=True,
        )
    finally:
        _teardown(room)

    # The returned snapshot should have coaching_decision == None
    assert snapshot is not None
    assert snapshot.coaching_decision is None

    # The payload sent via websocket should also have null coaching_decision
    sent = _sent_payload(room)
    assert sent is not None
    assert sent["type"] == "metrics"
    assert sent["data"]["coaching_decision"] is None


@pytest.mark.asyncio
async def test_coaching_decision_populated_in_debug_mode():
    """In debug mode, coaching_decision must be populated with
    candidate_nudges, suppressed_reasons, emitted_nudge, trigger_features,
    and session_type/coaching_intensity."""
    room = _make_room(debug_mode=True)
    _install_resources(room)

    try:
        snapshot = await emit_metrics_snapshot(
            room,
            record_history=True,
            allow_coaching=True,
        )
    finally:
        _teardown(room)

    assert snapshot is not None
    assert snapshot.coaching_decision is not None

    cd = snapshot.coaching_decision
    assert "candidate_nudges" in cd
    assert "candidate_rule_scores" in cd
    assert "suppressed_reasons" in cd
    assert "emitted_nudge" in cd
    assert "trigger_features" in cd
    assert "session_type" in cd
    assert "coaching_intensity" in cd
    assert cd["session_type"] == "practice"
    assert cd["coaching_intensity"] == "subtle"

    # The payload sent to the tutor should include the decision
    sent = _sent_payload(room)
    assert sent is not None
    sent_cd = sent["data"]["coaching_decision"]
    assert sent_cd is not None
    assert "candidate_nudges" in sent_cd
    assert "session_type" in sent_cd
    assert sent_cd["coaching_intensity"] == "subtle"


@pytest.mark.asyncio
async def test_trace_recording_unconditional_regardless_of_debug_mode():
    """Trace recording of coaching decisions must happen in both
    normal and debug modes."""
    for debug in (False, True):
        room = _make_room(debug_mode=debug)
        _install_resources(room)

        mock_recorder = MagicMock()
        mock_recorder.record_metrics_snapshot = MagicMock()
        mock_recorder.record_coaching_decision = MagicMock()
        room.trace_recorder = mock_recorder

        try:
            await emit_metrics_snapshot(
                room,
                record_history=True,
                allow_coaching=True,
            )
        finally:
            _teardown(room)

        # Trace recording should always happen
        mock_recorder.record_coaching_decision.assert_called_once()
        call_kwargs = mock_recorder.record_coaching_decision.call_args
        # Verify the trace includes expected fields
        assert "candidate_nudges" in (call_kwargs.kwargs or {}) or len(call_kwargs.args) > 0


@pytest.mark.asyncio
async def test_coaching_decision_not_attached_when_coaching_disabled():
    """When allow_coaching=False (fast-path audio emit), coaching_decision
    must always be None regardless of debug mode."""
    room = _make_room(debug_mode=True)
    _install_resources(room)

    try:
        snapshot = await emit_metrics_snapshot(
            room,
            record_history=False,
            allow_coaching=False,
        )
    finally:
        _teardown(room)

    assert snapshot is not None
    assert snapshot.coaching_decision is None
