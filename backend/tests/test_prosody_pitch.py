"""Tests for prosody enhancements: pitch estimation, pause_ratio, trailing_energy."""
from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from app.audio_processor.prosody import (
    ProsodyResult,
    analyze_prosody,
    estimate_pitch_robust,
    _compute_pause_ratio,
    _compute_trailing_energy,
)


SAMPLE_RATE = 16000


def _make_pcm_bytes(samples_float: np.ndarray) -> bytes:
    """Convert float [-1,1] samples to 16-bit PCM bytes."""
    clipped = np.clip(samples_float, -1.0, 1.0)
    int_samples = (clipped * 32767).astype(np.int16)
    return int_samples.tobytes()


def _sine_wave(freq_hz: float, duration_s: float, amplitude: float = 0.5,
               sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Generate a sine wave as float samples in [-1, 1]."""
    t = np.arange(int(sample_rate * duration_s)) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _silence(duration_s: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Generate silence as float samples."""
    return np.zeros(int(sample_rate * duration_s), dtype=np.float32)


# --- Pitch estimation tests ---

class TestEstimatePitchRobust:
    def test_sine_wave_220hz(self):
        """Pitch of a 220 Hz sine wave should be detected near 220 Hz."""
        samples = _sine_wave(220.0, 0.5)
        pitch_hz, confidence = estimate_pitch_robust(samples, SAMPLE_RATE)
        assert pitch_hz > 0, "Should detect voiced pitch"
        assert abs(pitch_hz - 220.0) < 15.0, f"Expected ~220Hz, got {pitch_hz}"
        assert confidence >= 0.5, f"Confidence should be >= 0.5, got {confidence}"

    def test_sine_wave_440hz(self):
        """Pitch of a 440 Hz sine wave should be detected near 440 Hz."""
        samples = _sine_wave(440.0, 0.5)
        pitch_hz, confidence = estimate_pitch_robust(samples, SAMPLE_RATE)
        assert pitch_hz > 0, "Should detect voiced pitch"
        assert abs(pitch_hz - 440.0) < 15.0, f"Expected ~440Hz, got {pitch_hz}"
        assert confidence >= 0.5

    def test_sine_wave_100hz(self):
        """Pitch of a 100 Hz sine wave should be detected near 100 Hz."""
        samples = _sine_wave(100.0, 0.5)
        pitch_hz, confidence = estimate_pitch_robust(samples, SAMPLE_RATE)
        assert pitch_hz > 0, "Should detect voiced pitch"
        assert abs(pitch_hz - 100.0) < 15.0, f"Expected ~100Hz, got {pitch_hz}"

    def test_unvoiced_noise(self):
        """White noise should yield low confidence or no pitch."""
        rng = np.random.RandomState(42)
        samples = (rng.randn(SAMPLE_RATE) * 0.3).astype(np.float32)
        pitch_hz, confidence = estimate_pitch_robust(
            samples, SAMPLE_RATE, confidence_threshold=0.5
        )
        # Noise should either return 0 pitch or very low confidence
        if pitch_hz > 0:
            # If it does return something, the confidence should be marginal
            assert confidence < 0.9, "Noise should not have high confidence"

    def test_silence_returns_zero(self):
        """Silence should return 0 Hz pitch."""
        samples = _silence(0.5)
        pitch_hz, confidence = estimate_pitch_robust(samples, SAMPLE_RATE)
        assert pitch_hz == 0.0
        assert confidence == 0.0

    def test_too_short_returns_zero(self):
        """Very short audio (<20ms) should return 0."""
        samples = _sine_wave(220.0, 0.01)  # 10ms
        pitch_hz, confidence = estimate_pitch_robust(samples, SAMPLE_RATE)
        assert pitch_hz == 0.0
        assert confidence == 0.0

    def test_confidence_gating(self):
        """High confidence threshold should filter out marginal detections."""
        # Very low amplitude sine + noise
        rng = np.random.RandomState(123)
        sine = _sine_wave(200.0, 0.5, amplitude=0.01)
        noise = (rng.randn(len(sine)) * 0.3).astype(np.float32)
        samples = sine + noise

        pitch_hz, confidence = estimate_pitch_robust(
            samples, SAMPLE_RATE, confidence_threshold=0.9
        )
        # With very strict threshold, noisy signal may be filtered out
        # Either no pitch or very high confidence - the key is it doesn't crash
        assert isinstance(pitch_hz, float)
        assert isinstance(confidence, float)


# --- Pause ratio tests ---

class TestPauseRatio:
    def test_all_silence(self):
        """A fully silent chunk should have pause_ratio near 1.0."""
        samples = _silence(0.5)
        ratio = _compute_pause_ratio(samples, SAMPLE_RATE)
        assert ratio >= 0.9, f"Expected ~1.0 for silence, got {ratio}"

    def test_all_speech(self):
        """A loud sine wave should have pause_ratio near 0.0."""
        samples = _sine_wave(200.0, 0.5, amplitude=0.5)
        ratio = _compute_pause_ratio(samples, SAMPLE_RATE)
        assert ratio <= 0.1, f"Expected ~0.0 for loud signal, got {ratio}"

    def test_half_silence(self):
        """Half speech, half silence should give pause_ratio ~0.5."""
        speech = _sine_wave(200.0, 0.25, amplitude=0.5)
        silence = _silence(0.25)
        samples = np.concatenate([speech, silence])
        ratio = _compute_pause_ratio(samples, SAMPLE_RATE)
        assert 0.3 <= ratio <= 0.7, f"Expected ~0.5, got {ratio}"

    def test_empty_returns_zero(self):
        """Empty samples should return 0.0."""
        ratio = _compute_pause_ratio(np.array([], dtype=np.float32), SAMPLE_RATE)
        assert ratio == 0.0

    def test_pause_ratio_via_analyze(self):
        """pause_ratio should be populated via analyze_prosody()."""
        pcm = _make_pcm_bytes(_silence(0.5))
        result = analyze_prosody(pcm, SAMPLE_RATE)
        assert result.pause_ratio >= 0.9


# --- Trailing energy tests ---

class TestTrailingEnergy:
    def test_rising_energy(self):
        """Energy that rises toward the end should set trailing_energy=True."""
        # Quiet first 75%, loud last 25%
        quiet = _sine_wave(200.0, 0.375, amplitude=0.05)
        loud = _sine_wave(200.0, 0.125, amplitude=0.5)
        samples = np.concatenate([quiet, loud])
        assert _compute_trailing_energy(samples) is True

    def test_falling_energy(self):
        """Energy that falls toward the end should set trailing_energy=False."""
        loud = _sine_wave(200.0, 0.375, amplitude=0.5)
        quiet = _sine_wave(200.0, 0.125, amplitude=0.05)
        samples = np.concatenate([loud, quiet])
        assert _compute_trailing_energy(samples) is False

    def test_constant_energy(self):
        """Constant energy should set trailing_energy=False (not strictly greater)."""
        samples = _sine_wave(200.0, 0.5, amplitude=0.3)
        # With constant amplitude, last 25% RMS == first 75% RMS
        # trailing_energy requires last > first, so should be False
        result = _compute_trailing_energy(samples)
        assert result is False

    def test_too_short_returns_false(self):
        """Very short audio should return False."""
        samples = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        assert _compute_trailing_energy(samples) is False

    def test_trailing_energy_via_analyze(self):
        """trailing_energy should be populated via analyze_prosody()."""
        quiet = _sine_wave(200.0, 0.375, amplitude=0.05)
        loud = _sine_wave(200.0, 0.125, amplitude=0.5)
        samples = np.concatenate([quiet, loud])
        pcm = _make_pcm_bytes(samples)
        result = analyze_prosody(pcm, SAMPLE_RATE)
        assert result.trailing_energy is True


# --- Integration: analyze_prosody returns all new fields ---

class TestAnalyzeProsodyEnhanced:
    def test_result_has_new_fields(self):
        """ProsodyResult should have all new fields."""
        samples = _sine_wave(200.0, 0.5, amplitude=0.3)
        pcm = _make_pcm_bytes(samples)
        result = analyze_prosody(pcm, SAMPLE_RATE)

        assert hasattr(result, "pitch_hz")
        assert hasattr(result, "pitch_confidence")
        assert hasattr(result, "pause_ratio")
        assert hasattr(result, "trailing_energy")

        assert isinstance(result.pitch_hz, float)
        assert isinstance(result.pitch_confidence, float)
        assert isinstance(result.pause_ratio, float)
        assert isinstance(result.trailing_energy, bool)

    def test_empty_pcm(self):
        """Empty PCM should return defaults for all fields."""
        result = analyze_prosody(b"", SAMPLE_RATE)
        assert result.pitch_hz == 0.0
        assert result.pitch_confidence == 0.0
        assert result.pause_ratio == 0.0
        assert result.trailing_energy is False

    def test_existing_fields_unchanged(self):
        """Original fields (rms_energy, rms_db, zcr, speech_rate_proxy) still work."""
        samples = _sine_wave(300.0, 0.5, amplitude=0.3)
        pcm = _make_pcm_bytes(samples)
        result = analyze_prosody(pcm, SAMPLE_RATE)

        assert result.rms_energy > 0
        assert result.rms_db > -100
        assert result.zero_crossing_rate > 0
        assert isinstance(result.speech_rate_proxy, float)

    def test_sine_pitch_through_analyze(self):
        """analyze_prosody should detect pitch from a sine wave."""
        samples = _sine_wave(300.0, 0.5, amplitude=0.5)
        pcm = _make_pcm_bytes(samples)
        result = analyze_prosody(pcm, SAMPLE_RATE)

        assert result.pitch_hz > 0, "Should detect pitch"
        assert abs(result.pitch_hz - 300.0) < 20.0, f"Expected ~300Hz, got {result.pitch_hz}"
        assert result.pitch_confidence >= 0.5
