from __future__ import annotations

import math
from collections import deque

from ..config import settings


class EnergyTracker:
    """Tracks composite vocal energy for a participant.

    Energy is a weighted combination of:
      - Voice RMS level (mapped via dB curve for perceptual accuracy)
      - Speech rate variation (standard-deviation based)
      - Facial expression valence (weak secondary signal)

    Important semantic choice: baseline and session-average energy are built
    from speech-active samples only. Silence should not drag the participant's
    "energy" down toward zero; silence is handled separately by talk-share and
    silence metrics.
    """

    # dB-scale mapping for RMS → energy. Normal conversational speech lands
    # around -30 to -17 dBFS, which should map to a healthy mid/high range.
    _RMS_DB_FLOOR: float = -50.0   # silence / noise floor → 0.0
    _RMS_DB_CEILING: float = -10.0  # loud / clipping → 1.0

    def __init__(self, window_size: int = 30, baseline_window: int = 60):
        self._rms_history: deque[float] = deque(maxlen=window_size)
        self._speech_rate_history: deque[float] = deque(maxlen=window_size)
        self._expression_valence: float = 0.5
        self._current_score: float = 0.5
        # Baseline/session-average history is intentionally speech-only.
        self._score_history: deque[float] = deque(maxlen=baseline_window)
        self._baseline: float = 0.5
        self._speech_sample_count: int = 0

    def update_audio(
        self,
        rms_energy: float,
        speech_rate_proxy: float,
        *,
        is_speech: bool = True,
    ):
        """Update with audio prosody features.

        Args:
            rms_energy: Normalized RMS energy (0-1, from prosody analyzer).
            speech_rate_proxy: Normalized syllable-rate proxy (0-1).
            is_speech: Whether this chunk represents speech. Non-speech chunks
                are ignored for energy-history purposes so silence does not
                artificially lower the metric.
        """
        if not is_speech:
            return

        self._rms_history.append(rms_energy)
        self._speech_rate_history.append(speech_rate_proxy)
        self._speech_sample_count += 1
        self._recalculate(track_history=True)

    def update_expression(self, valence: float):
        """Update with facial expression valence.

        Expression can influence the current composite, but expression-only
        updates do not count as speaking-energy history.
        """
        self._expression_valence = valence
        self._recalculate(track_history=False)

    @staticmethod
    def _rms_to_db_score(rms_normalized: float) -> float:
        """Convert normalized RMS (0-1) to a perceptual energy score via dB mapping."""
        if rms_normalized <= 0.0:
            return 0.0
        rms_db = 20.0 * math.log10(max(rms_normalized, 1e-6))
        score = (rms_db - EnergyTracker._RMS_DB_FLOOR) / (
            EnergyTracker._RMS_DB_CEILING - EnergyTracker._RMS_DB_FLOOR
        )
        return max(0.0, min(1.0, score))

    def _recalculate(self, *, track_history: bool):
        """Recalculate composite energy score.

        ``track_history`` should only be True for speech-active audio updates.
        """
        if self._rms_history:
            avg_rms = sum(self._rms_history) / len(self._rms_history)
            rms_score = self._rms_to_db_score(avg_rms)
        else:
            rms_score = 0.0

        if len(self._speech_rate_history) > 1:
            mean_rate = sum(self._speech_rate_history) / len(self._speech_rate_history)
            variance = sum(
                (r - mean_rate) ** 2 for r in self._speech_rate_history
            ) / len(self._speech_rate_history)
            # Standard deviation is in the same units as the proxy itself,
            # producing a much more usable range than raw variance.
            std_dev = math.sqrt(variance)
            rate_score = min(1.0, std_dev / 0.3)
        else:
            rate_score = 0.0

        composite = (
            settings.energy_weight_rms * rms_score
            + settings.energy_weight_speech_rate * rate_score
            + settings.energy_weight_expression * self._expression_valence
        )
        clamped = max(0.0, min(1.0, composite))
        self._current_score = clamped

        if track_history:
            self._score_history.append(clamped)
            if len(self._score_history) >= 10:
                self._baseline = sum(self._score_history) / len(self._score_history)

    @property
    def score(self) -> float:
        return max(0.0, min(1.0, self._current_score))

    @property
    def has_speech_history(self) -> bool:
        """Whether we have any speech-active samples for this participant."""
        return self._speech_sample_count > 0

    @property
    def baseline(self) -> float:
        """Rolling speaking-energy baseline for this participant."""
        return self._baseline

    @property
    def drop_from_baseline(self) -> float:
        """How much current speaking energy has dropped below baseline."""
        return max(0.0, self._baseline - self.score)

    @property
    def session_average(self) -> float:
        """Average speaking energy over recorded speech-active samples only."""
        if not self._score_history:
            return 0.5
        return sum(self._score_history) / len(self._score_history)
