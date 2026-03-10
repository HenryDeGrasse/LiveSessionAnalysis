from __future__ import annotations

import webrtcvad


class VoiceActivityDetector:
    """Wrapper around webrtcvad for per-participant voice activity detection.

    Expects 16kHz, mono, 16-bit PCM audio in 10, 20, or 30ms chunks.
    """

    def __init__(self, aggressiveness: int = 2):
        """Initialize VAD.

        Args:
            aggressiveness: 0-3, higher = more aggressive filtering.
                Mode 2 is balanced for tutoring sessions.
        """
        self._vad = webrtcvad.Vad(aggressiveness)
        self._sample_rate = 16000

    def is_speech(self, pcm_chunk: bytes) -> bool:
        """Determine if an audio chunk contains speech.

        Args:
            pcm_chunk: Raw PCM bytes (16-bit signed, little-endian, 16kHz mono).
                Must be 10, 20, or 30ms (320, 640, or 960 bytes).

        Returns:
            True if the chunk contains speech.
        """
        if len(pcm_chunk) not in (320, 640, 960):
            # Invalid chunk size — pad up to the nearest valid frame size
            # so we don't discard valid audio samples by truncating down.
            if len(pcm_chunk) <= 320:
                pcm_chunk = pcm_chunk + b'\x00' * (320 - len(pcm_chunk))
            elif len(pcm_chunk) <= 640:
                pcm_chunk = pcm_chunk + b'\x00' * (640 - len(pcm_chunk))
            elif len(pcm_chunk) <= 960:
                pcm_chunk = pcm_chunk + b'\x00' * (960 - len(pcm_chunk))
            else:
                pcm_chunk = pcm_chunk[:960]

        try:
            return self._vad.is_speech(pcm_chunk, self._sample_rate)
        except Exception:
            return False
