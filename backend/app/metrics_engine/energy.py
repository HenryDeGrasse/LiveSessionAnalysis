from __future__ import annotations

from collections import deque

from ..config import settings


class EnergyTracker:
    """Tracks composite energy score for a participant.

    Energy = 0.5 * voice_rms + 0.3 * speech_rate_variance + 0.2 * expression_valence
    Audio-driven primarily; expression is a weak secondary signal.

    Also tracks a rolling baseline so coaching rules can detect drops
    relative to the participant's normal energy level.
    """

    def __init__(self, window_size: int = 30, baseline_window: int = 60):
        self._rms_history: deque[float] = deque(maxlen=window_size)
        self._speech_rate_history: deque[float] = deque(maxlen=window_size)
        self._expression_valence: float = 0.5
        self._current_score: float = 0.5
        # Baseline tracking: longer window of score history
        self._score_history: deque[float] = deque(maxlen=baseline_window)
        self._baseline: float = 0.5

    def update_audio(self, rms_energy: float, speech_rate_proxy: float):
        """Update with audio prosody features."""
        self._rms_history.append(rms_energy)
        self._speech_rate_history.append(speech_rate_proxy)
        self._recalculate()

    def update_expression(self, valence: float):
        """Update with facial expression valence."""
        self._expression_valence = valence
        self._recalculate()

    def _recalculate(self):
        """Recalculate composite energy score."""
        avg_rms = sum(self._rms_history) / len(self._rms_history) if self._rms_history else 0.0

        if len(self._speech_rate_history) > 1:
            mean_rate = sum(self._speech_rate_history) / len(self._speech_rate_history)
            variance = sum(
                (r - mean_rate) ** 2 for r in self._speech_rate_history
            ) / len(self._speech_rate_history)
            rate_score = min(1.0, variance / 0.05)
        else:
            rate_score = 0.0

        self._current_score = (
            settings.energy_weight_rms * avg_rms
            + settings.energy_weight_speech_rate * rate_score
            + settings.energy_weight_expression * self._expression_valence
        )

        # Track score history for baseline
        clamped = max(0.0, min(1.0, self._current_score))
        self._score_history.append(clamped)
        if len(self._score_history) >= 10:
            self._baseline = sum(self._score_history) / len(self._score_history)

    @property
    def score(self) -> float:
        return max(0.0, min(1.0, self._current_score))

    @property
    def baseline(self) -> float:
        """Rolling baseline energy level for this participant."""
        return self._baseline

    @property
    def drop_from_baseline(self) -> float:
        """How much current score has dropped below baseline. Positive = dropped."""
        return max(0.0, self._baseline - self.score)

    @property
    def session_average(self) -> float:
        """Get the average energy over all recorded samples."""
        if not self._score_history:
            return 0.5
        return sum(self._score_history) / len(self._score_history)
