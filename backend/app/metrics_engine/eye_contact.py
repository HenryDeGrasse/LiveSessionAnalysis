from __future__ import annotations

import time
from collections import deque

from ..config import settings


class EyeContactTracker:
    """Tracks rolling-window eye contact percentage for a participant."""

    def __init__(self, window_seconds: float = None):
        self._window = window_seconds if window_seconds is not None else settings.rolling_window_seconds
        self._samples: deque[tuple[float, bool]] = deque()

    def update(self, timestamp: float, on_camera: bool):
        """Record a gaze sample."""
        self._samples.append((timestamp, on_camera))
        self._prune(timestamp)

    def score(self) -> float:
        """Get the current eye contact percentage (0-1)."""
        if not self._samples:
            return 0.5
        now = self._samples[-1][0]
        self._prune(now)
        if not self._samples:
            return 0.0
        on_count = sum(1 for _, on in self._samples if on)
        return on_count / len(self._samples)

    def _prune(self, now: float):
        """Remove samples outside the rolling window."""
        cutoff = now - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
