"""Tests for transcription integration into LiveKit worker and session runtime.

Covers:
- TOPIC_TRANSCRIPT_PARTIAL / TOPIC_TRANSCRIPT_FINAL constants
- _get_or_create_transcription_stream helper
- TranscriptBuffer and TranscriptStore as session resources
- process_audio_chunk returns result with is_speech
- transcript_available set on MetricsSnapshot
- Cleanup in finalize_session
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.livekit_worker import (
    TOPIC_TRANSCRIPT_FINAL,
    TOPIC_TRANSCRIPT_PARTIAL,
    LiveKitAnalyticsWorker,
)
from app.models import MediaProvider, Role
from app.session_manager import session_manager
from app.session_runtime import (
    _session_resources,
    cleanup_resources,
    get_or_create_resources,
    get_or_create_transcription_stream,
    process_audio_chunk,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def _enable_transcription(monkeypatch):
    monkeypatch.setattr(settings, "enable_transcription", True)
    monkeypatch.setattr(settings, "transcription_roles", ["tutor", "student"])
    monkeypatch.setattr(settings, "transcription_provider", "mock")
    monkeypatch.setattr(settings, "deepgram_api_key", "")


@pytest.fixture
def room():
    resp = session_manager.create_session(
        media_provider=MediaProvider.LIVEKIT,
        tutor_id="tutor-1",
    )
    room = session_manager.get_session(resp.session_id)
    assert room is not None
    room.started_at = time.time()
    yield room
    cleanup_resources(room.session_id)
    session_manager.remove_session(room.session_id)


# ---------------------------------------------------------------------------
# Topic constants
# ---------------------------------------------------------------------------

def test_topic_transcript_constants():
    assert TOPIC_TRANSCRIPT_PARTIAL == "lsa.transcript.partial.v1"
    assert TOPIC_TRANSCRIPT_FINAL == "lsa.transcript.final.v1"


# ---------------------------------------------------------------------------
# Resources include transcription objects when enabled
# ---------------------------------------------------------------------------

def test_resources_include_transcript_buffer_when_enabled(monkeypatch, room):
    monkeypatch.setattr(settings, "enable_transcription", True)
    resources = get_or_create_resources(room)
    assert "transcript_buffer" in resources
    assert "transcript_store" in resources
    assert "session_clock" in resources


def test_resources_exclude_transcript_when_disabled(monkeypatch, room):
    monkeypatch.setattr(settings, "enable_transcription", False)
    # Force fresh resource creation
    _session_resources.pop(room.session_id, None)
    resources = get_or_create_resources(room)
    assert "transcript_buffer" not in resources
    assert "transcript_store" not in resources


# ---------------------------------------------------------------------------
# get_or_create_transcription_stream
# ---------------------------------------------------------------------------

def test_returns_none_when_transcription_disabled(monkeypatch, room):
    monkeypatch.setattr(settings, "enable_transcription", False)
    _session_resources.pop(room.session_id, None)
    result = get_or_create_transcription_stream(room, Role.STUDENT)
    assert result is None


def test_returns_none_when_role_not_in_roles(monkeypatch, room):
    monkeypatch.setattr(settings, "enable_transcription", True)
    monkeypatch.setattr(settings, "transcription_roles", ["student"])
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    _session_resources.pop(room.session_id, None)
    result = get_or_create_transcription_stream(room, Role.TUTOR)
    assert result is None


@pytest.mark.asyncio
async def test_creates_stream_when_enabled(_enable_transcription, room):
    _session_resources.pop(room.session_id, None)
    ts = get_or_create_transcription_stream(room, Role.STUDENT, student_index=0)
    assert ts is not None

    # Second call returns same instance
    ts2 = get_or_create_transcription_stream(room, Role.STUDENT, student_index=0)
    assert ts2 is ts


@pytest.mark.asyncio
async def test_stream_stored_in_resources(_enable_transcription, room):
    _session_resources.pop(room.session_id, None)
    get_or_create_transcription_stream(room, Role.TUTOR, student_index=0)
    resources = _session_resources.get(room.session_id, {})
    assert "transcription_stream_tutor:0" in resources


# ---------------------------------------------------------------------------
# process_audio_chunk returns result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_audio_chunk_returns_result(room):
    """process_audio_chunk should return the audio processing result."""
    # Generate 30ms of silence at 16kHz mono PCM16
    pcm = bytes(480 * 2)
    result = await process_audio_chunk(room, Role.STUDENT, pcm)
    assert result is not None
    assert hasattr(result, "is_speech")


# ---------------------------------------------------------------------------
# transcript_available on MetricsSnapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcript_available_set_when_transcription_resources_exist(
    _enable_transcription, room
):
    """MetricsSnapshot.transcript_available should be True when transcription
    is active for the session, even before the first stream is created."""
    _session_resources.pop(room.session_id, None)
    get_or_create_resources(room)

    from app.session_runtime import emit_metrics_snapshot

    snapshot = await emit_metrics_snapshot(
        room, record_history=False, allow_coaching=False
    )
    if snapshot is not None:
        assert snapshot.transcript_available is True


@pytest.mark.asyncio
async def test_transcript_available_false_when_disabled(monkeypatch, room):
    monkeypatch.setattr(settings, "enable_transcription", False)
    _session_resources.pop(room.session_id, None)

    from app.session_runtime import emit_metrics_snapshot

    snapshot = await emit_metrics_snapshot(
        room, record_history=False, allow_coaching=False
    )
    if snapshot is not None:
        assert snapshot.transcript_available is False


# ---------------------------------------------------------------------------
# LiveKitAnalyticsWorker._get_or_create_transcription_stream
# ---------------------------------------------------------------------------

def test_worker_get_or_create_returns_none_when_disabled(monkeypatch, room):
    monkeypatch.setattr(settings, "enable_transcription", False)
    worker = LiveKitAnalyticsWorker(session=room)
    result = worker._get_or_create_transcription_stream(Role.STUDENT)
    assert result is None


@pytest.mark.asyncio
async def test_worker_get_or_create_caches_stream(_enable_transcription, room):
    _session_resources.pop(room.session_id, None)
    worker = LiveKitAnalyticsWorker(session=room)
    ts1 = worker._get_or_create_transcription_stream(Role.STUDENT)
    assert ts1 is not None
    ts2 = worker._get_or_create_transcription_stream(Role.STUDENT)
    assert ts2 is ts1


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_resources_stops_and_removes_transcription(
    _enable_transcription, room
):
    _session_resources.pop(room.session_id, None)
    ts = get_or_create_transcription_stream(room, Role.STUDENT, student_index=0)
    assert ts is not None
    assert room.session_id in _session_resources

    stop_called = False

    async def mock_stop():
        nonlocal stop_called
        stop_called = True
        return []

    ts.stop = mock_stop

    cleanup_resources(room.session_id)
    # cleanup_resources schedules stop() via create_task in async context;
    # yield control so the task runs.
    await asyncio.sleep(0)
    assert stop_called is True
    assert room.session_id not in _session_resources


# ---------------------------------------------------------------------------
# Shutdown stops transcription streams
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_shutdown_stops_transcription_streams(
    _enable_transcription, room
):
    worker = LiveKitAnalyticsWorker(session=room)
    fake_stream = AsyncMock()
    worker._transcription_streams["student:0"] = fake_stream

    await worker._shutdown()
    fake_stream.stop.assert_awaited_once()
    assert len(worker._transcription_streams) == 0
