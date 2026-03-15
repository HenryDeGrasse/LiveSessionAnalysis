"""Tests for MockSTTProvider and SlowMockProvider."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.transcription.models import ProviderResponse, WordTiming
from app.transcription.providers import STTProviderClient
from app.transcription.providers.mock import (
    MockSTTConfig,
    MockSTTProvider,
    SlowMockProvider,
)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_mock_satisfies_protocol(self):
        provider = MockSTTProvider()
        assert isinstance(provider, STTProviderClient)

    def test_slow_mock_satisfies_protocol(self):
        provider = SlowMockProvider()
        assert isinstance(provider, STTProviderClient)


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect(self):
        p = MockSTTProvider()
        assert not p.is_connected
        await p.connect()
        assert p.is_connected

    @pytest.mark.asyncio
    async def test_double_connect_raises(self):
        p = MockSTTProvider()
        await p.connect()
        with pytest.raises(RuntimeError, match="already connected"):
            await p.connect()

    @pytest.mark.asyncio
    async def test_close(self):
        p = MockSTTProvider()
        await p.connect()
        await p.close()
        assert p.is_closed
        assert not p.is_connected

    @pytest.mark.asyncio
    async def test_send_audio_before_connect_raises(self):
        p = MockSTTProvider()
        with pytest.raises(RuntimeError, match="not connected"):
            await p.send_audio(b"\x00" * 320)

    @pytest.mark.asyncio
    async def test_send_keep_alive_before_connect_raises(self):
        p = MockSTTProvider()
        with pytest.raises(RuntimeError, match="not connected"):
            await p.send_keep_alive()

    @pytest.mark.asyncio
    async def test_send_finalize_before_connect_raises(self):
        p = MockSTTProvider()
        with pytest.raises(RuntimeError, match="not connected"):
            await p.send_finalize()

    @pytest.mark.asyncio
    async def test_send_close_stream_before_connect_raises(self):
        p = MockSTTProvider()
        with pytest.raises(RuntimeError, match="not connected"):
            await p.send_close_stream()


# ---------------------------------------------------------------------------
# Audio ingestion
# ---------------------------------------------------------------------------


class TestAudioIngestion:
    @pytest.mark.asyncio
    async def test_counts_audio_chunks(self):
        p = MockSTTProvider()
        await p.connect()
        for _ in range(5):
            await p.send_audio(b"\x00" * 320)
        assert p.audio_chunks_received == 5

    @pytest.mark.asyncio
    async def test_total_audio_bytes(self):
        p = MockSTTProvider()
        await p.connect()
        await p.send_audio(b"\x00" * 100)
        await p.send_audio(b"\x00" * 200)
        assert p.total_audio_bytes == 300


# ---------------------------------------------------------------------------
# Partial emission
# ---------------------------------------------------------------------------


class TestPartialEmission:
    @pytest.mark.asyncio
    async def test_partials_emitted_per_chunk(self):
        p = MockSTTProvider()
        await p.connect()

        # Send 3 audio chunks
        for _ in range(3):
            await p.send_audio(b"\x00" * 320)

        # Close to flush + terminate
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        partials = [r for r in results if r.is_partial]
        assert len(partials) == 3  # one per chunk

    @pytest.mark.asyncio
    async def test_partials_disabled(self):
        cfg = MockSTTConfig(emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        await p.send_audio(b"\x00" * 320)
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        partials = [r for r in results if r.is_partial]
        assert len(partials) == 0


# ---------------------------------------------------------------------------
# Speech final after silence
# ---------------------------------------------------------------------------


class TestSpeechFinalAfterSilence:
    @pytest.mark.asyncio
    async def test_speech_final_after_keep_alives(self):
        cfg = MockSTTConfig(silence_chunks_for_speech_final=2, emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        # Send audio, then keep-alive to trigger speech_final
        await p.send_audio(b"\x00" * 320)
        await p.send_keep_alive()
        await p.send_keep_alive()  # triggers speech_final

        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        finals = [r for r in results if r.is_final]
        speech_finals = [r for r in results if r.speech_final]
        assert len(finals) >= 1
        assert len(speech_finals) >= 1

    @pytest.mark.asyncio
    async def test_no_speech_final_without_enough_silence(self):
        cfg = MockSTTConfig(silence_chunks_for_speech_final=5, emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        await p.send_audio(b"\x00" * 320)
        await p.send_keep_alive()  # only 1 – not enough

        # Close to get final flush
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        # The close_stream flushes remaining words, so we get finals from there,
        # but the keep-alive alone should NOT have triggered them.
        # We verify that exactly one batch of final+speech_final was emitted (from flush).
        finals = [r for r in results if r.is_final]
        assert len(finals) == 1  # only from the flush


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


class TestFinalize:
    @pytest.mark.asyncio
    async def test_finalize_flushes_words(self):
        cfg = MockSTTConfig(emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        await p.send_audio(b"\x00" * 320)
        await p.send_audio(b"\x00" * 320)
        await p.send_finalize()

        # Send more audio after finalize
        await p.send_audio(b"\x00" * 320)
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        finals = [r for r in results if r.is_final]
        # Two batches: one from finalize, one from close_stream
        assert len(finals) == 2


# ---------------------------------------------------------------------------
# Canned responses
# ---------------------------------------------------------------------------


class TestCannedResponses:
    @pytest.mark.asyncio
    async def test_canned_responses_are_yielded_in_order(self):
        canned = [
            ProviderResponse(is_final=False, speech_final=False, text="hello"),
            ProviderResponse(is_final=True, speech_final=False, text="hello world"),
            ProviderResponse(is_final=False, speech_final=True, text="hello world"),
        ]
        cfg = MockSTTConfig(canned_responses=canned)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        for _ in range(3):
            await p.send_audio(b"\x00" * 320)

        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        assert len(results) == 3
        assert results[0].text == "hello"
        assert results[0].is_partial
        assert results[1].text == "hello world"
        assert results[1].is_final
        assert results[2].text == "hello world"
        assert results[2].speech_final

    @pytest.mark.asyncio
    async def test_extra_audio_after_canned_exhausted(self):
        canned = [
            ProviderResponse(is_final=True, speech_final=False, text="only one"),
        ]
        cfg = MockSTTConfig(canned_responses=canned)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        # First chunk -> canned response
        await p.send_audio(b"\x00" * 320)
        # Second chunk -> no more canned, should be silent
        await p.send_audio(b"\x00" * 320)

        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        assert len(results) == 1
        assert results[0].text == "only one"


# ---------------------------------------------------------------------------
# Word timings
# ---------------------------------------------------------------------------


class TestWordTimings:
    @pytest.mark.asyncio
    async def test_word_timings_present(self):
        cfg = MockSTTConfig(emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        await p.send_audio(b"\x00" * 320)
        await p.send_audio(b"\x00" * 320)
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        finals = [r for r in results if r.is_final]
        assert len(finals) == 1
        assert len(finals[0].words) == 2
        for wt in finals[0].words:
            assert isinstance(wt, WordTiming)
            assert wt.start < wt.end

    @pytest.mark.asyncio
    async def test_time_cursor_advances(self):
        """After a flush, the next batch of words should start at the end of the previous."""
        cfg = MockSTTConfig(emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        await p.send_audio(b"\x00" * 320)
        await p.send_finalize()

        await p.send_audio(b"\x00" * 320)
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        finals = [r for r in results if r.is_final]
        assert len(finals) == 2
        first_end = finals[0].words[-1].end
        second_start = finals[1].words[0].start
        assert second_start >= first_end


# ---------------------------------------------------------------------------
# SlowMockProvider
# ---------------------------------------------------------------------------


class TestSlowMockProvider:
    @pytest.mark.asyncio
    async def test_send_delay(self):
        p = SlowMockProvider(send_delay_s=0.05)
        await p.connect()

        t0 = time.monotonic()
        await p.send_audio(b"\x00" * 320)
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.04  # allow small timing slack

        await p.close()

    @pytest.mark.asyncio
    async def test_cancellation_during_delay(self):
        """A send_audio call can be cancelled mid-sleep."""
        p = SlowMockProvider(send_delay_s=1.0)
        await p.connect()

        task = asyncio.create_task(p.send_audio(b"\x00" * 320))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Provider should still be usable
        assert p.audio_chunks_received == 0  # chunk wasn't appended
        await p.close()

    @pytest.mark.asyncio
    async def test_slow_mock_config_override(self):
        """Caller-provided delay overrides config default."""
        cfg = MockSTTConfig(send_delay_s=0.5)
        p = SlowMockProvider(send_delay_s=0.01, config=cfg)
        await p.connect()

        t0 = time.monotonic()
        await p.send_audio(b"\x00" * 320)
        elapsed = time.monotonic() - t0
        # Should use 0.01 (the SlowMockProvider param), not 0.5
        assert elapsed < 0.2
        await p.close()


# ---------------------------------------------------------------------------
# Language config
# ---------------------------------------------------------------------------


class TestLanguageConfig:
    @pytest.mark.asyncio
    async def test_custom_language(self):
        cfg = MockSTTConfig(language="es", emit_partials=False)
        p = MockSTTProvider(config=cfg)
        await p.connect()

        await p.send_audio(b"\x00" * 320)
        await p.send_close_stream()

        results: list[ProviderResponse] = []
        async for r in p.receive_results():
            results.append(r)

        assert all(r.language == "es" for r in results)
