"""Tests for post-session transcript persistence in finalize_session."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.models import Role, SessionSummary
from app.session_runtime import (
    _persist_transcript_data,
    finalize_session,
    get_or_create_resources,
    cleanup_resources,
    _session_resources,
)
from app.transcription.models import FinalUtterance, WordTiming
from app.transcription.store import TranscriptStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utt(
    role: str = "student",
    text: str = "hello world",
    start: float = 0.0,
    end: float = 1.0,
    utterance_id: str = "u1",
) -> FinalUtterance:
    return FinalUtterance(
        role=role,
        text=text,
        start_time=start,
        end_time=end,
        utterance_id=utterance_id,
        words=[],
    )


def _make_mock_room(session_id: str = "test-session-1") -> MagicMock:
    """Create a mock SessionRoom with the minimum required attributes."""
    room = MagicMock()
    room.session_id = session_id
    room.session_type = "general"
    room.session_title = "Test Session"
    room.tutor_id = "tutor-1"
    room.student_user_id = "student-1"
    room.media_provider = "livekit"
    room.ended_at = None
    room.started_at = 1000.0
    room.elapsed_seconds.return_value = 600.0
    room.metrics_history = []
    room.nudges_sent = []
    room.participants = {Role.TUTOR: MagicMock(connected=False, websocket=None)}
    room.extra_student_participants = {}
    room._metrics_task = None
    room._last_metrics_emit_at = 0.0
    room.coaching_intensity = "normal"
    room.max_students = 1
    room.student_tokens = ["tok-s1"]
    room.debug_mode = False
    room.latency_percentiles.return_value = (0.0, 0.0)
    return room


# ---------------------------------------------------------------------------
# Tests: _persist_transcript_data
# ---------------------------------------------------------------------------


class TestPersistTranscriptData:
    def test_empty_transcript_store_is_noop(self):
        room = _make_mock_room()
        store = TranscriptStore(session_id=room.session_id)
        resources = {"transcript_store": store}

        # Should not raise; no data to persist
        _persist_transcript_data(room, resources, None)

    def test_no_transcript_store_is_noop(self):
        room = _make_mock_room()
        resources = {}
        _persist_transcript_data(room, resources, None)

    @patch("app.session_runtime.settings")
    def test_persist_to_session_store(self, mock_settings):
        mock_settings.trace_storage_backend = "local"
        mock_settings.enable_transcript_storage = True

        room = _make_mock_room()
        store = TranscriptStore(session_id=room.session_id)
        store.add(_utt(text="hello world"))
        store.add(_utt(text="this is a test", utterance_id="u2"))

        summary = MagicMock(spec=SessionSummary)
        summary.transcript_word_count = 0

        mock_session_store = MagicMock()

        resources = {"transcript_store": store}

        with patch("app.analytics.get_session_store", return_value=mock_session_store):
            _persist_transcript_data(room, resources, summary)

        # Should have called save on the session store
        mock_session_store.save.assert_called_once_with(summary)
        # Summary should have compact transcript payload + word count updated
        assert summary.transcript_word_count == 6  # "hello world" (2) + "this is a test" (4)
        assert summary.transcript_compact is not None
        assert summary.transcript_compact["word_count"] == 6
        assert len(summary.transcript_compact["utterances"]) == 2

    @patch("app.session_runtime.settings")
    def test_persist_handles_session_store_error(self, mock_settings):
        mock_settings.trace_storage_backend = "local"
        mock_settings.enable_transcript_storage = True

        room = _make_mock_room()
        store = TranscriptStore(session_id=room.session_id)
        store.add(_utt(text="some text"))

        resources = {"transcript_store": store}

        with patch(
            "app.analytics.get_session_store",
            side_effect=Exception("DB error"),
        ):
            # Should not raise
            _persist_transcript_data(room, resources, None)


# ---------------------------------------------------------------------------
# Tests: finalize_session transcript enrichment
# ---------------------------------------------------------------------------


class TestFinalizeSessionTranscriptEnrichment:
    def setup_method(self):
        """Clean up session resources before each test."""
        _session_resources.clear()

    def teardown_method(self):
        _session_resources.clear()

    @patch("app.session_runtime.settings")
    @patch("app.session_runtime.save_session")
    @patch("app.session_runtime.generate_session_summary")
    def test_finalize_enriches_summary_with_word_count(
        self, mock_gen_summary, mock_save, mock_settings,
    ):
        mock_settings.enable_transcript_storage = True
        mock_settings.enable_transcription = False
        mock_settings.enable_uncertainty_detection = False
        mock_settings.enable_ai_coaching = False
        mock_settings.trace_storage_backend = "local"

        room = _make_mock_room()
        session_id = room.session_id

        # Create a summary mock
        summary = MagicMock(spec=SessionSummary)
        summary.transcript_word_count = 0
        mock_save.return_value = summary
        mock_gen_summary.return_value = summary

        # Set up resources with transcript store
        store = TranscriptStore(session_id=session_id)
        store.add(_utt(text="one two three"))
        store.add(_utt(text="four five", utterance_id="u2"))

        _session_resources[session_id] = {"transcript_store": store}

        with patch("app.session_runtime._persist_transcript_data"):
            finalize_session(room)

        # Verify word count was set on summary
        assert summary.transcript_word_count == 5

    @patch("app.session_runtime.settings")
    @patch("app.session_runtime.save_session")
    @patch("app.session_runtime.generate_session_summary")
    def test_finalize_skips_persistence_when_disabled(
        self, mock_gen_summary, mock_save, mock_settings,
    ):
        mock_settings.enable_transcript_storage = False
        mock_settings.enable_transcription = False
        mock_settings.enable_uncertainty_detection = False
        mock_settings.enable_ai_coaching = False
        mock_settings.trace_storage_backend = "local"

        room = _make_mock_room()
        session_id = room.session_id

        summary = MagicMock(spec=SessionSummary)
        summary.transcript_word_count = 0
        mock_save.return_value = summary

        store = TranscriptStore(session_id=session_id)
        store.add(_utt(text="test words here"))

        _session_resources[session_id] = {"transcript_store": store}

        with patch("app.session_runtime._persist_transcript_data") as mock_persist:
            finalize_session(room)
            mock_persist.assert_not_called()
