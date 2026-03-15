"""Tests for TranscriptionStream."""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from app.models import Role
from app.transcription.clock import SessionClock
from app.transcription.models import FinalUtterance, PartialTranscript, ProviderResponse
from app.transcription.providers.mock import MockSTTConfig, MockSTTProvider
from app.transcription.queue import _TailInjection
from app.transcription.stream import TranscriptionStream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHUNK = bytes(960)  # 480 samples × 2 bytes = 960 bytes (30ms @ 16kHz)


class DelayedConnectMockProvider(MockSTTProvider):
    """Mock provider with a delayed connect() to exercise start/stop races."""

    def __init__(self, connect_delay_s: float = 0.01, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connect_delay_s = connect_delay_s

    async def connect(self) -> None:
        await asyncio.sleep(self._connect_delay_s)
        await super().connect()



def _make_stream(
    provider: MockSTTProvider | None = None,
    on_partial: object = None,
    on_final: object = None,
    on_drop: object = None,
    tail_silence_ms: int = 60,  # 2 chunks — fast tests
    queue_max_size: int = 50,
    keepalive_interval: float = 10.0,
    clock: SessionClock | None = None,
) -> TranscriptionStream:
    """Create a TranscriptionStream with sensible test defaults."""
    mono_time = 0.0

    def fake_mono() -> float:
        return mono_time

    clk = clock or SessionClock(mono_fn=fake_mono)
    return TranscriptionStream(
        session_id="test-session",
        role=Role.STUDENT,
        student_index=0,
        clock=clk,
        provider=provider or MockSTTProvider(),
        tail_silence_ms=tail_silence_ms,
        queue_max_size=queue_max_size,
        keepalive_interval=keepalive_interval,
        on_partial=on_partial,  # type: ignore[arg-type]
        on_final=on_final,  # type: ignore[arg-type]
        on_drop=on_drop,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Basic speech → final utterance flow
# ---------------------------------------------------------------------------


class TestBasicSpeechFlow:
    """Verify that speech chunks produce partial + final utterances."""

    @pytest.mark.asyncio
    async def test_stop_waits_for_inflight_start(self):
        """stop() should safely handle a stream whose start() is still connecting."""
        provider = DelayedConnectMockProvider(connect_delay_s=0.02)
        stream = _make_stream(provider=provider)

        start_task = asyncio.create_task(stream.start())
        await asyncio.sleep(0)
        await stream.stop()
        await start_task

        assert provider.is_closed is True
        assert stream._sender_task is None
        assert stream._receiver_task is None

    @pytest.mark.asyncio
    async def test_speech_produces_final_utterance(self):
        """Send speech chunks, then stop → expect a FinalUtterance."""
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider()
        stream = _make_stream(provider=provider, on_final=on_final)
        await stream.start()

        # Send speech chunks
        for _ in range(3):
            stream.try_send(CHUNK, is_speech=True)

        # Give the sender/receiver loops time to process
        await asyncio.sleep(0.1)

        # Stop triggers CloseStream → provider emits final
        await stream.stop()

        assert len(finals) >= 1
        assert finals[0].role == "student"
        assert finals[0].text  # non-empty

    @pytest.mark.asyncio
    async def test_speech_then_silence_produces_final(self):
        """Speech → silence edge triggers tail injection → speech_final."""
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider()
        stream = _make_stream(provider=provider, on_final=on_final)
        await stream.start()

        # Speech
        for _ in range(3):
            stream.try_send(CHUNK, is_speech=True)

        # Silence (triggers tail injection)
        stream.try_send(CHUNK, is_speech=False)

        # Wait for tail injection + provider processing
        await asyncio.sleep(0.5)

        # The mock provider should have emitted speech_final after silence
        await stream.stop()

        assert len(finals) >= 1
        assert finals[0].utterance_id == "student:0:utt-0"


# ---------------------------------------------------------------------------
# try_send never blocks
# ---------------------------------------------------------------------------


class TestTrySendNonBlocking:
    """Verify try_send() never blocks regardless of queue state."""

    @pytest.mark.asyncio
    async def test_try_send_does_not_block(self):
        """try_send should return immediately even with a full queue."""
        provider = MockSTTProvider()
        stream = _make_stream(
            provider=provider, queue_max_size=5
        )
        await stream.start()

        # Send way more than queue capacity — should not block
        for _ in range(100):
            stream.try_send(CHUNK, is_speech=True)

        # Should have dropped some chunks
        assert stream.stats["dropped_audio_chunks"] > 0
        assert stream.stats["voiced_chunks_received"] == 100

        await stream.stop()

    def test_try_send_without_start_does_not_block(self):
        """try_send should work even before start() (enqueues to queue)."""
        stream = _make_stream()
        # This should not raise or block
        stream.try_send(CHUNK, is_speech=True)
        stream.try_send(CHUNK, is_speech=False)
        assert stream.stats["voiced_chunks_received"] == 1


# ---------------------------------------------------------------------------
# Partial + final callback invocation
# ---------------------------------------------------------------------------


class TestCallbacks:
    """Verify that partial and final callbacks are invoked correctly."""

    @pytest.mark.asyncio
    async def test_partial_callback_invoked(self):
        """Partials should be emitted for interim provider hypotheses."""
        partials: List[PartialTranscript] = []

        async def on_partial(p: PartialTranscript) -> None:
            partials.append(p)

        provider = MockSTTProvider(MockSTTConfig(emit_partials=True))
        stream = _make_stream(provider=provider, on_partial=on_partial)
        await stream.start()

        for _ in range(3):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.15)
        await stream.stop()

        assert len(partials) >= 1
        assert all(p.role == "student" for p in partials)

    @pytest.mark.asyncio
    async def test_final_callback_invoked(self):
        """Final callback should fire on speech_final."""
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider()
        stream = _make_stream(provider=provider, on_final=on_final)
        await stream.start()

        for _ in range(3):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.1)
        await stream.stop()

        assert len(finals) >= 1

    @pytest.mark.asyncio
    async def test_no_callbacks_when_none(self):
        """Stream should work fine without callbacks (no crash)."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider)
        await stream.start()

        for _ in range(3):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.1)
        await stream.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_drop_callback_invoked(self):
        """on_drop callback should fire when audio is dropped."""
        drop_counts: List[int] = []

        def on_drop(count: int) -> None:
            drop_counts.append(count)

        provider = MockSTTProvider()
        stream = _make_stream(
            provider=provider,
            queue_max_size=3,
            on_drop=on_drop,
        )
        await stream.start()

        # Flood queue
        for _ in range(20):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.1)
        await stream.stop()

        assert len(drop_counts) > 0


# ---------------------------------------------------------------------------
# Utterance ID stability across revisions
# ---------------------------------------------------------------------------


class TestUtteranceIdStability:
    """Verify utterance_id is stable within a turn and increments between turns."""

    @pytest.mark.asyncio
    async def test_partial_utterance_id_stable(self):
        """All partials for the same turn should have the same utterance_id."""
        partials: List[PartialTranscript] = []

        async def on_partial(p: PartialTranscript) -> None:
            partials.append(p)

        provider = MockSTTProvider(MockSTTConfig(emit_partials=True))
        stream = _make_stream(provider=provider, on_partial=on_partial)
        await stream.start()

        for _ in range(5):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.15)
        await stream.stop()

        assert len(partials) >= 2
        # All partials for the first utterance should share the same ID
        first_id = partials[0].utterance_id
        assert first_id == "student:0:utt-0"
        # Revisions should increment
        for i, p in enumerate(partials):
            if p.utterance_id == first_id:
                assert p.revision == i + 1

    @pytest.mark.asyncio
    async def test_utterance_id_increments_after_final(self):
        """utterance_id should increment after each speech_final."""
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        # Use canned responses to control exactly when finals fire
        canned = [
            ProviderResponse(
                is_final=True, speech_final=False,
                text="hello", start=0.0, end=0.3
            ),
            ProviderResponse(
                is_final=False, speech_final=True,
                text="", start=0.0, end=0.3
            ),
            ProviderResponse(
                is_final=True, speech_final=False,
                text="world", start=0.5, end=0.8
            ),
            ProviderResponse(
                is_final=False, speech_final=True,
                text="", start=0.5, end=0.8
            ),
        ]
        provider = MockSTTProvider(MockSTTConfig(canned_responses=canned))
        stream = _make_stream(provider=provider, on_final=on_final)
        await stream.start()

        # Send enough speech chunks to trigger all canned responses
        for _ in range(4):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.2)
        await stream.stop()

        assert len(finals) == 2
        assert finals[0].utterance_id == "student:0:utt-0"
        assert finals[0].text == "hello"
        assert finals[1].utterance_id == "student:0:utt-1"
        assert finals[1].text == "world"


# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------


class TestStats:
    """Verify stats property tracks the right metrics."""

    @pytest.mark.asyncio
    async def test_stats_initial(self):
        """Stats should be zeroed initially."""
        stream = _make_stream()
        s = stream.stats
        assert s["voiced_chunks_received"] == 0
        assert s["dropped_audio_chunks"] == 0
        assert s["total_chunks_sent"] == 0
        assert s["ever_spoken"] is False
        assert s["drop_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_speech(self):
        """Stats should reflect speech chunks."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider)
        await stream.start()

        for _ in range(5):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.15)
        s = stream.stats

        assert s["voiced_chunks_received"] == 5
        assert s["ever_spoken"] is True
        assert s["total_chunks_sent"] >= 1

        await stream.stop()

    @pytest.mark.asyncio
    async def test_stats_silence_skipped(self):
        """Silence chunks (before speech) should be counted as skipped."""
        stream = _make_stream()
        await stream.start()

        # Send silence-only
        for _ in range(5):
            stream.try_send(CHUNK, is_speech=False)

        s = stream.stats
        assert s["silence_chunks_sent"] == 5
        assert s["voiced_chunks_received"] == 0
        assert s["ever_spoken"] is False

        await stream.stop()

    @pytest.mark.asyncio
    async def test_drop_rate(self):
        """drop_rate should be dropped / voiced_chunks_received."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider, queue_max_size=3)
        await stream.start()

        # Flood with speech
        for _ in range(20):
            stream.try_send(CHUNK, is_speech=True)

        s = stream.stats
        assert s["voiced_chunks_received"] == 20
        assert s["drop_rate"] > 0.0
        assert s["drop_rate"] == s["dropped_audio_chunks"] / s["voiced_chunks_received"]

        await stream.stop()

    def test_control_coalescing_does_not_count_as_audio_drop(self):
        """Stale tail-control coalescing should not inflate audio-drop stats."""
        stream = _make_stream(queue_max_size=3)

        stream._queue.put_control(_TailInjection(token=1))
        stream._queue.put_control(_TailInjection(token=2))
        stream._queue.put_control(_TailInjection(token=3))

        # This enqueue forces stale control coalescing, but no audio is dropped.
        stream.try_send(CHUNK, is_speech=True)

        s = stream.stats
        assert stream._queue.dropped_count == 2
        assert stream._queue.audio_dropped_count == 0
        assert s["dropped_audio_chunks"] == 0
        assert s["drop_rate"] == 0.0


# ---------------------------------------------------------------------------
# VAD edge state tracking
# ---------------------------------------------------------------------------


class TestVADEdgeState:
    """Verify VAD edge-state tracking (no spurious tail injections)."""

    @pytest.mark.asyncio
    async def test_initial_silence_no_tail_injection(self):
        """Silence at session start should NOT trigger tail injection."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider)
        await stream.start()

        # Only silence frames
        for _ in range(10):
            stream.try_send(CHUNK, is_speech=False)

        s = stream.stats
        # No tail injection should have been enqueued
        assert s["tail_silence_chunks_sent"] == 0
        assert s["silence_chunks_sent"] == 10

        await stream.stop()

    @pytest.mark.asyncio
    async def test_speech_silence_edge_triggers_tail(self):
        """Speech→silence edge should trigger tail injection."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider, tail_silence_ms=60)
        await stream.start()

        # Speech
        stream.try_send(CHUNK, is_speech=True)
        # Silence (edge)
        stream.try_send(CHUNK, is_speech=False)

        # Wait for tail injection to complete
        await asyncio.sleep(0.3)

        s = stream.stats
        assert s["tail_silence_chunks_sent"] >= 1

        await stream.stop()

    @pytest.mark.asyncio
    async def test_continued_silence_no_extra_tails(self):
        """Continued silence frames after edge should not add more tail injections."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider, tail_silence_ms=60)
        await stream.start()

        # Speech
        stream.try_send(CHUNK, is_speech=True)
        # First silence (edge → tail injection enqueued)
        stream.try_send(CHUNK, is_speech=False)
        # More silence — all enqueued (provider handles VAD)
        for _ in range(5):
            stream.try_send(CHUNK, is_speech=False)

        await asyncio.sleep(0.3)
        s = stream.stats
        # All 6 silence frames were sent through
        assert s["silence_chunks_sent"] == 6

        await stream.stop()


# ---------------------------------------------------------------------------
# Role key format
# ---------------------------------------------------------------------------


class TestRoleKey:
    """Verify role_key format for multi-student safety."""

    @pytest.mark.asyncio
    async def test_role_key_format(self):
        """utterance_id should use f'{role.value}:{student_index}:utt-N'."""
        finals: List[FinalUtterance] = []

        async def on_final(u: FinalUtterance) -> None:
            finals.append(u)

        provider = MockSTTProvider()
        stream = TranscriptionStream(
            session_id="test",
            role=Role.TUTOR,
            student_index=2,
            clock=SessionClock(),
            provider=provider,
            tail_silence_ms=60,
            queue_max_size=50,
            keepalive_interval=10.0,
            on_final=on_final,
        )
        await stream.start()

        for _ in range(3):
            stream.try_send(CHUNK, is_speech=True)

        await asyncio.sleep(0.1)
        await stream.stop()

        assert len(finals) >= 1
        assert finals[0].utterance_id.startswith("tutor:2:utt-")


# ---------------------------------------------------------------------------
# Reconnect handling
# ---------------------------------------------------------------------------


class TestReconnect:
    """Verify handle_reconnect() resets state properly."""

    @pytest.mark.asyncio
    async def test_reconnect_resets_state(self):
        """After reconnect, VAD state and pause tracking should reset."""
        provider = MockSTTProvider()
        stream = _make_stream(provider=provider)
        await stream.start()

        # Speech then silence
        stream.try_send(CHUNK, is_speech=True)
        stream.try_send(CHUNK, is_speech=False)

        await stream.handle_reconnect()

        # After reconnect, silence should not trigger tail (not in_speech)
        stream.try_send(CHUNK, is_speech=False)
        assert stream.stats["silence_chunks_sent"] >= 1

        await stream.stop()
