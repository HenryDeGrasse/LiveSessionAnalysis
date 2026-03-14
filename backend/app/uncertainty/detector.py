"""Uncertainty fusion detector: combines paralinguistic and linguistic signals.

``UncertaintyDetector`` is a per-student instance that:

1. Receives paralinguistic prosody updates via ``update_audio()``.
2. Receives student transcript utterances via ``update_transcript()``.
3. Fuses both signal types (50/50 weighting).
4. Applies persistence gating — uncertainty must be sustained (2+ utterances
   above threshold within a 45-second window) before surfacing to the
   coaching layer or UI.
5. Tracks the current discussion topic via ``TutorQuestionTopicExtractor``.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING, Deque, List, Optional, Tuple

from .linguistic import LinguisticUncertaintyDetector
from .models import FusedUncertaintySignal, LinguisticUncertaintyResult
from .paralinguistic import ParalinguisticAnalyzer, ParalinguisticResult
from .topic_extractor import TutorQuestionTopicExtractor

if TYPE_CHECKING:
    from app.audio_processor.prosody import ProsodyResult


class UncertaintyDetector:
    """Fuses paralinguistic and linguistic uncertainty signals.

    Key design decisions (from architecture review):
        1. Per-student instances (not global) for multi-student sessions.
        2. Both signal types are *features* — fusion handles calibration.
        3. Persistence required: score > threshold for N utterances within a
           time window before surfacing to coaching/UI.
        4. Topic association uses tutor questions + curated vocabulary.

    Usage::

        detector = UncertaintyDetector(student_index=0)

        # Feed audio prosody regularly
        detector.update_audio(prosody_result, timestamp=12.5)

        # Feed transcript when a student utterance is finalized
        signal = detector.update_transcript(
            text="um i think maybe the derivative?",
            end_time=13.0,
            speaker_id="student-0",
            recent_tutor_utterances=["What is the derivative of x squared?"],
        )
        if signal is not None:
            print("Sustained uncertainty:", signal)
    """

    # Fusion weights
    W_PARALINGUISTIC = 0.5
    W_LINGUISTIC = 0.5

    # Persistence: uncertainty must be sustained before we report it
    PERSISTENCE_UTTERANCES = 2
    PERSISTENCE_WINDOW_SECONDS = 45.0
    UNCERTAINTY_THRESHOLD = 0.5

    def __init__(
        self,
        student_index: int = 0,
        persistence_utterances: int | None = None,
        persistence_window_seconds: float | None = None,
        uncertainty_threshold: float | None = None,
        warmup_seconds: float = 20.0,
    ) -> None:
        self._student_index = student_index

        # Allow override for testing
        if persistence_utterances is not None:
            self.PERSISTENCE_UTTERANCES = persistence_utterances
        if persistence_window_seconds is not None:
            self.PERSISTENCE_WINDOW_SECONDS = persistence_window_seconds
        if uncertainty_threshold is not None:
            self.UNCERTAINTY_THRESHOLD = uncertainty_threshold

        # Sub-detectors
        self._paralinguistic = ParalinguisticAnalyzer(warmup_seconds=warmup_seconds)
        self._linguistic = LinguisticUncertaintyDetector()

        # Most recent paralinguistic score (updated via update_audio)
        self._last_para_score: float = 0.0

        # Persistence tracking: (timestamp, fusion_score)
        self._recent_scores: Deque[Tuple[float, float]] = deque(maxlen=50)

        # Topic tracking
        self._topic_extractor = TutorQuestionTopicExtractor()

        # Most recent surfaced persistent signal.
        self._last_signal: Optional[FusedUncertaintySignal] = None
        self._last_signal_time: float | None = None

    # ------------------------------------------------------------------ #
    # Audio updates
    # ------------------------------------------------------------------ #

    def update_audio(
        self,
        prosody_or_pitch: "ProsodyResult | float | None" = None,
        speech_rate: float | None = None,
        pause_ratio: float | None = None,
        trailing_energy: bool | None = None,
        chunk_duration_seconds: float | None = None,
        *,
        pitch_hz: float | None = None,
        timestamp: float | None = None,
        role: str = "student",
    ) -> ParalinguisticResult:
        """Update paralinguistic signals from audio processing.

        Supports both call styles:
        1. ``update_audio(prosody_result, timestamp=..., role=...)``
        2. ``update_audio(pitch_hz, speech_rate, pause_ratio, trailing_energy, chunk_duration_seconds)``

        ``timestamp`` is accepted for API compatibility with the session
        pipeline, but the current fusion logic only needs the most recent
        paralinguistic score, so it is not otherwise used here.
        """
        del timestamp  # reserved for future time-aware fusion logic

        if hasattr(prosody_or_pitch, "pitch_hz") and hasattr(prosody_or_pitch, "speech_rate_proxy"):
            prosody = prosody_or_pitch
            pitch_hz_value = float(prosody.pitch_hz)
            speech_rate_value = float(prosody.speech_rate_proxy)
            pause_ratio_value = float(prosody.pause_ratio)
            trailing_energy_value = bool(prosody.trailing_energy)
            duration_value = float(chunk_duration_seconds) if chunk_duration_seconds is not None else 0.0
        else:
            pitch_hz_value = pitch_hz if pitch_hz is not None else prosody_or_pitch
            if (
                pitch_hz_value is None
                or speech_rate is None
                or pause_ratio is None
                or trailing_energy is None
                or chunk_duration_seconds is None
            ):
                raise ValueError(
                    "update_audio() requires either a ProsodyResult or all explicit prosody fields"
                )
            pitch_hz_value = float(pitch_hz_value)
            speech_rate_value = float(speech_rate)
            pause_ratio_value = float(pause_ratio)
            trailing_energy_value = bool(trailing_energy)
            duration_value = float(chunk_duration_seconds)

        if pitch_hz is not None and prosody_or_pitch is not None and hasattr(prosody_or_pitch, "pitch_hz"):
            raise ValueError("Pass either ProsodyResult or pitch_hz, not both")

        result = self._paralinguistic.update(
            role=role,
            pitch_hz=pitch_hz_value,
            speech_rate=speech_rate_value,
            pause_ratio=pause_ratio_value,
            trailing_energy=trailing_energy_value,
            chunk_duration_seconds=duration_value,
        )
        self._last_para_score = result.score
        return result

    # ------------------------------------------------------------------ #
    # Transcript updates
    # ------------------------------------------------------------------ #

    def update_transcript(
        self,
        text: str,
        end_time: float,
        speaker_id: str = "student",
        recent_tutor_utterances: Optional[List[str]] = None,
    ) -> Optional[FusedUncertaintySignal]:
        """Process a new student utterance and check for sustained uncertainty.

        Returns a ``FusedUncertaintySignal`` only if:
            1. The raw fusion score exceeds the threshold.
            2. The persistence requirement is met (N utterances above threshold
               within the window).

        Args:
            text: The student's utterance text.
            end_time: Session-relative timestamp (seconds) of utterance end.
            speaker_id: Speaker identifier for per-speaker filler calibration.
            recent_tutor_utterances: Recent tutor utterance texts for topic
                extraction.

        Returns:
            ``FusedUncertaintySignal`` if sustained uncertainty detected,
            otherwise ``None``.
        """
        # Linguistic features
        ling_result = self._linguistic.analyze(text, speaker_id=speaker_id)

        # Paralinguistic features (most recent audio score)
        para_score = self._last_para_score

        # Fusion
        fusion_score = (
            self.W_PARALINGUISTIC * para_score
            + self.W_LINGUISTIC * ling_result.score
        )
        fusion_score = max(0.0, min(1.0, fusion_score))

        # Record for persistence tracking
        self._recent_scores.append((end_time, fusion_score))

        # Update topic from tutor questions
        if recent_tutor_utterances:
            self._topic_extractor.update(recent_tutor_utterances)

        # Check persistence: need N scores > threshold within the window
        if not self._persistence_met(end_time):
            return None

        signal = FusedUncertaintySignal(
            score=fusion_score,
            paralinguistic_score=para_score,
            linguistic_score=ling_result.score,
            topic=self._topic_extractor.current_topic,
            trigger_text=text,
            signals=ling_result.signals,
            confidence=self._compute_confidence(fusion_score, ling_result),
        )
        self._last_signal = signal
        self._last_signal_time = end_time
        return signal

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def current_uncertainty_score(self) -> float:
        """Smoothed uncertainty score (0-1) for the student.

        Uses exponentially-weighted recent mean so that very recent
        utterances count more than older ones.
        """
        if not self._recent_scores:
            return 0.0

        latest_time = self._recent_scores[-1][0]
        window_start = latest_time - self.PERSISTENCE_WINDOW_SECONDS
        scores = [s for ts, s in self._recent_scores if ts >= window_start]
        n = len(scores)
        if n <= 2:
            return scores[-1]

        # Exponentially-weighted mean over the recent window:
        # weights increase smoothly from exp(-1) to exp(0)=1.
        total_w = 0.0
        total_ws = 0.0
        for i, s in enumerate(scores):
            w = math.exp(-1.0 + i / (n - 1))
            total_w += w
            total_ws += w * s
        return total_ws / total_w if total_w > 0 else scores[-1]

    @property
    def uncertainty_topic(self) -> str:
        """Return the current topic string from tutor question extraction."""
        return self._topic_extractor.current_topic

    @property
    def current_uncertainty_signal(self) -> Optional[FusedUncertaintySignal]:
        """Return the latest persistent uncertainty signal that is still active."""
        if self._last_signal is None or self._last_signal_time is None:
            return None
        latest_time = self._recent_scores[-1][0] if self._recent_scores else self._last_signal_time
        if self._last_signal_time < latest_time - self.PERSISTENCE_WINDOW_SECONDS:
            return None
        if not self._persistence_met(latest_time):
            return None
        return self._last_signal

    @property
    def student_index(self) -> int:
        return self._student_index

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _persistence_met(self, current_time: float) -> bool:
        """Check if uncertainty has been sustained (not a one-off spike)."""
        window_start = current_time - self.PERSISTENCE_WINDOW_SECONDS
        recent_high = [
            score for ts, score in self._recent_scores
            if ts >= window_start and score >= self.UNCERTAINTY_THRESHOLD
        ]
        return len(recent_high) >= self.PERSISTENCE_UTTERANCES

    @staticmethod
    def _compute_confidence(
        fusion_score: float,
        ling_result: LinguisticUncertaintyResult,
    ) -> float:
        """Compute a confidence value for the fused uncertainty signal.

        Higher confidence when both signal types agree and when multiple
        linguistic signals are present.
        """
        # Base confidence from the fusion score distance from threshold
        base = min(1.0, fusion_score / 0.8) if fusion_score > 0 else 0.0

        # Bonus for multiple linguistic signal types
        signal_types = {s.signal_type for s in ling_result.signals}
        diversity_bonus = min(0.2, len(signal_types) * 0.05)

        return min(1.0, base + diversity_bonus)
