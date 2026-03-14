"""Tests for transcription data models and related config/model changes."""

from __future__ import annotations

from app.config import Settings
from app.models import MetricsSnapshot, SessionSummary, WSMessage
from app.transcription import (
    FinalUtterance,
    PartialTranscript,
    ProviderResponse,
    TranscriptionStats,
    WordTiming,
)
from datetime import datetime


class TestWordTiming:
    def test_creation(self):
        wt = WordTiming(word="hello", start=0.5, end=1.0, confidence=0.95)
        assert wt.word == "hello"
        assert wt.start == 0.5
        assert wt.end == 1.0
        assert wt.confidence == 0.95

    def test_frozen(self):
        wt = WordTiming(word="hi", start=0.0, end=0.2)
        try:
            wt.word = "bye"  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass

    def test_default_confidence(self):
        wt = WordTiming(word="ok", start=0.0, end=0.1)
        assert wt.confidence == 1.0


class TestPartialTranscript:
    def test_defaults(self):
        pt = PartialTranscript(role="student", text="um...", session_time=5.0)
        assert pt.role == "student"
        assert pt.utterance_id == ""
        assert pt.revision == 0
        assert pt.confidence == 1.0
        assert pt.is_final is False
        assert pt.speech_final is False
        assert pt.language == "en"


class TestFinalUtterance:
    def test_full_creation(self):
        words = [
            WordTiming(word="I", start=1.0, end=1.1),
            WordTiming(word="understand", start=1.1, end=1.5),
        ]
        fu = FinalUtterance(
            role="tutor",
            text="I understand",
            start_time=1.0,
            end_time=1.5,
            utterance_id="tutor:utt-1",
            words=words,
            confidence=0.98,
            sentiment="positive",
            sentiment_score=0.25,
            student_index=2,
        )
        assert fu.role == "tutor"
        assert fu.utterance_id == "tutor:utt-1"
        assert len(fu.words) == 2
        assert fu.confidence == 0.98
        assert fu.sentiment == "positive"
        assert fu.sentiment_score == 0.25
        assert fu.student_index == 2
        assert fu.speaker_id is None

    def test_defaults(self):
        fu = FinalUtterance(role="student", text="yes", start_time=0.0, end_time=0.5)
        assert fu.utterance_id == ""
        assert fu.words == []
        assert fu.sentiment is None
        assert fu.sentiment_score == 0.0
        assert fu.language == "en"
        assert fu.channel == 0
        assert fu.student_index == 0


class TestTranscriptionStats:
    def test_defaults(self):
        stats = TranscriptionStats()
        assert stats.total_audio_bytes_sent == 0
        assert stats.total_final_utterances == 0
        assert stats.voiced_chunks_received == 0
        assert stats.voiced_chunks_enqueued == 0
        assert stats.provider_audio_time_s == 0.0
        assert stats.avg_latency_ms == 0.0

    def test_mutation(self):
        stats = TranscriptionStats()
        stats.total_final_utterances = 5
        stats.dropped_audio_chunks = 2
        assert stats.total_final_utterances == 5
        assert stats.dropped_audio_chunks == 2


class TestProviderResponse:
    def test_creation(self):
        pr = ProviderResponse(
            is_final=True,
            speech_final=True,
            text="hello world",
            start=1.0,
            end=1.8,
            confidence=0.99,
            sentiment="neutral",
            sentiment_score=0.0,
        )
        assert pr.is_final is True
        assert pr.speech_final is True
        assert pr.is_partial is False
        assert pr.text == "hello world"
        assert pr.start == 1.0
        assert pr.end == 1.8
        assert pr.words == []
        assert pr.sentiment == "neutral"
        assert pr.provider_latency_ms == 0.0

    def test_is_partial(self):
        pr = ProviderResponse(is_final=False, speech_final=False, text="hello")
        assert pr.is_partial is True


class TestMetricsSnapshotNewFields:
    def test_defaults(self):
        ms = MetricsSnapshot(session_id="test-123")
        assert ms.transcript_available is False
        assert ms.student_uncertainty_score is None
        assert ms.student_uncertainty_topic is None
        assert ms.student_uncertainty_confidence is None
        assert ms.ai_suggestion is None

    def test_with_values(self):
        ms = MetricsSnapshot(
            session_id="test-123",
            transcript_available=True,
            student_uncertainty_score=0.85,
            student_uncertainty_topic="quadratic equations",
            student_uncertainty_confidence=0.72,
            ai_suggestion="Try breaking the problem into smaller steps",
        )
        assert ms.transcript_available is True
        assert ms.student_uncertainty_score == 0.85
        assert ms.student_uncertainty_topic == "quadratic equations"
        assert ms.ai_suggestion is not None

    def test_serialization_roundtrip(self):
        ms = MetricsSnapshot(
            session_id="s1",
            transcript_available=True,
            student_uncertainty_score=0.5,
        )
        data = ms.model_dump()
        assert data["transcript_available"] is True
        assert data["student_uncertainty_score"] == 0.5
        ms2 = MetricsSnapshot(**data)
        assert ms2.transcript_available is True


class TestSessionSummaryNewFields:
    def test_defaults(self):
        ss = SessionSummary(
            session_id="s1",
            start_time=datetime(2025, 1, 1),
            end_time=datetime(2025, 1, 1, 1),
            duration_seconds=3600.0,
        )
        assert ss.transcript_word_count == 0
        assert ss.topics_covered == []
        assert ss.ai_summary is None
        assert ss.student_understanding_map == {}
        assert ss.key_moments == []
        assert ss.uncertainty_timeline == []
        assert ss.transcript_compact is None

    def test_with_values(self):
        ss = SessionSummary(
            session_id="s1",
            start_time=datetime(2025, 1, 1),
            end_time=datetime(2025, 1, 1, 1),
            duration_seconds=3600.0,
            transcript_word_count=1500,
            topics_covered=["algebra", "geometry"],
            ai_summary="Good session focusing on quadratics.",
            student_understanding_map={"algebra": 0.8, "geometry": 0.6},
            key_moments=[{"time": 120, "type": "breakthrough"}],
            uncertainty_timeline=[{"time": 60, "score": 0.7, "topic": "fractions"}],
            transcript_compact={"utterances": [{"text": "hello"}], "word_count": 1},
        )
        assert ss.transcript_word_count == 1500
        assert len(ss.topics_covered) == 2
        assert ss.ai_summary is not None
        assert ss.student_understanding_map["algebra"] == 0.8
        assert ss.transcript_compact is not None


class TestWSMessageNewTypes:
    def test_transcript_partial(self):
        msg = WSMessage(type="transcript_partial", data={"text": "hello"})
        assert msg.type == "transcript_partial"

    def test_transcript_final(self):
        msg = WSMessage(type="transcript_final", data={"text": "hello world"})
        assert msg.type == "transcript_final"

    def test_existing_types_still_work(self):
        msg = WSMessage(type="metrics", data={})
        assert msg.type == "metrics"
        msg2 = WSMessage(type="nudge", data={"message": "test"})
        assert msg2.type == "nudge"


class TestConfigNewFields:
    def test_transcription_defaults(self):
        s = Settings()
        assert s.enable_transcription is False
        assert s.transcription_provider == "assemblyai"
        assert s.transcription_roles == ["student"]
        assert s.deepgram_api_key == ""
        assert s.assemblyai_api_key == ""
        assert s.transcription_language == "en"
        assert s.transcription_model == "nova-2"
        assert s.transcription_enable_sentiment is False
        assert s.transcription_buffer_window_seconds == 120.0
        assert s.transcription_queue_max_size == 200
        assert s.transcription_keepalive_interval_seconds == 8.0
        assert s.deepgram_endpointing_ms == 800
        assert s.deepgram_mip_opt_out is True

    def test_uncertainty_defaults(self):
        s = Settings()
        assert s.enable_uncertainty_detection is False
        assert s.uncertainty_ui_threshold == 0.6
        assert s.uncertainty_persistence_utterances == 2
        assert s.uncertainty_persistence_window_seconds == 45.0

    def test_ai_coaching_defaults(self):
        s = Settings()
        assert s.enable_ai_coaching is False
        assert s.ai_coaching_provider == "openrouter"
        assert s.ai_coaching_model == "anthropic/claude-3.5-haiku"
        assert s.openrouter_api_key == ""
        assert s.anthropic_api_key == ""
        assert s.ai_coaching_baseline_interval_seconds == 45.0
        assert s.ai_coaching_burst_interval_seconds == 15.0
        assert s.ai_coaching_max_calls_per_hour == 60

    def test_post_session_defaults(self):
        s = Settings()
        assert s.enable_transcript_storage is False
        assert s.enable_ai_session_summary is False
