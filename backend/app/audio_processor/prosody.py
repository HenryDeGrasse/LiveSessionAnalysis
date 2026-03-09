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


def analyze_prosody(
    pcm_chunk: bytes,
    sample_rate: int = 16000,
) -> ProsodyResult:
    """Analyze prosodic features from a PCM audio chunk.

    Args:
        pcm_chunk: Raw PCM bytes (16-bit signed, little-endian, mono).
        sample_rate: Audio sample rate in Hz.

    Returns:
        ProsodyResult with energy, zero-crossing rate, and speech rate proxy.
    """
    # Convert bytes to numpy array
    samples = np.frombuffer(pcm_chunk, dtype=np.int16).astype(np.float32)

    if len(samples) == 0:
        return ProsodyResult(
            rms_energy=0.0,
            rms_db=-100.0,
            zero_crossing_rate=0.0,
            speech_rate_proxy=0.0,
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

    return ProsodyResult(
        rms_energy=rms_normalized,
        rms_db=rms_db,
        zero_crossing_rate=zcr,
        speech_rate_proxy=speech_rate_proxy,
    )
