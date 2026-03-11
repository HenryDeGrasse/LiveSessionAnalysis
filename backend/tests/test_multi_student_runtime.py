"""Tests for multi-student WebSocket and session runtime behavior.

Covers:
- Per-student media processor creation in get_or_create_resources
- process_video_frame_bytes and process_audio_chunk routing by student_index
- finalize_session notifying extra students
- MetricsEngine extra_student_trackers creation and routing
- per_student_metrics in MetricsSnapshot
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.metrics_engine.engine import MetricsEngine
from app.models import Role
from app.session_manager import SessionRoom, session_manager
from app.session_runtime import (
    _session_resources,
    cleanup_resources,
    get_or_create_resources,
    process_audio_chunk,
    process_video_frame_bytes,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_room(max_students: int = 2) -> SessionRoom:
    resp = session_manager.create_session(max_students=max_students)
    room = session_manager.get_session(resp.session_id)
    assert room is not None
    room.started_at = 1.0
    return room


def _teardown(room: SessionRoom):
    _session_resources.pop(room.session_id, None)
    session_manager.remove_session(room.session_id)


# ── session_runtime: get_or_create_resources ─────────────────────────────────


def test_get_or_create_resources_creates_extra_student_processors():
    room = _make_room(max_students=3)
    try:
        assert len(room.extra_student_participants) == 2  # indices 1 and 2

        resources = get_or_create_resources(room)

        assert "video_student" in resources
        assert "audio_student" in resources
        assert "video_student_1" in resources
        assert "audio_student_1" in resources
        assert "video_student_2" in resources
        assert "audio_student_2" in resources
    finally:
        _teardown(room)


def test_get_or_create_resources_single_student_no_extras():
    room = _make_room(max_students=1)
    try:
        resources = get_or_create_resources(room)

        assert "video_student" in resources
        assert "audio_student" in resources
        # No extra keys
        assert "video_student_1" not in resources
        assert "audio_student_1" not in resources
    finally:
        _teardown(room)


def test_cleanup_resources_closes_extra_student_processors():
    room = _make_room(max_students=2)
    try:
        resources = get_or_create_resources(room)

        mock_video_extra = MagicMock()
        mock_video_extra.close = MagicMock()
        resources["video_student_1"] = mock_video_extra

        cleanup_resources(room.session_id)
        mock_video_extra.close.assert_called_once()
    finally:
        session_manager.remove_session(room.session_id)


# ── session_runtime: process_video_frame_bytes routing ───────────────────────


@pytest.mark.asyncio
async def test_process_video_frame_bytes_routes_to_extra_student_processor():
    room = _make_room(max_students=2)
    try:
        resources = get_or_create_resources(room)

        mock_processor = MagicMock()
        mock_result = MagicMock()
        mock_result.gaze = None
        mock_result.face_detected = True
        mock_result.expression = None
        mock_result.total_ms = 5.0
        mock_result.decode_ms = 1.0
        mock_result.facemesh_ms = 2.0
        mock_result.gaze_ms = 0.0
        mock_result.expression_ms = 0.0
        mock_processor.process_frame.return_value = mock_result
        resources["video_student_1"] = mock_processor

        # Connect student slot 1 so should_process_video_frame uses primary student tracker
        # (rate-limiting is keyed to Role.STUDENT primary slot for simplicity)
        room.participants[Role.STUDENT].last_video_processed_at = None

        payload = b"\xff\xd8\xff"  # minimal JPEG header
        await process_video_frame_bytes(room, Role.STUDENT, payload, student_index=1)

        mock_processor.process_frame.assert_called_once()
    finally:
        _teardown(room)


@pytest.mark.asyncio
async def test_process_audio_chunk_routes_to_extra_student_processor():
    room = _make_room(max_students=2)
    try:
        resources = get_or_create_resources(room)

        mock_processor = MagicMock()
        mock_result = MagicMock()
        mock_result.is_speech = True
        mock_result.prosody = MagicMock(rms_energy=0.5, speech_rate_proxy=0.3, rms_db=-20.0)
        mock_result.noise_floor_db = -40.0
        mock_processor.process_chunk.return_value = mock_result
        resources["audio_student_1"] = mock_processor

        payload = b"\x00" * 512
        await process_audio_chunk(room, Role.STUDENT, payload, student_index=1)

        mock_processor.process_chunk.assert_called_once()
    finally:
        _teardown(room)


# ── MetricsEngine: extra student tracker routing ──────────────────────────────


def test_metrics_engine_creates_extra_tracker_on_first_update():
    engine = MetricsEngine("test-multi-extra")

    assert 1 not in engine.extra_student_trackers

    engine.update_gaze(Role.STUDENT, 1.0, True, student_index=1)

    assert 1 in engine.extra_student_trackers
    t = engine.extra_student_trackers[1]
    assert "eye_contact" in t
    assert "energy" in t
    assert "attention_state" in t
    assert "speaking_time" in t


def test_metrics_engine_update_gaze_extra_student_does_not_affect_primary():
    engine = MetricsEngine("test-multi-gaze-isolation")

    engine.update_gaze(Role.STUDENT, 1.0, True)        # primary student
    primary_score_before = engine.student_eye_contact.score()

    engine.update_gaze(Role.STUDENT, 2.0, False, student_index=1)  # extra

    # Primary student eye contact should be unaffected by extra student update
    assert engine.student_eye_contact.score() == primary_score_before


def test_metrics_engine_update_expression_extra_student():
    engine = MetricsEngine("test-multi-expression")

    engine.update_expression(Role.STUDENT, 0.9, student_index=1)

    assert 1 in engine.extra_student_trackers
    # Primary student energy should not be affected
    assert not engine.student_energy.has_speech_history


def test_metrics_engine_update_audio_extra_student_routes_to_own_tracker():
    engine = MetricsEngine("test-multi-audio")

    # Extra student speaks
    engine.update_audio(Role.STUDENT, 1.0, True, 0.5, 0.3, student_index=1)

    assert 1 in engine.extra_student_trackers
    t = engine.extra_student_trackers[1]
    st = t["speaking_time"]
    # student_speaking should have been set on the extra tracker
    assert st.student_speaking is True

    # Primary speaking_time should be unaffected
    assert engine.speaking_time.student_speaking is False


def test_metrics_engine_update_audio_extra_student_no_interruption_side_effects():
    """Extra student audio must not corrupt primary interruption tracker."""
    engine = MetricsEngine("test-multi-interruption-isolation")

    before_count = engine.interruptions.total_count

    engine.update_audio(Role.STUDENT, 1.0, True, 0.8, 0.5, student_index=1)
    engine.update_audio(Role.TUTOR, 1.0, True, 0.8, 0.5)  # primary tutor speaks too

    # Interruption count should only reflect primary (tutor, primary student) interactions
    # Extra student should not have triggered an interruption event
    assert engine.interruptions.total_count == before_count


# ── MetricsSnapshot: per_student_metrics ─────────────────────────────────────


def test_compute_snapshot_no_extra_students():
    engine = MetricsEngine("test-snap-no-extra")
    snapshot = engine.compute_snapshot()

    assert snapshot.per_student_metrics is None


def test_compute_snapshot_with_extra_students():
    engine = MetricsEngine("test-snap-with-extra")

    engine.update_gaze(Role.STUDENT, 1.0, True, student_index=1)
    engine.update_audio(Role.STUDENT, 1.0, True, 0.5, 0.3, student_index=1)

    snapshot = engine.compute_snapshot()

    assert snapshot.per_student_metrics is not None
    assert "1" in snapshot.per_student_metrics
    metrics = snapshot.per_student_metrics["1"]
    # Should have ParticipantMetrics fields
    assert "eye_contact_score" in metrics
    assert "talk_time_percent" in metrics
    assert "is_speaking" in metrics


def test_compute_snapshot_per_student_metrics_serializable():
    """per_student_metrics must survive JSON round-trip."""
    import json

    engine = MetricsEngine("test-snap-json")
    engine.update_audio(Role.STUDENT, 1.0, True, 0.4, 0.2, student_index=2)

    snapshot = engine.compute_snapshot()
    data = snapshot.model_dump(mode="json")

    assert data["per_student_metrics"] is not None
    assert "2" in data["per_student_metrics"]

    # Should be JSON-serializable without error
    json.dumps(data)


# ── finalize_session: notify extra students ───────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_session_notifies_extra_students():
    from app.session_runtime import finalize_session

    room = _make_room(max_students=2)
    try:
        room.started_at = 1.0

        # Set up connected mock for extra student
        extra_ws = AsyncMock()
        extra_ws.send_json = AsyncMock()
        extra_ws.close = AsyncMock()
        extra_participant = room.extra_student_participants[1]
        extra_participant.connected = True
        extra_participant.websocket = extra_ws

        # Set up primary student and tutor as connected too
        primary_ws = AsyncMock()
        primary_ws.send_json = AsyncMock()
        primary_ws.close = AsyncMock()
        room.participants[Role.STUDENT].connected = True
        room.participants[Role.STUDENT].websocket = primary_ws

        tutor_ws = AsyncMock()
        tutor_ws.send_json = AsyncMock()
        tutor_ws.close = AsyncMock()
        room.participants[Role.TUTOR].connected = True
        room.participants[Role.TUTOR].websocket = tutor_ws

        finalize_session(room)
        # Allow the fire-and-forget task to run
        await asyncio.sleep(0.05)

        # Extra student should receive session_end
        extra_ws.send_json.assert_called_once()
        call_data = extra_ws.send_json.call_args[0][0]
        assert call_data["type"] == "session_end"
    finally:
        _teardown(room)
