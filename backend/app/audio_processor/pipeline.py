from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass

from ..config import settings
from .vad import VoiceActivityDetector
from .prosody import analyze_prosody, ProsodyResult


@dataclass
class AudioProcessingResult:
    """Result from processing a single audio chunk."""
    is_speech: bool
    raw_vad: bool
    noise_floor_db: float
    prosody: ProsodyResult
    processing_ms: float


class SpeechActivityGate:
    """Turns raw VAD output into a more stable speech-active signal.

    Uses an adaptive noise floor, simple zero-crossing sanity bounds, and
    short start/end smoothing so one noisy frame does not become a speaking
    segment or interruption.
    """

    def __init__(self):
        self._noise_floor_history: deque[float] = deque(maxlen=500)
        self._candidate_history: deque[bool] = deque(
            maxlen=settings.speech_start_window_frames
        )
        self._active = False
        self._consecutive_inactive = 0

    def process(
        self,
        raw_vad: bool,
        prosody: ProsodyResult,
        force_muted: bool = False,
    ) -> tuple[bool, float]:
        """Return smoothed speech-active state and current noise floor."""
        if force_muted:
            self._candidate_history.append(False)
            self._active = False
            self._consecutive_inactive = 0
            return False, self.noise_floor_db()

        if not raw_vad:
            self._noise_floor_history.append(prosody.rms_db)

        noise_floor_db = self.noise_floor_db()
        energy_ok = prosody.rms_db > noise_floor_db + settings.speech_noise_gate_db
        zcr_ok = (
            settings.speech_zcr_min
            <= prosody.zero_crossing_rate
            <= settings.speech_zcr_max
        )
        candidate = raw_vad and energy_ok and zcr_ok
        self._candidate_history.append(candidate)

        if not self._active:
            positives = sum(1 for value in self._candidate_history if value)
            if positives >= settings.speech_start_min_positive_frames:
                self._active = True
                self._consecutive_inactive = 0
        else:
            if candidate:
                self._consecutive_inactive = 0
            else:
                self._consecutive_inactive += 1
                if self._consecutive_inactive >= settings.speech_end_hangover_frames:
                    self._active = False
                    self._consecutive_inactive = 0

        return self._active, noise_floor_db

    def noise_floor_db(self) -> float:
        if not self._noise_floor_history:
            return -55.0
        return float(statistics.median(self._noise_floor_history))


class AudioProcessor:
    """Per-participant audio processing pipeline."""

    def __init__(self, aggressiveness: int = 2):
        self._vad = VoiceActivityDetector(aggressiveness=aggressiveness)
        self._speech_gate = SpeechActivityGate()

    def process_chunk(
        self,
        pcm_chunk: bytes,
        force_muted: bool = False,
    ) -> AudioProcessingResult:
        """Process a single audio chunk through VAD and prosody analysis.

        Args:
            pcm_chunk: Raw PCM bytes (16-bit signed, little-endian, 16kHz mono).
            force_muted: Force non-speech even if the PCM stream still carries
                residual noise while the browser track is muted.

        Returns:
            AudioProcessingResult with gated speech detection and prosody features.
        """
        start = time.time()

        raw_vad = False if force_muted else self._vad.is_speech(pcm_chunk)
        prosody = analyze_prosody(pcm_chunk)
        is_speech, noise_floor_db = self._speech_gate.process(
            raw_vad,
            prosody,
            force_muted=force_muted,
        )

        return AudioProcessingResult(
            is_speech=is_speech,
            raw_vad=raw_vad,
            noise_floor_db=noise_floor_db,
            prosody=prosody,
            processing_ms=(time.time() - start) * 1000,
        )
