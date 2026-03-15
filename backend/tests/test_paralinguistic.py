"""Tests for ParalinguisticAnalyzer: score fusion, noise robustness."""
from __future__ import annotations

import pytest

from app.uncertainty.paralinguistic import ParalinguisticAnalyzer, SpeakerBaseline


def _warmup_analyzer(
    analyzer: ParalinguisticAnalyzer,
    role: str = "student",
    pitch_hz: float = 150.0,
    speech_rate: float = 0.5,
    warmup_seconds: float = 20.0,
    chunk_duration: float = 0.5,
) -> None:
    """Feed enough voiced frames to complete warmup."""
    n_chunks = int(warmup_seconds / chunk_duration) + 1
    for _ in range(n_chunks):
        analyzer.update(
            role=role,
            pitch_hz=pitch_hz,
            speech_rate=speech_rate,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=chunk_duration,
        )


class TestHighPitchDeviationHigherScore:
    """High pitch deviation from baseline should produce a higher uncertainty score."""

    def test_elevated_pitch_increases_score(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(analyzer, warmup_seconds=5.0, pitch_hz=150.0)

        # Normal pitch — low score
        normal = analyzer.update(
            role="student",
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        # Very high pitch — deviation should raise score
        high = analyzer.update(
            role="student",
            pitch_hz=300.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        assert high.score > normal.score
        assert abs(high.pitch_deviation) > abs(normal.pitch_deviation)

    def test_very_low_pitch_also_increases_score(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(analyzer, warmup_seconds=5.0, pitch_hz=200.0)

        normal = analyzer.update(
            role="student",
            pitch_hz=200.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        low = analyzer.update(
            role="student",
            pitch_hz=80.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        assert low.score > normal.score


class TestMonotoneLowerScore:
    """Monotone speech (no deviation) should yield a lower uncertainty score."""

    def test_steady_pitch_low_score(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(
            analyzer, warmup_seconds=5.0, pitch_hz=150.0, speech_rate=0.5,
        )

        result = analyzer.update(
            role="student",
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.0,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        # With zero deviation, zero pause, no trailing — score should be very low
        assert result.score < 0.1

    def test_consistent_speech_rate_low_score(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(
            analyzer, warmup_seconds=5.0, pitch_hz=150.0, speech_rate=0.5,
        )

        result = analyzer.update(
            role="student",
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.05,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        assert result.score < 0.15


class TestNoiseRobustness:
    """The analyzer should be resilient to occasional noisy frames."""

    def test_single_outlier_does_not_dominate(self):
        # Use varied warmup pitches to get a meaningful std
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        pitches_warmup = [140.0, 145.0, 150.0, 155.0, 160.0,
                          142.0, 148.0, 152.0, 158.0, 147.0, 153.0]
        for p in pitches_warmup:
            analyzer.update(
                role="student", pitch_hz=p, speech_rate=0.5,
                pause_ratio=0.1, trailing_energy=False,
                chunk_duration_seconds=0.5,
            )

        scores = []
        # Many normal frames at baseline
        for _ in range(10):
            r = analyzer.update(
                role="student",
                pitch_hz=150.0,
                speech_rate=0.5,
                pause_ratio=0.1,
                trailing_energy=False,
                chunk_duration_seconds=0.5,
            )
            scores.append(r.score)

        # One extreme outlier — pitch far from baseline
        outlier = analyzer.update(
            role="student",
            pitch_hz=500.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        # Next normal frame — score should return to normal levels
        recovered = analyzer.update(
            role="student",
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        # The outlier frame should have higher score than the recovered frame
        assert outlier.score > recovered.score
        # Score should be reasonably close to pre-outlier levels
        # (EMA shifts baseline slightly after the outlier, so allow some drift)
        avg_normal = sum(scores) / len(scores)
        assert abs(recovered.score - avg_normal) < 0.2

    def test_unvoiced_frame_does_not_crash(self):
        """Pitch=0 (unvoiced) should be handled gracefully."""
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(analyzer, warmup_seconds=5.0, pitch_hz=150.0)

        result = analyzer.update(
            role="student",
            pitch_hz=0.0,
            speech_rate=0.0,
            pause_ratio=0.5,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )

        assert 0.0 <= result.score <= 1.0
        assert result.pitch_deviation == 0.0


class TestScoreBounds:
    """The uncertainty score should always be in [0, 1]."""

    def test_all_signals_max(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=2.0)
        _warmup_analyzer(analyzer, warmup_seconds=2.0, pitch_hz=150.0)

        result = analyzer.update(
            role="student",
            pitch_hz=500.0,
            speech_rate=0.0,
            pause_ratio=1.0,
            trailing_energy=True,
            chunk_duration_seconds=0.5,
        )
        assert 0.0 <= result.score <= 1.0

    def test_all_signals_min(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=2.0)
        _warmup_analyzer(analyzer, warmup_seconds=2.0, pitch_hz=150.0, speech_rate=0.5)

        result = analyzer.update(
            role="student",
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.0,
            trailing_energy=False,
            chunk_duration_seconds=0.5,
        )
        assert 0.0 <= result.score <= 1.0


class TestMultipleRoles:
    """Each role gets its own baseline."""

    def test_independent_baselines(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(analyzer, role="tutor", warmup_seconds=5.0, pitch_hz=100.0)
        _warmup_analyzer(analyzer, role="student", warmup_seconds=5.0, pitch_hz=200.0)

        tutor_baseline = analyzer.get_baseline("tutor")
        student_baseline = analyzer.get_baseline("student")

        assert tutor_baseline.pitch_baseline == pytest.approx(100.0, abs=5.0)
        assert student_baseline.pitch_baseline == pytest.approx(200.0, abs=5.0)


class TestLastResult:
    """The last_result property tracks the most recent analysis."""

    def test_none_initially(self):
        analyzer = ParalinguisticAnalyzer()
        assert analyzer.last_result is None

    def test_updates_after_call(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=1.0)
        result = analyzer.update(
            role="student",
            pitch_hz=150.0,
            speech_rate=0.5,
            pause_ratio=0.1,
            trailing_energy=False,
            chunk_duration_seconds=1.0,
        )
        assert analyzer.last_result is result


class TestPauseAndTrailingContributions:
    """Pause ratio and trailing energy independently raise the score."""

    def test_high_pause_ratio_increases_score(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(analyzer, warmup_seconds=5.0, pitch_hz=150.0)

        low_pause = analyzer.update(
            role="student", pitch_hz=150.0, speech_rate=0.5,
            pause_ratio=0.0, trailing_energy=False, chunk_duration_seconds=0.5,
        )
        high_pause = analyzer.update(
            role="student", pitch_hz=150.0, speech_rate=0.5,
            pause_ratio=0.8, trailing_energy=False, chunk_duration_seconds=0.5,
        )
        assert high_pause.score > low_pause.score

    def test_trailing_energy_increases_score(self):
        analyzer = ParalinguisticAnalyzer(warmup_seconds=5.0)
        _warmup_analyzer(analyzer, warmup_seconds=5.0, pitch_hz=150.0)

        no_trailing = analyzer.update(
            role="student", pitch_hz=150.0, speech_rate=0.5,
            pause_ratio=0.1, trailing_energy=False, chunk_duration_seconds=0.5,
        )
        with_trailing = analyzer.update(
            role="student", pitch_hz=150.0, speech_rate=0.5,
            pause_ratio=0.1, trailing_energy=True, chunk_duration_seconds=0.5,
        )
        assert with_trailing.score > no_trailing.score
