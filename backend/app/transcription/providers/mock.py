"""Mock STT providers for testing.

:class:`MockSTTProvider` simulates a streaming STT service:
  - Accepts audio chunks.
  - Emits configurable partial / is_final / speech_final responses.
  - Simulates ``speech_final`` after a configurable silence gap.

:class:`SlowMockProvider` adds per-``send_audio`` delay to exercise
back-pressure and mid-injection cancel paths.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional

from app.transcription.models import ProviderResponse, WordTiming


@dataclass
class MockSTTConfig:
    """Tuning knobs for :class:`MockSTTProvider`."""

    # After this many audio chunks without new audio, emit speech_final.
    silence_chunks_for_speech_final: int = 3
    # Simulated per-word confidence.
    default_confidence: float = 0.95
    # When True, emit a partial before every final.
    emit_partials: bool = True
    # Artificial latency (seconds) added to each ``send_audio`` call.
    send_delay_s: float = 0.0
    # Language code placed on every response.
    language: str = "en"
    # Pre-canned responses; if provided they are yielded in order and the
    # automatic word-generation logic is bypassed.
    canned_responses: List[ProviderResponse] = field(default_factory=list)


class MockSTTProvider:
    """In-process mock that satisfies :class:`STTProviderClient`.

    Useful for deterministic unit / integration tests that should not depend
    on a live STT service.
    """

    def __init__(self, config: Optional[MockSTTConfig] = None) -> None:
        self._cfg = config or MockSTTConfig()
        self._connected = False
        self._closed = False
        self._finalized = False
        self._stream_closed = False

        # Internal bookkeeping
        self._audio_chunks: List[bytes] = []
        self._silence_counter = 0
        self._utterance_counter = 0
        self._current_words: List[str] = []
        self._time_cursor: float = 0.0  # simulated clock in seconds

        # Response queue consumed by ``receive_results``
        self._result_queue: asyncio.Queue[Optional[ProviderResponse]] = asyncio.Queue()

        # Canned-response index
        self._canned_idx = 0

    # -- Protocol methods -----------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            raise RuntimeError("MockSTTProvider already connected")
        self._connected = True

    async def send_audio(self, pcm_chunk: bytes) -> None:
        self._ensure_connected()
        if self._cfg.send_delay_s > 0:
            await asyncio.sleep(self._cfg.send_delay_s)
        self._audio_chunks.append(pcm_chunk)
        self._silence_counter = 0

        # Generate simulated transcript words from chunk length
        word = f"word{len(self._audio_chunks)}"
        self._current_words.append(word)

        # If we have canned responses, use those instead
        if self._cfg.canned_responses:
            if self._canned_idx < len(self._cfg.canned_responses):
                resp = self._cfg.canned_responses[self._canned_idx]
                self._canned_idx += 1
                await self._result_queue.put(resp)
            return

        # Emit a partial for every chunk when enabled
        if self._cfg.emit_partials:
            partial = self._make_response(
                is_final=False,
                speech_final=False,
                words=list(self._current_words),
            )
            await self._result_queue.put(partial)

    async def send_keep_alive(self) -> None:
        self._ensure_connected()
        self._silence_counter += 1

        # Simulate speech_final after enough silence (only when there are
        # accumulated words and we are *not* using canned responses).
        if (
            self._current_words
            and not self._cfg.canned_responses
            and self._silence_counter >= self._cfg.silence_chunks_for_speech_final
        ):
            await self._emit_final_and_speech_final()

    async def send_finalize(self) -> None:
        self._ensure_connected()
        self._finalized = True
        # Flush remaining words as a final utterance
        if self._current_words and not self._cfg.canned_responses:
            await self._emit_final_and_speech_final()

    async def send_close_stream(self) -> None:
        self._ensure_connected()
        self._stream_closed = True
        # Flush remaining words
        if self._current_words and not self._cfg.canned_responses:
            await self._emit_final_and_speech_final()
        # Signal end of results
        await self._result_queue.put(None)

    async def receive_results(self) -> AsyncIterator[ProviderResponse]:  # type: ignore[override]
        """Yield responses until a ``None`` sentinel is received."""
        while True:
            item = await self._result_queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        self._closed = True
        self._connected = False
        # Ensure any pending receive_results exits
        await self._result_queue.put(None)

    # -- Inspection helpers (test-only) ----------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def audio_chunks_received(self) -> int:
        return len(self._audio_chunks)

    @property
    def total_audio_bytes(self) -> int:
        return sum(len(c) for c in self._audio_chunks)

    # -- Internal helpers ------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MockSTTProvider is not connected")

    def _make_word_timings(self, words: List[str]) -> List[WordTiming]:
        timings: List[WordTiming] = []
        t = self._time_cursor
        for w in words:
            dur = 0.3  # simulated word duration
            timings.append(
                WordTiming(word=w, start=t, end=t + dur, confidence=self._cfg.default_confidence)
            )
            t += dur
        return timings

    def _make_response(
        self,
        *,
        is_final: bool,
        speech_final: bool,
        words: List[str],
    ) -> ProviderResponse:
        timings = self._make_word_timings(words)
        start = timings[0].start if timings else self._time_cursor
        end = timings[-1].end if timings else self._time_cursor
        return ProviderResponse(
            is_final=is_final,
            speech_final=speech_final,
            text=" ".join(words),
            start=start,
            end=end,
            words=timings,
            confidence=self._cfg.default_confidence,
            language=self._cfg.language,
        )

    async def _emit_final_and_speech_final(self) -> None:
        """Emit is_final + speech_final for accumulated words, then reset."""
        words = list(self._current_words)
        self._utterance_counter += 1

        # is_final response
        final = self._make_response(is_final=True, speech_final=False, words=words)
        await self._result_queue.put(final)

        # speech_final response
        sf = self._make_response(is_final=False, speech_final=True, words=words)
        await self._result_queue.put(sf)

        # Advance cursor and reset
        if final.words:
            self._time_cursor = final.words[-1].end
        self._current_words.clear()
        self._silence_counter = 0


class SlowMockProvider(MockSTTProvider):
    """MockSTTProvider variant with a per-``send_audio`` delay.

    Convenience wrapper that sets ``send_delay_s`` without callers needing
    to construct a full :class:`MockSTTConfig`.
    """

    def __init__(
        self,
        send_delay_s: float = 0.1,
        config: Optional[MockSTTConfig] = None,
    ) -> None:
        cfg = config or MockSTTConfig()
        # Override delay – caller-supplied value wins
        cfg.send_delay_s = send_delay_s
        super().__init__(config=cfg)


__all__ = [
    "MockSTTConfig",
    "MockSTTProvider",
    "SlowMockProvider",
]
