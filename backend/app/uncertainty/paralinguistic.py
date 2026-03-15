"""Paralinguistic uncertainty detection via prosody deviation from speaker baseline.

SpeakerBaseline tracks each speaker's vocal characteristics (pitch, speech rate)
using a warmup-then-EMA approach.  ParalinguisticAnalyzer fuses deviations from
baseline with pause ratio and trailing energy to produce a 0-1 uncertainty score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List


@dataclass
class ParalinguisticResult:
    """Output of a single paralinguistic uncertainty analysis."""

    score: float  # 0-1 overall uncertainty score
    pitch_deviation: float  # signed deviation from baseline (semitones-like)
    speech_rate_deviation: float  # signed deviation from baseline
    pause_ratio: float  # 0-1 fraction of chunk that was silence
    trailing_energy: bool  # True if energy rises toward end of chunk


class SpeakerBaseline:
    """Tracks a speaker's baseline pitch and speech rate using robust median
    warmup followed by slow EMA adaptation.

    During warmup (first ``warmup_seconds`` of voiced samples), ALL voiced
    samples are collected unconditionally — no circular confidence filtering.
    After warmup the baseline is the robust *median* of warmup samples and
    subsequent updates use a slow EMA (alpha=0.02).

    Deviations are clamped to ±2σ so that outlier frames cannot produce
    arbitrarily large deviation values.
    """

    # ---- construction ----------------------------------------------------- #
    def __init__(self, warmup_seconds: float = 20.0, ema_alpha: float = 0.02) -> None:
        self._warmup_seconds = warmup_seconds
        self._ema_alpha = ema_alpha

        # Warmup sample accumulators
        self._pitch_samples: List[float] = []
        self._rate_samples: List[float] = []
        self._warmup_time_accumulated: float = 0.0

        # Post-warmup baseline values
        self._pitch_baseline: float = 0.0
        self._rate_baseline: float = 0.0
        self._pitch_std: float = 1.0
        self._rate_std: float = 1.0

        self._calibrated: bool = False

    # ---- public API ------------------------------------------------------- #
    @property
    def calibrated(self) -> bool:
        """True once warmup data has been processed and baselines computed."""
        return self._calibrated

    @property
    def pitch_baseline(self) -> float:
        return self._pitch_baseline

    @property
    def rate_baseline(self) -> float:
        return self._rate_baseline

    def update(
        self,
        pitch_hz: float,
        speech_rate: float,
        chunk_duration_seconds: float,
    ) -> None:
        """Feed a new voiced sample into the baseline tracker.

        Args:
            pitch_hz: Fundamental frequency of the chunk in Hz.  Only voiced
                frames (pitch_hz > 0) should be fed; callers must gate this.
            speech_rate: Speech-rate proxy value for the chunk (0-1 range from
                prosody analysis).
            chunk_duration_seconds: Duration of the audio chunk in seconds,
                used to track warmup progress.
        """
        if pitch_hz <= 0:
            return

        if not self._calibrated:
            # Warmup phase — collect unconditionally
            self._pitch_samples.append(pitch_hz)
            self._rate_samples.append(speech_rate)
            self._warmup_time_accumulated += chunk_duration_seconds

            if self._warmup_time_accumulated >= self._warmup_seconds:
                self._finalize_warmup()
        else:
            # Post-warmup — slow EMA adaptation
            self._pitch_baseline += self._ema_alpha * (pitch_hz - self._pitch_baseline)
            self._rate_baseline += self._ema_alpha * (speech_rate - self._rate_baseline)

    def pitch_deviation(self, current_pitch: float) -> float:
        """Return the clamped deviation of *current_pitch* from baseline.

        The deviation is expressed as a ratio relative to baseline, then
        clamped to ±2σ.  Returns 0.0 if not calibrated or pitch is 0.
        """
        if not self._calibrated or current_pitch <= 0:
            return 0.0
        raw = (current_pitch - self._pitch_baseline) / max(self._pitch_std, 1e-6)
        return max(-2.0, min(2.0, raw))

    def speech_rate_deviation(self, current_rate: float) -> float:
        """Return the clamped deviation of *current_rate* from baseline.

        Clamped to ±2σ.  Returns 0.0 if not calibrated.
        """
        if not self._calibrated:
            return 0.0
        raw = (current_rate - self._rate_baseline) / max(self._rate_std, 1e-6)
        return max(-2.0, min(2.0, raw))

    # ---- internals -------------------------------------------------------- #
    def _finalize_warmup(self) -> None:
        """Compute baseline as robust median of warmup samples."""
        if not self._pitch_samples:
            return

        # Use median for robustness against outliers
        sorted_pitch = sorted(self._pitch_samples)
        sorted_rate = sorted(self._rate_samples)
        n = len(sorted_pitch)
        mid = n // 2

        if n % 2 == 0 and n >= 2:
            self._pitch_baseline = (sorted_pitch[mid - 1] + sorted_pitch[mid]) / 2.0
            self._rate_baseline = (sorted_rate[mid - 1] + sorted_rate[mid]) / 2.0
        else:
            self._pitch_baseline = sorted_pitch[mid]
            self._rate_baseline = sorted_rate[mid]

        # Compute standard deviation for clamping
        self._pitch_std = _std(self._pitch_samples, self._pitch_baseline)
        self._rate_std = _std(self._rate_samples, self._rate_baseline)

        self._calibrated = True

        # Free warmup buffers
        self._pitch_samples = []
        self._rate_samples = []


class ParalinguisticAnalyzer:
    """Fuses prosodic deviation signals into a single 0-1 uncertainty score.

    Signal weights (tuned for tutoring sessions):
        - pitch deviation (absolute):  0.35
        - speech rate deviation:       0.25
        - pause ratio:                 0.25
        - trailing energy:             0.15

    The analyzer maintains a per-role SpeakerBaseline.  Feed prosody results
    via ``update()`` and read the latest score via ``last_result``.
    """

    # Signal weights — sum to 1.0
    W_PITCH = 0.35
    W_RATE = 0.25
    W_PAUSE = 0.25
    W_TRAILING = 0.15

    def __init__(self, warmup_seconds: float = 20.0) -> None:
        self._baselines: dict[str, SpeakerBaseline] = {}
        self._warmup_seconds = warmup_seconds
        self._last_result: ParalinguisticResult | None = None

    @property
    def last_result(self) -> ParalinguisticResult | None:
        return self._last_result

    def get_baseline(self, role: str) -> SpeakerBaseline:
        """Return (or create) the baseline tracker for a speaker role."""
        if role not in self._baselines:
            self._baselines[role] = SpeakerBaseline(
                warmup_seconds=self._warmup_seconds,
            )
        return self._baselines[role]

    def update(
        self,
        role: str,
        pitch_hz: float,
        speech_rate: float,
        pause_ratio: float,
        trailing_energy: bool,
        chunk_duration_seconds: float,
    ) -> ParalinguisticResult:
        """Analyze a new prosody frame and return an uncertainty result.

        The speaker baseline is updated first, then deviations are computed
        and fused into a composite score.

        Args:
            role: Speaker role string (e.g. "tutor", "student").
            pitch_hz: Fundamental frequency in Hz (0 if unvoiced).
            speech_rate: Speech rate proxy (0-1).
            pause_ratio: Fraction of chunk that was silence (0-1).
            trailing_energy: True if energy rises toward end of chunk.
            chunk_duration_seconds: Duration of the chunk in seconds.

        Returns:
            ParalinguisticResult with the composite uncertainty score.
        """
        baseline = self.get_baseline(role)

        # Update baseline with voiced data
        if pitch_hz > 0:
            baseline.update(pitch_hz, speech_rate, chunk_duration_seconds)

        # Compute deviations (0.0 when not yet calibrated)
        p_dev = baseline.pitch_deviation(pitch_hz)
        r_dev = baseline.speech_rate_deviation(speech_rate)

        # Convert deviations to 0-1 contributions
        # Absolute pitch deviation — higher |deviation| → more uncertainty
        pitch_score = min(1.0, abs(p_dev) / 2.0)

        # Speech rate: negative deviation (slower) → more uncertainty;
        # positive (faster) → mild uncertainty
        if r_dev < 0:
            rate_score = min(1.0, abs(r_dev) / 2.0)
        else:
            rate_score = min(1.0, abs(r_dev) / 3.0)  # faster speech less uncertain

        # Pause ratio is already 0-1
        pause_score = min(1.0, pause_ratio)

        # Trailing energy is binary
        trailing_score = 1.0 if trailing_energy else 0.0

        # Weighted fusion
        composite = (
            self.W_PITCH * pitch_score
            + self.W_RATE * rate_score
            + self.W_PAUSE * pause_score
            + self.W_TRAILING * trailing_score
        )

        # Clamp to [0, 1]
        composite = max(0.0, min(1.0, composite))

        result = ParalinguisticResult(
            score=composite,
            pitch_deviation=p_dev,
            speech_rate_deviation=r_dev,
            pause_ratio=pause_ratio,
            trailing_energy=trailing_energy,
        )
        self._last_result = result
        return result


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _std(values: List[float], mean: float) -> float:
    """Population standard deviation with a minimum floor."""
    if len(values) < 2:
        return 1.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return max(math.sqrt(variance), 1e-6)
