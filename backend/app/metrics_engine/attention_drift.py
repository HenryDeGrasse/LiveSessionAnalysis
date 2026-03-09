from __future__ import annotations

from collections import deque

from ..config import settings


class AttentionDriftDetector:
    """Detects declining engagement trends for a participant.

    Uses a sliding window of engagement scores and computes the slope.
    A negative slope below the threshold indicates attention drift.
    """

    def __init__(
        self,
        window_seconds: float = None,
        slope_threshold: float = None,
    ):
        self._window = window_seconds or settings.attention_drift_window_seconds
        self._threshold = slope_threshold or settings.attention_drift_slope_threshold
        self._samples: deque[tuple[float, float]] = deque()
        self._drifting: bool = False

    def update(self, timestamp: float, engagement_score: float):
        """Record an engagement score sample."""
        self._samples.append((timestamp, engagement_score))
        self._prune(timestamp)
        self._detect()

    def _prune(self, now: float):
        cutoff = now - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def _detect(self):
        """Detect drift using linear regression slope."""
        if len(self._samples) < 5:
            self._drifting = False
            return

        # Simple linear regression
        n = len(self._samples)
        times = [s[0] for s in self._samples]
        scores = [s[1] for s in self._samples]

        # Normalize times to start from 0
        t0 = times[0]
        t_norm = [t - t0 for t in times]

        mean_t = sum(t_norm) / n
        mean_s = sum(scores) / n

        numerator = sum((t - mean_t) * (s - mean_s) for t, s in zip(t_norm, scores))
        denominator = sum((t - mean_t) ** 2 for t in t_norm)

        if denominator < 1e-6:
            self._drifting = False
            return

        slope = numerator / denominator
        # slope is in score-units per second
        # threshold is per-second slope (e.g., -0.2 means losing 0.2 score per second)
        # But that's too aggressive for scores in [0,1]. Let's interpret as:
        # slope < threshold means drift detected
        # A slope of -0.003 over 60 seconds = -0.18 total drop, which is significant
        self._drifting = slope < self._threshold

    @property
    def is_drifting(self) -> bool:
        return self._drifting

    def trend(self) -> str:
        """Return engagement trend as a string."""
        if len(self._samples) < 5:
            return "stable"

        n = len(self._samples)
        times = [s[0] for s in self._samples]
        scores = [s[1] for s in self._samples]
        t0 = times[0]
        t_norm = [t - t0 for t in times]

        mean_t = sum(t_norm) / n
        mean_s = sum(scores) / n

        numerator = sum((t - mean_t) * (s - mean_s) for t, s in zip(t_norm, scores))
        denominator = sum((t - mean_t) ** 2 for t in t_norm)

        if denominator < 1e-6:
            return "stable"

        slope = numerator / denominator

        if slope < self._threshold:
            return "declining"
        elif slope > abs(self._threshold):
            return "rising"
        return "stable"
