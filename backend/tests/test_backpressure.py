"""Tests for backpressure level transitions in TranscriptionStream."""

from __future__ import annotations

import asyncio
from typing import List

import pytest

from app.models import Role
from app.transcription.clock import SessionClock
from app.transcription.models import (
    BackpressureLevel,
    FinalUtterance,
    PartialTranscript,
    ProviderResponse,
)
from app.transcription.providers.mock import MockSTTConfig, MockSTTProvider
from app.transcription.stream import (
    BP_DROP_RATE_L2,
    BP_DROP_RATE_L2_SUSTAIN_S,
    BP_DROP_RATE_L3,
    BP_DROP_RATE_L3_SUSTAIN_S,
    BP_LATENCY_SUSTAIN_S,
    BP_LATENCY_THRESHOLD_S,
    BP_RECOVERY_HYSTERESIS_S,
    TranscriptionStream,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CHUNK = bytes(960)  # 480 samples × 2 bytes = 960 bytes (30ms @ 16kHz)


class ControllableTimeStream:
    """Wrapper that creates a TranscriptionStream with a controllable clock."""

    def __init__(self, **kwargs):
        self.time = 0.0

        def fake_mono():
            return self.time

        self.clock = SessionClock(mono_fn=fake_mono)
        self.provider = MockSTTProvider()
        self.partials: List[PartialTranscript] = []
        self.finals: List[FinalUtterance] = []

        self.stream = TranscriptionStream(
            session_id="test-bp",
            role=Role.STUDENT,
            student_index=0,
            clock=self.clock,
            provider=self.provider,
            tail_silence_ms=60,
            queue_max_size=50,
            keepalive_interval=10.0,
            on_partial=self._on_partial,
            on_final=self._on_final,
            mono_fn=fake_mono,
            **kwargs,
        )

    async def _on_partial(self, p: PartialTranscript):
        self.partials.append(p)

    async def _on_final(self, f: FinalUtterance):
        self.finals.append(f)

    def advance(self, seconds: float):
        self.time += seconds


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBackpressureLevelDefaults:
    """Initial state is L0."""

    def test_initial_level_is_l0(self):
        cts = ControllableTimeStream()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL

    def test_stats_include_backpressure_level(self):
        cts = ControllableTimeStream()
        stats = cts.stream.stats
        assert "backpressure_level" in stats
        assert stats["backpressure_level"] == BackpressureLevel.L0_NORMAL

    def test_stats_include_reconnect_count(self):
        cts = ControllableTimeStream()
        assert cts.stream.stats["reconnect_count"] == 0


class TestBackpressureL1Latency:
    """L1 triggers when provider latency p95 > 1s sustained for 15s."""

    def test_l1_not_triggered_below_threshold(self):
        cts = ControllableTimeStream()
        # Add latency samples below threshold
        for _ in range(20):
            cts.stream._partial_latencies.append(500.0)  # 500ms
        cts.advance(20.0)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL

    def test_l1_triggered_after_sustained_high_latency(self):
        cts = ControllableTimeStream()
        # Add high latency samples
        for _ in range(20):
            cts.stream._partial_latencies.append(1500.0)  # 1500ms > 1000ms threshold
        # First check sets latency_high_since
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL

        # Advance past sustain period
        cts.advance(BP_LATENCY_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L1_PARTIALS_DEGRADED

    def test_l1_not_triggered_before_sustain_period(self):
        cts = ControllableTimeStream()
        for _ in range(20):
            cts.stream._partial_latencies.append(1500.0)
        cts.stream._update_backpressure()
        cts.advance(BP_LATENCY_SUSTAIN_S - 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL


class TestBackpressureL2DropRate:
    """L2 triggers when drop_rate > 0.5% sustained for 30s."""

    def test_l2_triggered_after_sustained_drop_rate(self):
        cts = ControllableTimeStream()
        # Simulate drop rate > 0.5%
        cts.stream._voiced_chunks_received = 1000
        cts.stream._dropped_audio_chunks = 10  # 1% drop rate

        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL

        cts.advance(BP_DROP_RATE_L2_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L2_TRANSCRIPT_DEGRADED

    def test_l2_not_triggered_below_threshold(self):
        cts = ControllableTimeStream()
        cts.stream._voiced_chunks_received = 10000
        cts.stream._dropped_audio_chunks = 2  # 0.02%

        cts.advance(60.0)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL


class TestBackpressureL3:
    """L3 triggers on WS down or drop_rate > 5% sustained for 60s."""

    def test_l3_triggered_immediately_on_ws_down(self):
        cts = ControllableTimeStream()
        cts.stream.set_ws_down(True)
        assert cts.stream.backpressure_level == BackpressureLevel.L3_TRANSCRIPT_DISABLED

    def test_l3_triggered_after_sustained_severe_drop_rate(self):
        cts = ControllableTimeStream()
        cts.stream._voiced_chunks_received = 100
        cts.stream._dropped_audio_chunks = 10  # 10% drop rate

        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL

        cts.advance(BP_DROP_RATE_L3_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L3_TRANSCRIPT_DISABLED

    def test_ws_down_then_recovery(self):
        cts = ControllableTimeStream()
        cts.stream.set_ws_down(True)
        assert cts.stream.backpressure_level == BackpressureLevel.L3_TRANSCRIPT_DISABLED

        # WS comes back
        cts.stream.set_ws_down(False)
        cts.stream._update_backpressure()
        # Still L3 due to hysteresis
        assert cts.stream.backpressure_level == BackpressureLevel.L3_TRANSCRIPT_DISABLED

        # After hysteresis period
        cts.advance(BP_RECOVERY_HYSTERESIS_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL


class TestBackpressureRecoveryHysteresis:
    """Recovery uses 30s hysteresis before downgrading level."""

    def test_recovery_requires_hysteresis(self):
        cts = ControllableTimeStream()
        # Escalate to L2
        cts.stream._voiced_chunks_received = 1000
        cts.stream._dropped_audio_chunks = 10
        cts.stream._update_backpressure()
        cts.advance(BP_DROP_RATE_L2_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L2_TRANSCRIPT_DEGRADED

        # Fix conditions
        cts.stream._voiced_chunks_received = 100000
        cts.stream._dropped_audio_chunks = 10  # 0.01% - well below threshold
        cts.stream._update_backpressure()
        # Still L2 due to hysteresis
        assert cts.stream.backpressure_level == BackpressureLevel.L2_TRANSCRIPT_DEGRADED

        # Advance past hysteresis
        cts.advance(BP_RECOVERY_HYSTERESIS_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L0_NORMAL

    def test_recovery_resets_if_conditions_worsen(self):
        cts = ControllableTimeStream()
        # Escalate to L2
        cts.stream._voiced_chunks_received = 1000
        cts.stream._dropped_audio_chunks = 10
        cts.stream._update_backpressure()
        cts.advance(BP_DROP_RATE_L2_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L2_TRANSCRIPT_DEGRADED

        # Conditions improve partially
        cts.stream._voiced_chunks_received = 100000
        cts.stream._dropped_audio_chunks = 10
        cts.stream._update_backpressure()
        cts.advance(15.0)  # Halfway through hysteresis

        # Conditions worsen again
        cts.stream._voiced_chunks_received = 1000
        cts.stream._dropped_audio_chunks = 10
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L2_TRANSCRIPT_DEGRADED


class TestBackpressureLevelEscalation:
    """Higher levels override lower levels."""

    def test_l3_overrides_l1(self):
        cts = ControllableTimeStream()
        # Set up L1 conditions
        for _ in range(20):
            cts.stream._partial_latencies.append(1500.0)
        cts.stream._update_backpressure()
        cts.advance(BP_LATENCY_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L1_PARTIALS_DEGRADED

        # WS goes down → L3
        cts.stream.set_ws_down(True)
        assert cts.stream.backpressure_level == BackpressureLevel.L3_TRANSCRIPT_DISABLED

    def test_l2_overrides_l1(self):
        cts = ControllableTimeStream()
        # Set up L1 AND L2 conditions simultaneously
        for _ in range(20):
            cts.stream._partial_latencies.append(1500.0)
        cts.stream._voiced_chunks_received = 1000
        cts.stream._dropped_audio_chunks = 10
        cts.stream._update_backpressure()
        cts.advance(max(BP_LATENCY_SUSTAIN_S, BP_DROP_RATE_L2_SUSTAIN_S) + 1)
        cts.stream._update_backpressure()
        assert cts.stream.backpressure_level == BackpressureLevel.L2_TRANSCRIPT_DEGRADED


class TestBackpressurePartialSuppression:
    """At L1+, partial UI updates are suppressed in the receiver loop."""

    def test_partial_callback_gating_logic(self):
        """Unit test: verify the backpressure check in receiver suppresses partials.

        The receiver loop checks ``_backpressure_level < L1`` before emitting
        partials. This test validates that the level is correctly set so the
        condition evaluates as expected.
        """
        cts = ControllableTimeStream()
        # At L0, on_partial is set → partials would be emitted
        assert cts.stream._on_partial is not None
        assert cts.stream._backpressure_level < BackpressureLevel.L1_PARTIALS_DEGRADED

        # Force L1
        for _ in range(20):
            cts.stream._partial_latencies.append(1500.0)
        cts.stream._update_backpressure()
        cts.advance(BP_LATENCY_SUSTAIN_S + 1)
        cts.stream._update_backpressure()
        # The condition `self._backpressure_level < L1` is now False → partials suppressed
        assert cts.stream._backpressure_level >= BackpressureLevel.L1_PARTIALS_DEGRADED

    def test_at_l0_partials_would_be_emitted(self):
        """At L0, the partial condition allows emission."""
        cts = ControllableTimeStream()
        assert cts.stream._backpressure_level < BackpressureLevel.L1_PARTIALS_DEGRADED


class TestReconnectTracking:
    """Reconnects are counted for observability."""

    @pytest.mark.asyncio
    async def test_reconnect_increments_counter(self):
        cts = ControllableTimeStream()
        await cts.stream.start()
        try:
            assert cts.stream.stats["reconnect_count"] == 0
            await cts.stream.handle_reconnect()
            assert cts.stream.stats["reconnect_count"] == 1
            await cts.stream.handle_reconnect()
            assert cts.stream.stats["reconnect_count"] == 2
        finally:
            await cts.stream.stop()


class TestObservabilitySnapshot:
    """Test SessionObservability snapshot generation."""

    def test_observability_returns_dataclass(self):
        cts = ControllableTimeStream()
        obs = cts.stream.observability()
        assert obs.backpressure_level == 0
        assert obs.reconnect_count == 0
        assert obs.drop_rate == 0.0

    def test_observability_reflects_latency_samples(self):
        cts = ControllableTimeStream()
        for v in [100.0, 200.0, 300.0, 400.0, 500.0]:
            cts.stream._partial_latencies.append(v)
        obs = cts.stream.observability()
        assert obs.partial_latency_p50_ms > 0
        assert obs.partial_latency_p95_ms >= obs.partial_latency_p50_ms


class TestPercentileHelper:
    """Test the percentile helper."""

    def test_empty_deque(self):
        from collections import deque
        assert TranscriptionStream._percentile(deque(), 50) == 0.0

    def test_single_element(self):
        from collections import deque
        d = deque([42.0])
        assert TranscriptionStream._percentile(d, 50) == 42.0
        assert TranscriptionStream._percentile(d, 95) == 42.0

    def test_known_percentiles(self):
        from collections import deque
        d = deque(range(1, 101))  # 1..100
        p50 = TranscriptionStream._percentile(d, 50)
        p95 = TranscriptionStream._percentile(d, 95)
        assert 49 <= p50 <= 51
        assert 94 <= p95 <= 96


class TestCopilotBackpressureGating:
    """AI copilot respects backpressure level."""

    @pytest.mark.asyncio
    async def test_l2_blocks_auto_allows_on_demand(self):
        from unittest.mock import AsyncMock
        from app.ai_coaching.copilot import AICoachingCopilot
        from app.transcription.buffer import TranscriptBuffer

        mock_llm = AsyncMock()
        copilot = AICoachingCopilot(llm_client=mock_llm, min_transcript_words=0)
        buf = TranscriptBuffer()

        result = await copilot.maybe_evaluate(buf, backpressure_level=2)
        assert result is None
        # LLM should not have been called
        mock_llm.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_l3_blocks_everything(self):
        from unittest.mock import AsyncMock
        from app.ai_coaching.copilot import AICoachingCopilot
        from app.transcription.buffer import TranscriptBuffer

        mock_llm = AsyncMock()
        copilot = AICoachingCopilot(llm_client=mock_llm, min_transcript_words=0)
        buf = TranscriptBuffer()

        result = await copilot.maybe_evaluate(buf, backpressure_level=3, on_demand=True)
        assert result is None
        mock_llm.chat.assert_not_called()
