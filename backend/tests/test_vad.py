import numpy as np
import pytest

from app.audio_processor.vad import VoiceActivityDetector
from app.audio_processor.prosody import analyze_prosody
from app.audio_processor.pipeline import AudioProcessor


@pytest.fixture
def vad():
    return VoiceActivityDetector(aggressiveness=2)


def _make_silence(duration_ms=30, sample_rate=16000):
    """Create silent PCM audio (zeros)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = np.zeros(n_samples, dtype=np.int16)
    return samples.tobytes()


def _make_noise(duration_ms=30, sample_rate=16000, amplitude=5000):
    """Create noisy PCM audio (simulates speech-like signal)."""
    n_samples = int(sample_rate * duration_ms / 1000)
    # Generate a mix of sine waves to simulate speech
    t = np.arange(n_samples) / sample_rate
    signal = amplitude * (
        np.sin(2 * np.pi * 200 * t)
        + 0.5 * np.sin(2 * np.pi * 400 * t)
        + 0.3 * np.sin(2 * np.pi * 800 * t)
    )
    samples = signal.astype(np.int16)
    return samples.tobytes()


def test_silence_is_not_speech(vad):
    """Silence should not be detected as speech."""
    chunk = _make_silence(duration_ms=30)
    assert vad.is_speech(chunk) is False


def test_noise_detection(vad):
    """Loud structured signal may or may not be speech, but should not crash."""
    chunk = _make_noise(duration_ms=30, amplitude=10000)
    result = vad.is_speech(chunk)
    assert isinstance(result, bool)


def test_invalid_chunk_size(vad):
    """Invalid chunk sizes should be handled gracefully."""
    # Too short
    result = vad.is_speech(b'\x00' * 100)
    assert isinstance(result, bool)

    # Too long
    result = vad.is_speech(b'\x00' * 2000)
    assert isinstance(result, bool)


def test_prosody_silence():
    """Prosody analysis of silence should return low energy."""
    chunk = _make_silence(duration_ms=30)
    result = analyze_prosody(chunk)
    assert result.rms_energy == 0.0
    assert result.zero_crossing_rate == 0.0


def test_prosody_noise():
    """Prosody analysis of noise should return positive energy."""
    chunk = _make_noise(duration_ms=30, amplitude=10000)
    result = analyze_prosody(chunk)
    assert result.rms_energy > 0.0


def test_prosody_values_in_range():
    """All prosody values should be normalized to [0, 1]."""
    chunk = _make_noise(duration_ms=30, amplitude=20000)
    result = analyze_prosody(chunk)
    assert 0.0 <= result.rms_energy <= 1.0
    assert 0.0 <= result.zero_crossing_rate <= 1.0
    assert 0.0 <= result.speech_rate_proxy <= 1.0


def test_audio_pipeline():
    """AudioProcessor should process chunks without errors."""
    processor = AudioProcessor()
    silence = _make_silence(duration_ms=30)
    result = processor.process_chunk(silence)
    assert result.is_speech is False
    assert result.processing_ms >= 0
    assert result.prosody.rms_energy == 0.0


def test_force_muted_suppresses_speech():
    processor = AudioProcessor()
    noisy = _make_noise(duration_ms=30, amplitude=15000)
    result = processor.process_chunk(noisy, force_muted=True)
    assert result.is_speech is False
    assert result.raw_vad is False


def test_empty_chunk():
    """Empty chunk should be handled gracefully."""
    result = analyze_prosody(b'')
    assert result.rms_energy == 0.0
