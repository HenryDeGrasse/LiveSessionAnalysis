"""Data models for the transcription pipeline.

All models are plain dataclasses (not Pydantic) to keep serialization costs low
in the hot audio path.  Pydantic models are used only at the API boundary.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Literal, Optional

SentimentLabel = Literal["positive", "negative", "neutral"]
SpeakerRole = Literal["tutor", "student"]


class BackpressureLevel(enum.IntEnum):
    """5-level backpressure policy for the transcription pipeline.

    L0 – Normal: all features enabled.
    L1 – Partials degraded: provider latency >1s for 15s → disable partial
         UI updates.
    L2 – Transcript degraded: drop_rate >0.5% for 30s → stop transcript
         UI, show indicator, suspend AI auto-triggers (keep on-demand).
    L3 – Transcript disabled: WS down or drop_rate >5% for 60s → disable
         transcription entirely, fall back to rule-based coaching.
    L4 – Recovery: conditions improve, 30s hysteresis before upgrading level.
    """

    L0_NORMAL = 0
    L1_PARTIALS_DEGRADED = 1
    L2_TRANSCRIPT_DEGRADED = 2
    L3_TRANSCRIPT_DISABLED = 3


@dataclass(frozen=True)
class WordTiming:
    """A single word with timing metadata returned by the STT provider."""

    word: str
    start: float  # seconds from stream start
    end: float  # seconds from stream start
    confidence: float = 1.0


@dataclass()
class PartialTranscript:
    """An interim (non-final) transcript fragment.

    Sent to the frontend for real-time display but not persisted.
    Includes stable IDs so the UI can revise an in-progress utterance in place.
    """

    role: SpeakerRole
    text: str
    session_time: float  # seconds from session start (aligned via SessionClock)
    utterance_id: str = ""
    revision: int = 0
    confidence: float = 1.0
    is_final: bool = False
    speech_final: bool = False
    language: str = "en"


@dataclass()
class FinalUtterance:
    """A finalized transcript segment.

    Produced when the STT provider marks a segment as final.  This is the
    canonical unit stored in TranscriptBuffer / TranscriptStore.
    """

    role: SpeakerRole
    text: str
    start_time: float  # seconds from session start
    end_time: float  # seconds from session start
    utterance_id: str = ""
    words: List[WordTiming] = field(default_factory=list)
    confidence: float = 1.0
    sentiment: Optional[SentimentLabel] = None
    sentiment_score: float = 0.0
    language: str = "en"
    channel: int = 0
    speaker_id: Optional[str] = None
    student_index: int = 0


@dataclass()
class TranscriptionStats:
    """Lightweight runtime statistics for observability."""

    total_audio_bytes_sent: int = 0
    total_final_utterances: int = 0
    total_partial_updates: int = 0
    provider_reconnects: int = 0
    dropped_audio_chunks: int = 0
    voiced_chunks_received: int = 0
    voiced_chunks_enqueued: int = 0
    provider_audio_time_s: float = 0.0
    avg_latency_ms: float = 0.0
    last_utterance_epoch: float = 0.0


@dataclass()
class SessionObservability:
    """Per-session observability metrics aggregated across streams."""

    partial_latency_p50_ms: float = 0.0
    partial_latency_p95_ms: float = 0.0
    final_latency_p50_ms: float = 0.0
    final_latency_p95_ms: float = 0.0
    reconnect_count: int = 0
    drop_rate: float = 0.0
    billed_seconds_estimate: float = 0.0
    llm_call_count: int = 0
    llm_total_tokens: int = 0
    backpressure_level: int = 0


@dataclass()
class ProviderResponse:
    """Normalized response envelope from any STT provider.

    Both Deepgram and AssemblyAI results are mapped into this shape by the
    provider client before being handed to TranscriptionStream.
    """

    is_final: bool
    speech_final: bool
    text: str
    start: float = 0.0
    end: float = 0.0
    words: List[WordTiming] = field(default_factory=list)
    confidence: float = 1.0
    sentiment: Optional[SentimentLabel] = None
    sentiment_score: float = 0.0
    channel: int = 0
    language: str = "en"
    provider_latency_ms: float = 0.0

    @property
    def is_partial(self) -> bool:
        """Return True when this update is an interim provider hypothesis."""

        return not self.is_final and not self.speech_final
