"""TranscriptionStream – manages a streaming STT connection for one participant.

Audio delivery is fully decoupled from the caller:
- ``try_send()`` does a non-blocking ``put_nowait()`` into DroppableAudioQueue
- A background ``_sender_loop`` drains the queue → provider WebSocket
- A background ``_receiver_loop`` reads provider responses → callbacks

See ``docs/ai-conversational-intelligence-plan.md`` §3.4 for the full design.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Awaitable, Callable, List, Optional

from app.config import settings
from app.models import Role
from app.transcription.clock import SessionClock
from app.transcription.models import (
    BackpressureLevel,
    FinalUtterance,
    PartialTranscript,
    ProviderResponse,
    SessionObservability,
    WordTiming,
)
from app.transcription.providers import STTProviderClient
from app.transcription.queue import DroppableAudioQueue, _TailInjection


# --------------------------------------------------------------------------- #
# Backpressure policy thresholds
# --------------------------------------------------------------------------- #

BP_LATENCY_THRESHOLD_S = 1.0       # L1: provider latency > 1s
BP_LATENCY_SUSTAIN_S = 15.0        # L1: sustained for 15s
BP_DROP_RATE_L2 = 0.005             # L2: drop rate > 0.5%
BP_DROP_RATE_L2_SUSTAIN_S = 30.0    # L2: sustained for 30s
BP_DROP_RATE_L3 = 0.05              # L3: drop rate > 5%
BP_DROP_RATE_L3_SUSTAIN_S = 60.0    # L3: sustained for 60s
BP_RECOVERY_HYSTERESIS_S = 30.0     # Recovery: 30s hysteresis
BP_LATENCY_WINDOW = 50             # sliding window size for latency samples


class TranscriptionStream:
    """Manages a streaming STT connection for one participant's audio.

    Audio delivery is fully decoupled from the caller:
    - ``try_send()`` does a non-blocking ``put_nowait()`` into DroppableAudioQueue
    - A background ``_sender_loop`` drains the queue → provider WebSocket
    - A background ``_receiver_loop`` reads provider responses → callbacks

    VAD edge tracking with explicit ``_in_speech`` state:
    - Tail injection fires ONLY on speech→silence transitions
    - No injection at session start, during initial silence, or after
      reconnects until the participant actually speaks
    - Cancelable via token at two points:
      1. Before injection starts (token check on dequeue)
      2. DURING injection (token re-checked each chunk)

    Tail injection pacing:
    - Tail silence is paced at real-time (30ms per chunk) using
      monotonic scheduling to prevent provider timestamp drift.

    Utterance assembly (see §3.6):
    - Accumulate ``is_final=True`` segments into a pending utterance
    - On ``speech_final=True``, concatenate segments → FinalUtterance
    - Generate stable ``utterance_id`` from ``{role_key}:utt-{N}``
    - Partial revision counter managed locally
    """

    RECEIVER_DRAIN_TIMEOUT = 5.0

    # Audio chunk timing constants (16kHz, 480 samples = 30ms)
    CHUNK_SAMPLES = 480
    CHUNK_BYTES = CHUNK_SAMPLES * 2  # 16-bit = 2 bytes/sample
    CHUNK_DURATION_S = CHUNK_SAMPLES / 16000  # 0.03

    def __init__(
        self,
        session_id: str,
        role: Role,
        student_index: int,
        clock: SessionClock,
        provider: STTProviderClient,
        tail_silence_ms: Optional[int] = None,
        queue_max_size: Optional[int] = None,
        keepalive_interval: Optional[float] = None,
        on_partial: Optional[Callable[[PartialTranscript], Awaitable[None]]] = None,
        on_final: Optional[Callable[[FinalUtterance], Awaitable[None]]] = None,
        on_drop: Optional[Callable[[int], None]] = None,
        mono_fn: Optional[Callable[[], float]] = None,
    ) -> None:
        self._session_id = session_id
        self._role = role
        self._role_key = f"{role.value}:{student_index}"
        self._clock = clock
        self._provider = provider
        self._tail_silence_ms = tail_silence_ms or settings.deepgram_endpointing_ms
        self._keepalive_interval = (
            keepalive_interval
            or settings.transcription_keepalive_interval_seconds
        )
        self._queue = DroppableAudioQueue(
            maxsize=queue_max_size or settings.transcription_queue_max_size
        )
        self._mono_fn = mono_fn or time.monotonic

        self._sender_task: Optional[asyncio.Task[None]] = None
        self._receiver_task: Optional[asyncio.Task[None]] = None
        self._start_task: Optional[asyncio.Task[None]] = None
        self._started: bool = False
        self._stopped: bool = False
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_drop = on_drop

        # VAD edge state
        self._in_speech: bool = False
        self._ever_spoken: bool = False

        # Cancelable tail injection
        self._tail_token: int = 0
        self._tail_pending: bool = False

        # Utterance assembly
        self._pending_segments: List[str] = []
        self._pending_words: List[WordTiming] = []
        self._pending_start_time: Optional[float] = None
        self._utterance_counter: int = 0
        self._partial_revision: int = 0

        # Provider connection offset
        self._provider_time_zero: Optional[float] = None

        # Audio sample counter
        self._samples_sent_to_provider: int = 0

        # Observability
        self._voiced_chunks_received = 0
        self._voiced_chunks_enqueued = 0
        self._dropped_audio_chunks = 0
        self._total_chunks_sent = 0
        self._silence_chunks_skipped = 0
        self._tail_silence_chunks_sent = 0
        self._tail_injections_canceled = 0
        self._reconnect_count = 0

        # Per-response latency tracking (sliding window)
        self._partial_latencies: deque[float] = deque(maxlen=BP_LATENCY_WINDOW)
        self._final_latencies: deque[float] = deque(maxlen=BP_LATENCY_WINDOW)

        # Backpressure state
        self._backpressure_level = BackpressureLevel.L0_NORMAL
        self._ws_down = False
        # Timestamps for sustained-condition tracking
        self._latency_high_since: Optional[float] = None
        self._drop_rate_l2_since: Optional[float] = None
        self._drop_rate_l3_since: Optional[float] = None
        self._recovery_since: Optional[float] = None

    # -- Public API -----------------------------------------------------------

    async def start(self) -> None:
        """Open provider connection and start sender + receiver tasks.

        The stream starts in "paused" state: ``clock.pause()`` is called
        immediately so that initial silence contributes to pause_offset.
        """
        current_task = asyncio.current_task()
        if current_task is not None:
            self._start_task = current_task

        if self._started and not self._stopped:
            return

        await self._provider.connect()
        self._provider_time_zero = self._clock.session_time()
        self._started = True
        self._stopped = False
        # Start paused — initial silence accumulates into pause_offset
        self._clock.pause(self._role_key, provider_audio_time=0.0)
        self._sender_task = asyncio.create_task(
            self._sender_loop(), name=f"stt-sender-{self._role_key}"
        )
        self._receiver_task = asyncio.create_task(
            self._receiver_loop(), name=f"stt-receiver-{self._role_key}"
        )

    def try_send(self, pcm_chunk: bytes, is_speech: bool) -> None:
        """Non-blocking enqueue. Called from ``_consume_audio_track()``.

        NEVER blocks. Uses explicit ``_in_speech`` state to detect edges:

        - Only speech→silence edge triggers tail injection
        - Silence→speech edge cancels any pending tail injection
        - Speech frames always enqueued
        - Continued silence frames are skipped
        """
        if is_speech:
            self._voiced_chunks_received += 1
            self._ever_spoken = True
            # Cancel any pending tail injection
            if self._tail_pending:
                self._tail_token += 1
                self._tail_pending = False
            self._in_speech = True
            self._enqueue_audio(pcm_chunk)
            return

        # Silence frame
        if self._in_speech and not self._tail_pending:
            # Speech→silence edge
            self._in_speech = False
            self._tail_pending = True
            self._queue.put_control(
                _TailInjection(token=self._tail_token),
                coalesce_token=self._tail_token,
            )
            return

        # Continued silence (or initial silence before any speech)
        self._silence_chunks_skipped += 1

    async def stop(self) -> List[FinalUtterance]:
        """Orderly shutdown.

        1. Wait for any in-flight ``start()`` task to finish setup
        2. Enqueue stop sentinel
        3. Await sender (sends CloseStream to provider)
        4. Await receiver drain (with timeout) for final responses
        5. Close provider connection
        """
        if self._stopped:
            return self._flush_pending()

        current_task = asyncio.current_task()
        if (
            self._start_task is not None
            and self._start_task is not current_task
            and not self._start_task.done()
        ):
            await asyncio.shield(self._start_task)

        self._queue.put_stop()
        if self._sender_task:
            await self._sender_task
        if self._receiver_task:
            try:
                await asyncio.wait_for(
                    self._receiver_task, timeout=self.RECEIVER_DRAIN_TIMEOUT
                )
            except asyncio.TimeoutError:
                self._receiver_task.cancel()
                try:
                    await self._receiver_task
                except asyncio.CancelledError:
                    pass
        await self._provider.close()
        self._sender_task = None
        self._receiver_task = None
        self._start_task = None
        self._stopped = True
        return self._flush_pending()

    async def handle_reconnect(self) -> None:
        """Handle provider WebSocket reconnect.

        Provider timestamps restart from 0 on each new connection.
        """
        self._provider_time_zero = self._clock.session_time()
        self._clock.reset_pauses(self._role_key)
        self._in_speech = False
        self._tail_pending = False
        self._samples_sent_to_provider = 0
        self.mark_reconnect()
        self._ws_down = False
        # Start paused again until first post-reconnect speech
        self._clock.pause(self._role_key, provider_audio_time=0.0)

    @property
    def drop_rate(self) -> float:
        """Audio drop rate for backpressure level decisions.

        Denominator: ``voiced_chunks_received`` (VAD=true frames).
        Tail silence chunks are excluded (synthetic, not user audio).
        """
        if self._voiced_chunks_received == 0:
            return 0.0
        return self._dropped_audio_chunks / self._voiced_chunks_received

    @property
    def backpressure_level(self) -> BackpressureLevel:
        """Current backpressure level."""
        return self._backpressure_level

    @property
    def stats(self) -> dict:
        """Lightweight runtime statistics for observability."""
        return {
            "voiced_chunks_received": self._voiced_chunks_received,
            "voiced_chunks_enqueued": self._voiced_chunks_enqueued,
            "dropped_audio_chunks": self._dropped_audio_chunks,
            "drop_rate": self.drop_rate,
            "total_chunks_sent": self._total_chunks_sent,
            "silence_chunks_skipped": self._silence_chunks_skipped,
            "tail_silence_chunks_sent": self._tail_silence_chunks_sent,
            "tail_injections_canceled": self._tail_injections_canceled,
            "queue_size": self._queue.qsize(),
            "utterances_finalized": self._utterance_counter,
            "provider_audio_time_s": self._provider_audio_time(),
            "ever_spoken": self._ever_spoken,
            "backpressure_level": self._backpressure_level,
            "reconnect_count": self._reconnect_count,
            "partial_latency_p50_ms": self._percentile(self._partial_latencies, 50),
            "partial_latency_p95_ms": self._percentile(self._partial_latencies, 95),
            "final_latency_p50_ms": self._percentile(self._final_latencies, 50),
            "final_latency_p95_ms": self._percentile(self._final_latencies, 95),
            "billed_seconds_estimate": self._provider_audio_time(),
        }

    def observability(self) -> SessionObservability:
        """Build a ``SessionObservability`` snapshot from current state."""
        return SessionObservability(
            partial_latency_p50_ms=self._percentile(self._partial_latencies, 50),
            partial_latency_p95_ms=self._percentile(self._partial_latencies, 95),
            final_latency_p50_ms=self._percentile(self._final_latencies, 50),
            final_latency_p95_ms=self._percentile(self._final_latencies, 95),
            reconnect_count=self._reconnect_count,
            drop_rate=self.drop_rate,
            billed_seconds_estimate=self._provider_audio_time(),
            backpressure_level=int(self._backpressure_level),
        )

    def set_ws_down(self, down: bool) -> None:
        """Signal that the provider WebSocket is down (or recovered)."""
        self._ws_down = down
        if down:
            self._update_backpressure()

    def mark_reconnect(self) -> None:
        """Record a provider reconnect for observability."""
        self._reconnect_count += 1

    # -- Internal: enqueue helpers --------------------------------------------

    def _enqueue_audio(self, pcm_chunk: bytes) -> None:
        """Enqueue audio. DroppableAudioQueue handles overflow."""
        prev_audio_dropped = self._queue.audio_dropped_count
        self._queue.put_nowait(pcm_chunk)
        self._dropped_audio_chunks = self._queue.audio_dropped_count
        if self._queue.audio_dropped_count > prev_audio_dropped:
            if self._on_drop:
                self._on_drop(self._dropped_audio_chunks)
        else:
            self._voiced_chunks_enqueued += 1

    # -- Internal: sender loop ------------------------------------------------

    async def _sender_loop(self) -> None:
        """Background task: drain queue → provider.

        Handles audio, cancelable tail injection, KeepAlive, and shutdown.
        """
        last_keepalive_mono = self._mono_fn()

        while True:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._keepalive_interval
                )
            except asyncio.TimeoutError:
                now_mono = self._mono_fn()
                if now_mono - last_keepalive_mono >= self._keepalive_interval:
                    await self._provider.send_keep_alive()
                    last_keepalive_mono = now_mono
                continue

            if item.kind == "stop":
                await self._provider.send_close_stream()
                break

            if item.kind == "control" and isinstance(item.payload, _TailInjection):
                inj_token = item.payload.token

                # Pre-start cancellation
                if inj_token != self._tail_token:
                    self._tail_injections_canceled += 1
                    continue

                # Paced injection with per-chunk cancellation
                tail_samples = math.ceil(16000 * self._tail_silence_ms / 1000)
                num_chunks = math.ceil(tail_samples / self.CHUNK_SAMPLES)
                zero_chunk = bytes(self.CHUNK_BYTES)

                injection_start = self._mono_fn()
                canceled_mid_flight = False

                for i in range(num_chunks):
                    # Mid-injection cancellation
                    if inj_token != self._tail_token:
                        self._tail_injections_canceled += 1
                        canceled_mid_flight = True
                        break

                    await self._provider.send_audio(zero_chunk)
                    self._tail_silence_chunks_sent += 1
                    self._samples_sent_to_provider += self.CHUNK_SAMPLES

                    # Real-time pacing
                    target = injection_start + (i + 1) * self.CHUNK_DURATION_S
                    now = self._mono_fn()
                    if target > now:
                        await asyncio.sleep(target - now)

                if not canceled_mid_flight:
                    # Injection completed successfully
                    self._tail_pending = False
                    self._clock.pause(
                        self._role_key,
                        provider_audio_time=self._provider_audio_time(),
                    )
                continue

            if item.kind == "audio":
                # Resume clock on first audio send (handles initial silence)
                # Also resumes after a completed tail injection
                self._clock.resume(self._role_key)
                await self._provider.send_audio(item.payload)
                self._samples_sent_to_provider += self.CHUNK_SAMPLES
                self._total_chunks_sent += 1
                last_keepalive_mono = self._mono_fn()

    # -- Internal: receiver loop ----------------------------------------------

    async def _receiver_loop(self) -> None:
        """Receive and process STT responses from the provider.

        - interim (``is_final=False``): emit PartialTranscript
        - ``is_final=True``, ``speech_final=False``: accumulate segment
        - ``speech_final=True``: concatenate → FinalUtterance

        Also tracks per-response latency and updates backpressure level.
        """
        async for response in self._provider.receive_results():
            # Track provider latency for backpressure decisions
            if response.provider_latency_ms > 0:
                if response.is_partial:
                    self._partial_latencies.append(response.provider_latency_ms)
                else:
                    self._final_latencies.append(response.provider_latency_ms)
            self._update_backpressure()

            if response.is_partial:
                # At L1+, suppress partial UI updates
                if self._on_partial and self._backpressure_level < BackpressureLevel.L1_PARTIALS_DEGRADED:
                    self._partial_revision += 1
                    accumulated = self._pending_text()
                    text = (
                        f"{accumulated} {response.text}".strip()
                        if accumulated
                        else response.text
                    )
                    partial = PartialTranscript(
                        utterance_id=self._current_utterance_id(),
                        revision=self._partial_revision,
                        role=self._role.value,
                        text=text,
                        confidence=response.confidence,
                        session_time=self._map_provider_time(response.start),
                    )
                    await self._on_partial(partial)

            elif response.is_final and not response.speech_final:
                self._pending_segments.append(response.text)
                if response.words:
                    self._pending_words.extend(response.words)
                if self._pending_start_time is None:
                    self._pending_start_time = response.start

            elif response.speech_final:
                if response.text:
                    self._pending_segments.append(response.text)
                if response.words:
                    self._pending_words.extend(response.words)

                full_text = " ".join(self._pending_segments).strip()
                if full_text and self._on_final:
                    utterance = FinalUtterance(
                        utterance_id=self._current_utterance_id(),
                        role=self._role.value,
                        text=full_text,
                        start_time=self._map_provider_time(
                            self._pending_start_time or response.start
                        ),
                        end_time=self._map_provider_time(response.end),
                        confidence=response.confidence,
                        sentiment=response.sentiment,
                        sentiment_score=response.sentiment_score,
                        words=self._pending_words.copy(),
                    )
                    await self._on_final(utterance)

                self._pending_segments.clear()
                self._pending_words.clear()
                self._pending_start_time = None
                self._partial_revision = 0
                self._utterance_counter += 1

    # -- Internal: helpers ----------------------------------------------------

    def _provider_audio_time(self) -> float:
        """Current provider-relative audio time from sample counter."""
        return self._samples_sent_to_provider / 16000

    def _map_provider_time(self, provider_audio_time: float) -> float:
        """Convert provider audio-relative timestamp to session time.

        Formula: ``connection_offset + provider_audio_time + applicable_pause_offset``
        """
        base = self._provider_time_zero or 0.0
        return base + self._clock.provider_to_session_time(
            provider_audio_time, self._role_key
        )

    def _pending_text(self) -> str:
        """Concatenation of accumulated is_final segments."""
        return " ".join(self._pending_segments)

    def _current_utterance_id(self) -> str:
        """Stable utterance ID for the current turn."""
        return f"{self._role_key}:utt-{self._utterance_counter}"

    def _flush_pending(self) -> List[FinalUtterance]:
        """Flush any accumulated but not-yet-finalized segments."""
        full_text = " ".join(self._pending_segments).strip()
        if not full_text:
            return []
        utterance = FinalUtterance(
            utterance_id=self._current_utterance_id(),
            role=self._role.value,
            text=full_text,
            start_time=self._map_provider_time(self._pending_start_time or 0.0),
            end_time=self._map_provider_time(self._provider_audio_time()),
            words=self._pending_words.copy(),
        )
        self._pending_segments.clear()
        self._pending_words.clear()
        self._pending_start_time = None
        self._utterance_counter += 1
        return [utterance]

    # -- Internal: backpressure -----------------------------------------------

    @staticmethod
    def _percentile(samples: deque[float], pct: int) -> float:
        """Compute percentile from a deque of samples. Returns 0.0 if empty."""
        if not samples:
            return 0.0
        sorted_s = sorted(samples)
        idx = int(len(sorted_s) * pct / 100)
        idx = min(idx, len(sorted_s) - 1)
        return sorted_s[idx]

    def _update_backpressure(self) -> None:
        """Recalculate backpressure level based on current conditions.

        Level escalation:
        - L3: WS down, or drop_rate > 5% sustained for 60s
        - L2: drop_rate > 0.5% sustained for 30s
        - L1: provider latency p95 > 1s sustained for 15s

        Recovery uses 30s hysteresis before downgrading.
        """
        now = self._mono_fn()
        current = self._backpressure_level
        target = BackpressureLevel.L0_NORMAL

        # --- Evaluate conditions for each level (highest first) ---

        # L3: WS down or severe drop rate
        if self._ws_down:
            target = BackpressureLevel.L3_TRANSCRIPT_DISABLED
        else:
            drop = self.drop_rate
            if drop > BP_DROP_RATE_L3:
                if self._drop_rate_l3_since is None:
                    self._drop_rate_l3_since = now
                if now - self._drop_rate_l3_since >= BP_DROP_RATE_L3_SUSTAIN_S:
                    target = BackpressureLevel.L3_TRANSCRIPT_DISABLED
            else:
                self._drop_rate_l3_since = None

            # L2: moderate drop rate
            if target < BackpressureLevel.L2_TRANSCRIPT_DEGRADED and drop > BP_DROP_RATE_L2:
                if self._drop_rate_l2_since is None:
                    self._drop_rate_l2_since = now
                if now - self._drop_rate_l2_since >= BP_DROP_RATE_L2_SUSTAIN_S:
                    target = BackpressureLevel.L2_TRANSCRIPT_DEGRADED
            elif drop <= BP_DROP_RATE_L2:
                self._drop_rate_l2_since = None

        # L1: high latency
        if target < BackpressureLevel.L1_PARTIALS_DEGRADED:
            p95 = self._percentile(self._partial_latencies, 95)
            if p95 > BP_LATENCY_THRESHOLD_S * 1000:  # compare ms to ms
                if self._latency_high_since is None:
                    self._latency_high_since = now
                if now - self._latency_high_since >= BP_LATENCY_SUSTAIN_S:
                    target = BackpressureLevel.L1_PARTIALS_DEGRADED
            else:
                self._latency_high_since = None

        # --- Apply hysteresis on recovery (downgrade) ---
        if target < current:
            # Conditions improved — apply recovery hysteresis
            if self._recovery_since is None:
                self._recovery_since = now
            if now - self._recovery_since >= BP_RECOVERY_HYSTERESIS_S:
                self._backpressure_level = target
                self._recovery_since = None
        else:
            # Conditions same or worse — reset recovery timer, apply immediately
            self._recovery_since = None
            if target > current:
                self._backpressure_level = target
