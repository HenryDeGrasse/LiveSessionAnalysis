"""Tests for SpeakerBaseline: warmup, median computation, EMA, deviation clamping."""
from __future__ import annotations

import pytest

from app.uncertainty.paralinguistic import SpeakerBaseline


class TestWarmupCollectsSamples:
    """During warmup, ALL voiced samples are collected unconditionally."""

    def test_not_calibrated_before_warmup(self):
        baseline = SpeakerBaseline(warmup_seconds=5.0)
        baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert not baseline.calibrated

    def test_calibrated_after_warmup(self):
        baseline = SpeakerBaseline(warmup_seconds=5.0)
        for _ in range(10):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert baseline.calibrated

    def test_exactly_at_warmup_boundary(self):
        baseline = SpeakerBaseline(warmup_seconds=5.0)
        # Feed 5 seconds exactly
        for _ in range(5):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert baseline.calibrated

    def test_zero_pitch_ignored(self):
        """Unvoiced frames (pitch_hz=0) should be ignored."""
        baseline = SpeakerBaseline(warmup_seconds=2.0)
        for _ in range(10):
            baseline.update(pitch_hz=0.0, speech_rate=0.0, chunk_duration_seconds=1.0)
        assert not baseline.calibrated


class TestMedianBaseline:
    """Baseline is computed as robust MEDIAN, not mean."""

    def test_median_with_outlier(self):
        baseline = SpeakerBaseline(warmup_seconds=5.0)
        # 4 samples at 150 Hz, 1 outlier at 500 Hz
        pitches = [150.0, 150.0, 150.0, 150.0, 500.0]
        for p in pitches:
            baseline.update(pitch_hz=p, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert baseline.calibrated
        # Median of [150,150,150,150,500] = 150
        assert baseline.pitch_baseline == 150.0

    def test_median_even_count(self):
        baseline = SpeakerBaseline(warmup_seconds=4.0)
        # 4 samples at 1s each → exactly 4 seconds of warmup with 4 samples
        pitches = [100.0, 200.0, 300.0, 400.0]
        for p in pitches:
            baseline.update(pitch_hz=p, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert baseline.calibrated
        # Median of [100,200,300,400] = (200+300)/2 = 250
        assert baseline.pitch_baseline == 250.0

    def test_median_odd_count(self):
        baseline = SpeakerBaseline(warmup_seconds=2.5)
        pitches = [100.0, 300.0, 200.0]
        for p in pitches:
            baseline.update(pitch_hz=p, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert baseline.calibrated
        # Sorted: [100,200,300], median = 200
        assert baseline.pitch_baseline == 200.0

    def test_rate_baseline_is_median(self):
        baseline = SpeakerBaseline(warmup_seconds=3.0)
        rates = [0.2, 0.8, 0.5]
        for r in rates:
            baseline.update(pitch_hz=150.0, speech_rate=r, chunk_duration_seconds=1.0)
        assert baseline.calibrated
        # Sorted: [0.2, 0.5, 0.8], median = 0.5
        assert baseline.rate_baseline == 0.5


class TestEMAAdaptation:
    """After warmup, baseline updates via slow EMA (alpha=0.02)."""

    def test_ema_moves_toward_new_values(self):
        baseline = SpeakerBaseline(warmup_seconds=2.0, ema_alpha=0.02)
        # Warmup: 2 seconds at 150 Hz
        for _ in range(4):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated
        old_baseline = baseline.pitch_baseline

        # Post-warmup: feed higher pitch
        baseline.update(pitch_hz=200.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        # EMA: new = old + 0.02 * (200 - old) → should increase slightly
        assert baseline.pitch_baseline > old_baseline
        assert baseline.pitch_baseline < 200.0  # but not jump to 200

    def test_ema_slow_convergence(self):
        baseline = SpeakerBaseline(warmup_seconds=1.0, ema_alpha=0.02)
        # Warmup
        for _ in range(2):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated
        initial = baseline.pitch_baseline

        # Many updates at 200 Hz — baseline should converge slowly
        for _ in range(50):
            baseline.update(pitch_hz=200.0, speech_rate=0.5, chunk_duration_seconds=0.5)

        # After 50 updates: new ≈ 150 + (200-150)*(1 - 0.98^50) ≈ 150 + 50*0.636 ≈ 181.8
        assert baseline.pitch_baseline > initial
        assert baseline.pitch_baseline < 200.0


class TestDeviationClamping:
    """Deviations are clamped to ±2σ."""

    def test_deviation_clamped_high(self):
        baseline = SpeakerBaseline(warmup_seconds=2.0)
        # All samples at 150 Hz → very small std
        for _ in range(4):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated

        # Extreme pitch should clamp to +2.0
        dev = baseline.pitch_deviation(1000.0)
        assert dev == 2.0

    def test_deviation_clamped_low(self):
        baseline = SpeakerBaseline(warmup_seconds=2.0)
        for _ in range(4):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated

        dev = baseline.pitch_deviation(10.0)
        assert dev == -2.0

    def test_deviation_within_range_not_clamped(self):
        baseline = SpeakerBaseline(warmup_seconds=2.0)
        # Varied samples to get a meaningful std
        for p in [140.0, 150.0, 160.0, 150.0]:
            baseline.update(pitch_hz=p, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated

        # Small deviation should not be clamped
        dev = baseline.pitch_deviation(155.0)
        assert -2.0 < dev < 2.0

    def test_speech_rate_deviation_clamped(self):
        baseline = SpeakerBaseline(warmup_seconds=1.0)
        for _ in range(2):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated

        dev = baseline.speech_rate_deviation(100.0)
        assert dev == 2.0

        dev = baseline.speech_rate_deviation(-100.0)
        assert dev == -2.0


class TestCalibratedFlag:
    """The calibrated flag transitions correctly."""

    def test_starts_uncalibrated(self):
        baseline = SpeakerBaseline()
        assert not baseline.calibrated

    def test_stays_calibrated_after_more_updates(self):
        baseline = SpeakerBaseline(warmup_seconds=1.0)
        for _ in range(2):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated

        # More updates should not un-calibrate
        for _ in range(10):
            baseline.update(pitch_hz=200.0, speech_rate=0.3, chunk_duration_seconds=0.5)
        assert baseline.calibrated

    def test_deviation_zero_when_uncalibrated(self):
        baseline = SpeakerBaseline(warmup_seconds=10.0)
        baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=1.0)
        assert not baseline.calibrated
        assert baseline.pitch_deviation(200.0) == 0.0
        assert baseline.speech_rate_deviation(0.9) == 0.0

    def test_deviation_zero_for_zero_pitch(self):
        baseline = SpeakerBaseline(warmup_seconds=1.0)
        for _ in range(2):
            baseline.update(pitch_hz=150.0, speech_rate=0.5, chunk_duration_seconds=0.5)
        assert baseline.calibrated
        assert baseline.pitch_deviation(0.0) == 0.0
