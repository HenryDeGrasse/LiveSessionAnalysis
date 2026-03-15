from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class ProsodyResult:
    """Result of prosody analysis on an audio chunk."""
    rms_energy: float  # Root mean square energy (0-1 normalized)
    rms_db: float  # Raw RMS level in dBFS-like units
    zero_crossing_rate: float  # Fraction of signal zero-crossings
    speech_rate_proxy: float  # Estimated syllable rate proxy (energy peaks per second)
    pitch_hz: float = 0.0  # Estimated fundamental frequency in Hz (0 if unvoiced)
    pitch_confidence: float = 0.0  # Confidence of pitch estimate (0-1)
    pause_ratio: float = 0.0  # Fraction of chunk that is silence within speech
    trailing_energy: bool = False  # True if energy in last 25% > energy in first 75%


def _median_filter_1d(values: np.ndarray, kernel_size: int = 5) -> np.ndarray:
    """Apply a lightweight edge-padded median filter."""
    if len(values) == 0 or kernel_size <= 1:
        return values

    kernel_size = max(1, kernel_size)
    if kernel_size % 2 == 0:
        kernel_size += 1

    pad = kernel_size // 2
    padded = np.pad(values, (pad, pad), mode="edge")
    filtered = np.empty_like(values)
    for idx in range(len(values)):
        filtered[idx] = np.median(padded[idx : idx + kernel_size])
    return filtered



def estimate_pitch_robust(
    samples: np.ndarray,
    sample_rate: int = 16000,
    pitch_floor: float = 80.0,
    pitch_ceiling: float = 500.0,
    confidence_threshold: float = 0.5,
) -> tuple[float, float]:
    """Estimate pitch using parselmouth with robust noise handling.

    Uses Praat's autocorrelation-based pitch tracker via parselmouth.
    Applies median filtering across voiced frames and ignores unvoiced frames.

    Args:
        samples: Normalized audio samples in [-1, 1] range.
        sample_rate: Audio sample rate in Hz.
        pitch_floor: Minimum pitch search range in Hz.
        pitch_ceiling: Maximum pitch search range in Hz.
        confidence_threshold: Minimum confidence to consider a frame voiced.

    Returns:
        Tuple of (pitch_hz, confidence). pitch_hz is 0.0 if unvoiced or
        confidence is below threshold.
    """
    # Praat requires duration >= 3 / pitch_floor for autocorrelation analysis.
    # Check before importing parselmouth to avoid expensive cold-start on
    # short chunks (the import alone can take >100ms the first time).
    min_duration_samples = max(
        int(sample_rate * 0.02),  # At least 20ms
        int(sample_rate * 3.0 / pitch_floor) + 1,  # Praat AC requirement
    )
    if len(samples) < min_duration_samples:
        return 0.0, 0.0

    try:
        import parselmouth
    except ImportError:
        return 0.0, 0.0

    snd = parselmouth.Sound(samples.astype(np.float64), sampling_frequency=sample_rate)

    try:
        pitch = snd.to_pitch_ac(
            time_step=0.01,
            pitch_floor=pitch_floor,
            pitch_ceiling=pitch_ceiling,
            very_accurate=True,
        )
    except Exception:
        return 0.0, 0.0

    pitch_values = pitch.selected_array["frequency"]
    strengths = pitch.selected_array["strength"]

    if len(pitch_values) == 0:
        return 0.0, 0.0

    voiced_mask = (pitch_values > 0) & (strengths >= confidence_threshold)
    if not np.any(voiced_mask):
        return 0.0, 0.0

    voiced_pitches = pitch_values[voiced_mask].astype(np.float64)
    voiced_strengths = strengths[voiced_mask].astype(np.float64)

    filtered_pitches = _median_filter_1d(voiced_pitches, kernel_size=5)
    median_pitch = float(np.median(filtered_pitches))
    mean_confidence = float(np.mean(voiced_strengths))

    if mean_confidence < confidence_threshold:
        return 0.0, mean_confidence

    return median_pitch, mean_confidence


def _compute_pause_ratio(
    samples: np.ndarray,
    sample_rate: int = 16000,
    silence_threshold_db: float = -40.0,
    frame_duration_ms: float = 20.0,
) -> float:
    """Compute the fraction of a chunk that is silence within speech.

    Analyzes short frames and counts what fraction falls below the
    silence energy threshold.

    Args:
        samples: Normalized audio samples in [-1, 1] range.
        sample_rate: Audio sample rate in Hz.
        silence_threshold_db: Energy threshold in dB below which a frame
            is considered silence.
        frame_duration_ms: Frame size in milliseconds for analysis.

    Returns:
        Fraction of frames that are silent (0.0-1.0).
    """
    if len(samples) == 0:
        return 0.0

    frame_size = max(1, int(sample_rate * frame_duration_ms / 1000.0))
    n_frames = len(samples) // frame_size

    if n_frames == 0:
        return 0.0

    silent_frames = 0
    for i in range(n_frames):
        frame = samples[i * frame_size : (i + 1) * frame_size]
        frame_rms = float(np.sqrt(np.mean(frame ** 2)))
        frame_db = 20.0 * math.log10(max(frame_rms, 1e-10))
        if frame_db < silence_threshold_db:
            silent_frames += 1

    return silent_frames / n_frames


def _compute_trailing_energy(
    samples: np.ndarray,
) -> bool:
    """Check if energy in the last 25% of the chunk exceeds the first 75%.

    This can indicate rising energy patterns such as questions or
    uncertainty.

    Args:
        samples: Normalized audio samples in [-1, 1] range.

    Returns:
        True if the trailing 25% has higher RMS energy than the leading 75%.
    """
    if len(samples) < 4:
        return False

    split_point = int(len(samples) * 0.75)
    first_part = samples[:split_point]
    last_part = samples[split_point:]

    first_rms = float(np.sqrt(np.mean(first_part ** 2)))
    last_rms = float(np.sqrt(np.mean(last_part ** 2)))

    return last_rms > first_rms


def analyze_prosody(
    pcm_chunk: bytes,
    sample_rate: int = 16000,
) -> ProsodyResult:
    """Analyze prosodic features from a PCM audio chunk.

    Args:
        pcm_chunk: Raw PCM bytes (16-bit signed, little-endian, mono).
        sample_rate: Audio sample rate in Hz.

    Returns:
        ProsodyResult with energy, zero-crossing rate, speech rate proxy,
        pitch, pause_ratio, and trailing_energy.
    """
    # Convert bytes to numpy array
    samples = np.frombuffer(pcm_chunk, dtype=np.int16).astype(np.float32)

    if len(samples) == 0:
        return ProsodyResult(
            rms_energy=0.0,
            rms_db=-100.0,
            zero_crossing_rate=0.0,
            speech_rate_proxy=0.0,
            pitch_hz=0.0,
            pitch_confidence=0.0,
            pause_ratio=0.0,
            trailing_energy=False,
        )

    # Normalize to [-1, 1]
    samples = samples / 32768.0

    # RMS energy
    rms = float(np.sqrt(np.mean(samples ** 2)))
    rms_db = 20.0 * math.log10(max(rms, 1e-6))
    # Normalize: typical speech RMS is 0.01-0.3
    rms_normalized = min(1.0, rms / 0.3)

    # Zero-crossing rate
    signs = np.sign(samples)
    sign_changes = np.abs(np.diff(signs))
    zcr = float(np.sum(sign_changes > 0)) / len(samples) if len(samples) > 1 else 0.0

    # Speech rate proxy: count energy peaks in the chunk
    # Use a simple envelope follower and count peaks
    chunk_duration_s = len(samples) / sample_rate
    if chunk_duration_s < 0.01:
        speech_rate_proxy = 0.0
    else:
        # Compute short-time energy in small windows
        window_size = max(1, int(sample_rate * 0.02))  # 20ms windows
        n_windows = max(1, len(samples) // window_size)
        energies = []
        for i in range(n_windows):
            window = samples[i * window_size : (i + 1) * window_size]
            energies.append(float(np.mean(window ** 2)))

        # Count peaks (local maxima above threshold)
        if len(energies) < 3:
            peak_count = 0
        else:
            threshold = np.mean(energies) * 0.5
            peak_count = 0
            for i in range(1, len(energies) - 1):
                if (
                    energies[i] > energies[i - 1]
                    and energies[i] > energies[i + 1]
                    and energies[i] > threshold
                ):
                    peak_count += 1

        # Normalize to syllables per second (typical: 3-6 syl/s)
        speech_rate_proxy = min(1.0, (peak_count / chunk_duration_s) / 8.0)

    # Pitch estimation (robust, using parselmouth)
    pitch_hz, pitch_confidence = estimate_pitch_robust(samples, sample_rate)

    # Pause ratio: fraction of chunk that is silence
    pause_ratio = _compute_pause_ratio(samples, sample_rate)

    # Trailing energy: does energy rise toward end of chunk?
    trailing_energy = _compute_trailing_energy(samples)

    return ProsodyResult(
        rms_energy=rms_normalized,
        rms_db=rms_db,
        zero_crossing_rate=zcr,
        speech_rate_proxy=speech_rate_proxy,
        pitch_hz=pitch_hz,
        pitch_confidence=pitch_confidence,
        pause_ratio=pause_ratio,
        trailing_energy=trailing_energy,
    )
