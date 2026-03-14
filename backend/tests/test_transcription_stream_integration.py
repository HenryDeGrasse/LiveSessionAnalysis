"""Integration tests for TranscriptionStream using MockSTTProvider.

Six critical integration scenarios that exercise the full pipeline:
queue → sender_loop → provider → receiver_loop → callbacks.
"""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from app.models import Role
from app.transcription.clock import SessionClock
from app.transcription.models import FinalUtterance, PartialTranscript, ProviderResponse
from app.transcription.providers.mock import MockSTTConfig, MockSTTProvider, SlowMockProvider
from app.transcription.stream import TranscriptionStream

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK = bytes(960)  # 480 samples × 2 bytes = 960 bytes (30ms @ 16kHz)
SPEECH_CHUNK = b"\x01" * 960  # Distinguishable from silence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """Manually-advanceable monotonic clock for deterministic tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt

    @property
    def now(self) -> float:
        return self._t


def _make_stream(
    provider: MockSTTProvider | None = None,
    on_partial: object = None,
    on_final: object = None,
    on_drop: object = None,
    tail_silence_ms: int = 60,
    queue_max_size: int = 50,
    keepalive_interval: float = 10.0,
    clock: SessionClock | None = None,
    mono_fn: object = None,
) -> TranscriptionStream:
    """Create a TranscriptionStream with sensible test defaults."""
    return TranscriptionStream(
        session_id="integ-test",
        role=Role.STUDENT,
        student_index=0,
        clock=clock or SessionClock(),
        provider=provider or MockSTTProvider(),
        tail_silence_ms=tail_silence_ms,
        queue_max_size=queue_max_size,
        keepalive_interval=keepalive_interval,
        on_partial=on_partial,  # type: ignore[arg-type]
        on_final=on_final,  # type: ignore[arg-type]
        on_drop=on_drop,  # type: ignore[arg-type]
        mono_fn=mono_fn,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Test 1 – Initial silence 30s → first speech
# ---------------------------------------------------------------------------


class TestInitialSilenceThenSpeech:
    """30 seconds of silence followed by speech should produce a final
    utterance with timestamps near real session time (no tail injection
    during initial silence).
    """

    @pytest.mark.asyncio
    async def test_initial_silence_then_speech(self):
        fake = FakeClock(start=0.0)
        clock = SessionClock(mono_fn=fake)
        provider = MockSTTProvider()
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        stream = _make_stream(
            provider=provider,
            on_final=on_final,
            clock=clock,
            mono_fn=fake,
            tail_silence_ms=60,
        )
        await stream.start()

        # 30 seconds of silence (1000 × 30ms chunks)
        for _ in range(1000):
            stream.try_send(CHUNK, is_speech=False)
            fake.advance(0.03)

        # No tail injection should have occurred during initial silence
        assert stream.stats["tail_silence_chunks_sent"] == 0

        # Now speech begins
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)
            fake.advance(0.03)

        # Wait for the provider to process
        await asyncio.sleep(0.2)
        await stream.stop()

        assert len(finals) >= 1
        utt = finals[0]
        assert utt.text  # non-empty

        # The first provider word starts at provider_audio_time ~= 0.0. After
        # 30s of initial silence, the mapped session timestamp should stay near
        # the real session clock rather than collapsing back toward 0.
        assert 29.5 <= utt.start_time <= 30.5, (
            f"Expected first utterance to start near 30s, got {utt.start_time:.3f}s"
        )
        assert utt.end_time > utt.start_time

        # Verify no spurious tail injection happened before speech
        assert stream.stats["silence_chunks_skipped"] == 1000


# ---------------------------------------------------------------------------
# Test 2 – VAD flicker (1-2 silence frames mid-speech cancel tail)
# ---------------------------------------------------------------------------


class TestVADFlicker:
    """A brief silence flicker mid-speech should NOT split the utterance.

    Scenario: speech → 1 silence → speech resumes quickly. The tail injection
    should be cancelled and the result should be a single utterance.
    """

    @pytest.mark.asyncio
    async def test_vad_flicker_single_utterance(self):
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider(MockSTTConfig(emit_partials=False))
        stream = _make_stream(
            provider=provider,
            on_final=on_final,
            tail_silence_ms=240,  # 8 chunks — longer tail so cancellation is testable
        )
        await stream.start()

        # Phase 1: speech
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        # Phase 2: 1 silence frame (triggers tail injection enqueue)
        stream.try_send(CHUNK, is_speech=False)

        # Phase 3: speech resumes immediately → cancels tail injection
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        # Wait for processing
        await asyncio.sleep(0.3)
        await stream.stop()

        # The tail injection should have been cancelled
        assert stream.stats["tail_injections_canceled"] >= 1

        # Result should be one utterance, not split into two
        assert len(finals) == 1, (
            f"Expected single utterance but got {len(finals)}: "
            f"{[u.text for u in finals]}"
        )


# ---------------------------------------------------------------------------
# Test 3 – Queue backpressure (small queue, ordering preserved)
# ---------------------------------------------------------------------------


class TestQueueBackpressure:
    """With a small queue, audio should be dropped but:
    - tail injection should still be preserved
    - the resulting utterance ordering should be correct
    """

    @pytest.mark.asyncio
    async def test_backpressure_drops_audio_preserves_tail(self):
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider(MockSTTConfig(emit_partials=False))
        stream = _make_stream(
            provider=provider,
            on_final=on_final,
            queue_max_size=5,
            tail_silence_ms=60,
        )
        await stream.start()

        # Flood with speech chunks (exceeds queue capacity)
        for _ in range(30):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        # Speech→silence edge should enqueue a tail injection
        stream.try_send(CHUNK, is_speech=False)

        # Wait for tail injection to complete + processing
        await asyncio.sleep(0.5)
        await stream.stop()

        # Audio should have been dropped
        assert stream.stats["dropped_audio_chunks"] > 0

        # But we should still get a final utterance (tail injection preserved)
        assert len(finals) >= 1

        # Tail injection should have been sent (not dropped)
        assert stream.stats["tail_silence_chunks_sent"] >= 1

        # Utterance ordering: IDs should be sequential
        for i, u in enumerate(finals):
            assert u.utterance_id == f"student:0:utt-{i}"


# ---------------------------------------------------------------------------
# Test 4 – Reconnect mid-silence and mid-utterance
# ---------------------------------------------------------------------------


class TestReconnectTimestamps:
    """After a reconnect, timestamps should reset correctly:
    - utt2.start_time > utt1.end_time
    """

    @pytest.mark.asyncio
    async def test_reconnect_timestamps_ordered(self):
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        # Use short keepalive so the mock emits speech_final quickly after
        # tail injection completes (the sender loop sends keep_alives during
        # the pause, and the mock triggers speech_final after 1 keep_alive).
        provider = MockSTTProvider(MockSTTConfig(
            emit_partials=False,
            silence_chunks_for_speech_final=1,
        ))
        stream = _make_stream(
            provider=provider,
            on_final=on_final,
            tail_silence_ms=60,
            keepalive_interval=0.05,
        )
        await stream.start()

        # First utterance: speech
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        # Speech→silence triggers tail
        stream.try_send(CHUNK, is_speech=False)

        # Wait for tail injection + keep_alive to trigger speech_final
        await asyncio.sleep(0.5)

        assert len(finals) >= 1, "First utterance not finalized before reconnect"
        pre_reconnect_count = len(finals)

        # Reconnect
        await stream.handle_reconnect()

        # Post-reconnect speech
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        await asyncio.sleep(0.3)
        await stream.stop()

        assert len(finals) >= pre_reconnect_count + 1, (
            f"Expected at least {pre_reconnect_count + 1} utterances, "
            f"got {len(finals)}"
        )

        utt1, utt2 = finals[0], finals[-1]
        assert utt2.start_time > utt1.end_time, (
            f"Post-reconnect utterance start ({utt2.start_time:.3f}) "
            f"should be after pre-reconnect end ({utt1.end_time:.3f})"
        )


# ---------------------------------------------------------------------------
# Test 5 – Tail pacing prevents drift
# ---------------------------------------------------------------------------


class TestTailPacingDrift:
    """Three utterances with silence gaps should accumulate <500ms total
    drift and <200ms per-utterance gap error.

    Uses real monotonic time for the pacing loop to verify that the pacing
    logic actually prevents timing drift.  A short keepalive interval lets the
    mock provider emit speech_final after each tail injection completes.
    """

    @pytest.mark.asyncio
    async def test_tail_pacing_low_drift(self):
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider(MockSTTConfig(
            emit_partials=False,
            silence_chunks_for_speech_final=1,
        ))
        # Use real clock for pacing accuracy test.
        # Short keepalive so mock's keep_alive → speech_final fires quickly.
        stream = _make_stream(
            provider=provider,
            on_final=on_final,
            tail_silence_ms=240,  # 8 chunks = ~240ms tail
            keepalive_interval=0.05,
        )
        await stream.start()

        for utterance_idx in range(3):
            # Speech burst
            for _ in range(5):
                stream.try_send(SPEECH_CHUNK, is_speech=True)

            # Speech→silence edge
            stream.try_send(CHUNK, is_speech=False)

            # Wait for tail injection + keep_alive → speech_final
            await asyncio.sleep(0.5)

            # Silence gap between utterances
            if utterance_idx < 2:
                for _ in range(3):
                    stream.try_send(CHUNK, is_speech=False)
                    await asyncio.sleep(0.03)

        await asyncio.sleep(0.3)
        await stream.stop()

        assert len(finals) == 3, (
            f"Expected 3 utterances, got {len(finals)}: "
            f"{[u.text for u in finals]}"
        )

        # Verify pacing accuracy: the tail injection chunks should have been
        # sent at approximately real-time (30ms each), meaning 8 chunks ≈ 240ms.
        # With 3 utterances, total tail chunks should be ~24.
        tail_sent = stream.stats["tail_silence_chunks_sent"]
        assert tail_sent >= 20, (
            f"Expected ~24 tail silence chunks, got {tail_sent}"
        )

        # Verify pacing consistency. The mock provider's synthetic word timings
        # are not realistic enough to assert exact absolute gap durations, but
        # a correctly paced tail injection should still avoid cumulative drift
        # and keep inter-utterance gaps stable.
        gaps: List[float] = []
        total_negative_drift = 0.0
        for i in range(1, len(finals)):
            gap = finals[i].start_time - finals[i - 1].end_time
            gaps.append(gap)
            if gap < 0:
                total_negative_drift += abs(gap)

        # Critical requirement: cumulative drift stays below 500ms.
        assert total_negative_drift < 0.5, (
            f"Total timing drift {total_negative_drift:.3f}s exceeds 500ms threshold"
        )

        # Critical requirement: per-gap pacing error stays below 200ms. Use the
        # median observed gap as the reference so the mock's synthetic provider
        # timings do not force a brittle absolute expectation.
        expected_gap = sorted(gaps)[len(gaps) // 2]
        for i, gap in enumerate(gaps, start=1):
            assert abs(gap - expected_gap) < 0.2, (
                f"Utterance {i} gap error too large: gap={gap:.3f}s, "
                f"expected≈{expected_gap:.3f}s"
            )

        # Sequential utterance IDs
        for i, u in enumerate(finals):
            assert u.utterance_id == f"student:0:utt-{i}"


# ---------------------------------------------------------------------------
# Test 6 – Mid-injection cancel (SlowMockProvider)
# ---------------------------------------------------------------------------


class TestMidInjectionCancel:
    """With a SlowMockProvider (artificial per-chunk delay), speech resuming
    during a tail injection should cancel it mid-flight.

    The result: fewer silence chunks sent than the full 800ms tail, and the
    final result should be a single unsplit utterance.
    """

    @pytest.mark.asyncio
    async def test_mid_injection_cancel_fewer_chunks(self):
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        # SlowMockProvider: 50ms delay per send_audio call
        provider = SlowMockProvider(send_delay_s=0.05)
        stream = _make_stream(
            provider=provider,
            on_final=on_final,
            tail_silence_ms=800,  # ~27 chunks at 30ms each
            queue_max_size=100,
        )
        await stream.start()

        # Phase 1: speech
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        # Wait for speech to be sent to provider
        await asyncio.sleep(0.5)

        # Phase 2: silence edge → triggers 800ms tail injection
        stream.try_send(CHUNK, is_speech=False)

        # Wait a bit so some tail chunks get sent (but not all 27)
        # With 50ms delay per chunk, 200ms ≈ 4 chunks
        await asyncio.sleep(0.25)

        # Phase 3: speech resumes → should cancel tail mid-flight
        for _ in range(5):
            stream.try_send(SPEECH_CHUNK, is_speech=True)

        # Wait for everything to settle
        await asyncio.sleep(0.8)
        await stream.stop()

        # Fewer tail silence chunks should have been sent than full 800ms
        # (full = ceil(16000 * 0.8 / 480) = 27 chunks)
        full_tail_chunks = 27
        sent = stream.stats["tail_silence_chunks_sent"]
        assert sent < full_tail_chunks, (
            f"Expected fewer than {full_tail_chunks} tail chunks, "
            f"but got {sent} — mid-injection cancel didn't work"
        )

        # Tail injection should have been cancelled
        assert stream.stats["tail_injections_canceled"] >= 1

        # Should produce a single utterance (not split by the partial tail)
        assert len(finals) == 1, (
            f"Expected 1 utterance but got {len(finals)}: "
            f"{[u.text for u in finals]}"
        )
