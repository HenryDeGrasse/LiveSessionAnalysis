# AI Conversational Intelligence — Deep Implementation Plan

> Real-time speech-to-text, tone analysis, uncertainty detection, and AI-powered
> contextual coaching for live tutoring sessions.

**Status:** Planning → Revised after architecture review  
**Estimated effort:** 10–14 weeks (phased, each tier is independently shippable)  
**Created:** 2026-03-13  
**Revised:** 2026-03-13 R1 (backpressure, cost-gating, privacy, robustness)  
**Revised:** 2026-03-13 R2 (VAD-vs-endpointing conflict, time alignment with
gated audio, feature-disable on backpressure, `is_final` concatenation,
PII scope, AI output validation)  
**Revised:** 2026-03-13 R3 (tail silence = endpointing config, cancelable tail
injection via token, priority queue for control commands, SessionClock
connection offset + reconnect, receiver task lifecycle, validator tightening,
KeepAlive billing as hypothesis)  
**Revised:** 2026-03-13 R4 (VAD edge state tracking, initial silence accounting,
DroppableAudioQueue replacing asyncio.Queue internals, utterance_end_ms/vad_events
clarification, STTProviderClient abstraction, unique cross-track IDs, tail
silence math.ceil, critical integration tests)  
**Revised:** 2026-03-13 R5 (real-time tail injection pacing, mid-injection
cancellation, _tail_pending lifecycle, provider-time-anchored pause math,
DroppableAudioQueue stale control coalescing, config-driven keepalive,
precise backpressure denominators, SDK version pin fix, 2 new integration tests)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Tier 1 — Live Transcription](#3-tier-1--live-transcription)
4. [Tier 2 — Tone & Uncertainty Detection](#4-tier-2--tone--uncertainty-detection)
5. [Tier 3 — AI Coaching Copilot](#5-tier-3--ai-coaching-copilot)
6. [Tier 4 — Frontend UX](#6-tier-4--frontend-ux)
7. [Tier 5 — Post-Session Enrichment](#7-tier-5--post-session-enrichment)
8. [Data Model Changes](#8-data-model-changes)
9. [Infrastructure & Cost](#9-infrastructure--cost)
10. [Privacy & Compliance](#10-privacy--compliance)
11. [Testing Strategy](#11-testing-strategy)
12. [Rollout Plan](#12-rollout-plan)
13. [Risk Register](#13-risk-register)
14. [Engineering Gotchas](#14-engineering-gotchas)
15. [Latency Budgets](#15-latency-budgets)

---

## 1. Executive Summary

The current system analyzes *how* participants behave (gaze, speaking patterns,
energy, interruptions) but not *what* they say. Adding a conversational
intelligence layer unlocks:

- **Live transcripts** — who said what, when
- **Tone/sentiment analysis** — confident, hesitant, confused, frustrated
- **Uncertainty detection** — "the student sounds unsure about derivatives"
- **AI coaching copilot** — contextual nudges like "The student seems uncertain
  about integration. Try asking: *Can you explain the relationship between
  integrals and derivatives in your own words?*"
- **Suggested tutor responses** — one-tap coaching prompts the tutor can use
- **Post-session transcript** — searchable, annotated session record

### Why this is feasible now

| Advantage | Detail |
|-----------|--------|
| **Speaker diarization is free** | Tutor and student audio arrive on separate LiveKit tracks — no speaker-separation model needed |
| **Server-side audio access exists** | `livekit_worker.py` already subscribes to room audio tracks and processes PCM chunks |
| **Coaching delivery pipeline exists** | `Coach.evaluate()` → `Nudge` → WebSocket/data-packet → tutor UI with cooldowns, severity, profiles |
| **Prosody features exist** | `prosody.py` already computes RMS energy, ZCR, speech rate proxy per chunk |
| **Session profiles exist** | Lecture/practice/socratic/discussion profiles adjust thresholds — AI coaching inherits this |

### Shortest path to production-quality pilot

Implement Tier 1 with (a) tail-silence-injected VAD gating + keepalives,
(b) provider endpointing for utterance boundaries, and (c) student-only
transcription. Then add Tier 3 on-demand suggestions before the fully
automatic loop. This validates value while minimizing the two biggest
failure modes (cost and tutor annoyance).

---

## 2. Architecture Overview

```
LiveKit Room
  │
  ├─ Tutor Audio Track ──→ LiveKitAnalyticsWorker._consume_audio_track()
  │                            │
  │                            ├─ Existing: process_audio_chunk() → VAD + prosody
  │                            │
  │                            └─ NEW: try_send(pcm, is_speech)
  │                                      │
  │                                      ▼
  │                              DroppableAudioQueue
  │                                      │
  │                              _sender_loop (background task)
  │                                      │
  │                              ├─ Voiced frames → send to provider
  │                              ├─ VAD speech→silence transition:
  │                              │     inject TAIL_SILENCE_MS of zero PCM
  │                              │     (so provider sees real silence for
  │                              │      endpointing / UtteranceEnd to fire)
  │                              ├─ After tail silence: KeepAlive only
  │                              │     (not billed, audio clock paused)
  │                              ├─ Overflow: drop oldest, emit metric
  │                              │
  │                              ▼
  │                         STT Provider WebSocket (Deepgram)
  │                                      │
  │                              ├─ is_final:true segments accumulated
  │                              ├─ speech_final:true → concat segments →
  │                              │     FinalUtterance → TranscriptBuffer
  │                              ├─ partial transcript → UI (utterance_id)
  │                              └─ sentiment (English only, may be None)
  │
  ├─ Student Audio Track ──→ (same pipeline, separate stream)
  │
  └─ Both transcripts + existing MetricsSnapshot
       │
       ├─ UncertaintyDetector (Tier 2)
       │     ├─ Paralinguistic: pitch, hesitation, pauses (per-student)
       │     └─ Linguistic: hedging words, question patterns (per-student)
       │
       └─ AICoachingCopilot (Tier 3)
             ├─ Rolling context window (last 90s transcript + signals)
             ├─ Event-triggered + low-frequency baseline (30-45s default)
             ├─ Burst mode (10-15s) only when uncertainty high or rule fired
             ├─ Prompt caching (80-95% of prompt repeats across calls)
             ├─ Hard per-session budget (max 60 calls/hour)
             ├─ Pedagogy-only constraint (teaching moves, never answers)
             ├─ PII scrubbing before LLM call
             ├─ Structured output: topic, observation, suggested_prompt
             └─ Feeds into existing Coach pipeline as AI-generated nudges
```

### Critical design constraints

1. **The transcription stream must NEVER block or slow the existing audio
   analytics loop.** Audio delivery to the STT provider uses a fire-and-forget
   bounded queue with a background sender task. If the provider is slow, audio
   chunks are dropped (with metrics) — the existing VAD/prosody/interruption
   pipeline is completely unaffected.

2. **VAD gating must preserve provider endpointing.** Deepgram's endpointing
   and UtteranceEnd depend on seeing actual silence audio in the stream. If
   we stop sending audio entirely during silence, the provider's audio clock
   pauses and endpointing never fires. Solution: **tail-silence injection** —
   on VAD speech→silence transition, inject a short burst of zero-PCM (e.g.,
   500ms) so the provider sees real silence and triggers `speech_final`. Only
   then switch to KeepAlive-only mode. See §3.5 for full details.

3. **Provider word timings are audio-stream-relative.** During KeepAlive-only
   periods the provider's audio clock does not advance. All timestamps must
   be converted through `SessionClock` with accumulated pause offsets. See §3.8.

---

## 3. Tier 1 — Live Transcription

**Goal:** Real-time speech-to-text for both participants, with speaker labels  
**Estimated time:** 2–3 weeks  
**Dependencies:** None (can start immediately)

### 3.1 STT Provider Selection

| Provider | Streaming Latency | Sentiment | Cost/min | Notes |
|----------|------------------|-----------|----------|-------|
| **Deepgram Nova-2** | ~250-350ms | ✅ English only | ~$0.0058 (pay-as-you-go) | **Primary choice** — fastest, has sentiment + endpointing |
| **AssemblyAI Real-Time** | ~300ms | ✅ Built-in | ~$0.0025 (Universal) / ~$0.0075 (Pro) | Strong alternative, similar features |
| **OpenAI Whisper (self-hosted via faster-whisper)** | ~500ms-1.5s (chunked) | ❌ No | Free (compute cost) | Fallback if cost-sensitive, higher latency |
| **Google Cloud STT v2** | ~200ms | ❌ Chain to NLP | ~$0.006 (rounds to 1s increments) | Most battle-tested, no native sentiment |

**Note on pricing:** All dollar estimates are **placeholders** based on
published rates as of 2026-03-13. Provider pricing changes frequently.
Wire cost telemetry early (per session: STT seconds billed, tokens in/out).

**Recommendation:** Start with **AssemblyAI Real-Time** (default provider).
AssemblyAI provides streaming transcription with word timings and simpler
utterance boundary semantics (`FinalTranscript` = utterance boundary, no
`is_final`/`speech_final` accumulation needed). Deepgram Nova-2 is the
alternative if you need its endpointing control or sentiment features.

Both providers are implemented behind the `STTProviderClient` protocol (§3.9)
and can be swapped via `LSA_TRANSCRIPTION_PROVIDER=assemblyai|deepgram|mock`.

### 3.2 Integration Point — Non-Blocking Audio Delivery

The audio is already flowing server-side through the LiveKit analytics worker.
The integration point is `_consume_audio_track()` in `livekit_worker.py`.

**Critical:** The original plan called for `await transcription_stream.send_audio(pcm)`
inline. This is wrong — any slow websocket / queue backpressure can stall
the entire track consumer, degrading the existing analytics pipeline.

**Correct pattern:**

```
Current flow:
  AudioStream → pcm_bytes_from_audio_frame() → process_audio_chunk() → VAD + prosody

New flow:
  AudioStream → pcm_bytes_from_audio_frame()
                  ├─ process_audio_chunk()                 (existing — unchanged, never touched)
                  └─ transcription_stream.try_send(pcm, is_speech)
                       │                                   (NEW — non-blocking put_nowait)
                       └─ Background _sender_loop task:
                            ├─ Voiced frames → send to provider
                            ├─ Speech→silence edge: inject tail silence
                            │     (TAIL_SILENCE_MS of zero PCM so provider
                            │      sees real silence → endpointing fires)
                            ├─ After tail silence: KeepAlive only (not billed)
                            ├─ Silence→speech edge: resume sending audio
                            └─ On overflow: drop oldest, emit metric
```

### 3.3 New Files

```
backend/app/
  transcription/
    __init__.py
    stream.py           # TranscriptionStream — bounded queue + background sender
    buffer.py           # TranscriptBuffer — rolling window of recent utterances
    store.py            # TranscriptStore — full session transcript for persistence
    providers/
      __init__.py
      deepgram.py       # Deepgram Nova-2 streaming client
      assemblyai.py     # AssemblyAI real-time client (backup)
      mock.py           # Mock provider for testing
```

### 3.4 TranscriptionStream Design

```python
# ─── Droppable Queue ───────────────────────────────────────────────────
#
# Purpose-built single-consumer queue that supports selective audio-only
# drops without reaching into asyncio.Queue internals. Uses a deque for
# storage and an asyncio.Event to wake the consumer.
#
# Key properties:
#   1. put_nowait() from the audio loop — never blocks
#   2. async get() for the sender task — awaits event
#   3. Overflow drops oldest AUDIO item, NEVER control/stop
#   4. Items are consumed in stream order (controls stay in position,
#      not promoted ahead of pending audio)

@dataclass(frozen=True, slots=True)
class _QueueItem:
    """Typed queue item. kind determines drop eligibility."""
    kind: Literal["audio", "control", "stop"]
    payload: bytes | _TailInjection | None = None


@dataclass(frozen=True, slots=True)
class _TailInjection:
    """Cancelable tail-silence injection command.
    
    Carries a token that must match TranscriptionStream._tail_token at
    execution time. If speech resumes before the sender processes this,
    the token will have been incremented and the injection is silently
    skipped — preventing VAD flicker from burying real speech.
    """
    token: int


class DroppableAudioQueue:
    """Bounded queue: drops oldest AUDIO on overflow, never drops control/stop.
    
    Single-consumer: only one task should call get(). Multiple producers
    may call put_nowait() from any coroutine (but NOT from threads).
    
    Internally uses collections.deque (no asyncio.Queue internals touched)
    plus asyncio.Event for consumer wakeup.
    
    Overflow policy:
    - Audio items: oldest dropped first
    - Control items: coalesced — stale _TailInjection (token mismatch)
      dropped before accepting a new control. This bounds growth even
      in pathological cases where the buffer contains only controls.
    - Stop items: never dropped
    """

    def __init__(self, maxsize: int = 200):
        self._maxsize = maxsize
        self._buf: collections.deque[_QueueItem] = collections.deque()
        self._event = asyncio.Event()   # Signaled when items are available
        self._dropped_count = 0

    def put_nowait(self, item: _QueueItem) -> None:
        """Enqueue an item. If full, make room first.
        
        Priority: drop audio → coalesce stale controls → force-accept.
        """
        if len(self._buf) >= self._maxsize:
            if not self._drop_oldest_audio():
                # No audio to drop — try coalescing stale controls.
                # Stale _TailInjection items are guaranteed to be
                # skipped by the sender (token mismatch), so they
                # can safely be removed.
                self._coalesce_stale_controls()
        self._buf.append(item)
        self._event.set()

    async def get(self) -> _QueueItem:
        """Await and return the next item (FIFO). Single-consumer only."""
        while not self._buf:
            self._event.clear()
            await self._event.wait()
        item = self._buf.popleft()
        if not self._buf:
            self._event.clear()
        return item

    def _drop_oldest_audio(self) -> bool:
        """Remove the first audio item from the buffer. Returns True if dropped."""
        for i, queued in enumerate(self._buf):
            if queued.kind == "audio":
                del self._buf[i]
                self._dropped_count += 1
                return True
        return False

    def _coalesce_stale_controls(self) -> None:
        """Remove stale _TailInjection controls (will be skipped anyway).
        
        A tail injection becomes stale when try_send() increments the
        token (speech resumed). These items would be skipped by the
        sender, so removing them is safe. Stop items are never removed.
        
        This bounds queue growth even in pathological all-control
        scenarios (e.g., rapid VAD flicker producing many stale
        tail injections).
        """
        # Collect indices to remove (iterate in reverse to avoid shift)
        to_remove = []
        for i, queued in enumerate(self._buf):
            if (queued.kind == "control"
                    and isinstance(queued.payload, _TailInjection)):
                to_remove.append(i)
        # Remove oldest stale controls (keep at most 1 — the newest)
        for idx in reversed(to_remove[:-1] if to_remove else []):
            del self._buf[idx]
            self._dropped_count += 1

    def qsize(self) -> int:
        return len(self._buf)

    @property
    def dropped_count(self) -> int:
        return self._dropped_count


# ─── TranscriptionStream ──────────────────────────────────────────────

class TranscriptionStream:
    """Manages a streaming STT connection for one participant's audio.
    
    Audio delivery is fully decoupled from the caller:
    - try_send() does a non-blocking put_nowait() into DroppableAudioQueue
    - A background _sender_loop drains the queue → provider WebSocket
    - A background _receiver_loop reads provider responses → callbacks
    - On queue overflow: oldest AUDIO items are dropped; control items
      (tail injection, shutdown) are never dropped
    
    VAD edge tracking with explicit `_in_speech` state:
    - Tail injection fires ONLY on speech→silence transitions
    - No injection at session start, during initial silence, or after
      reconnects until the participant actually speaks
    - Cancelable via token at two points:
      1. Before injection starts (token check on dequeue)
      2. DURING injection (token re-checked each chunk) — handles
         the common case where speech resumes while injection is in
         progress (~800ms window)
    
    Tail injection pacing:
    - Tail silence is paced at real-time (30ms per chunk) using
      monotonic scheduling. Without pacing, ~800ms of audio-time
      silence is transmitted in <1ms wall time, which causes provider
      timestamps to advance faster than session clock — leading to
      cumulative timestamp drift of ~tail_duration per utterance.
    
    _tail_pending lifecycle:
    - Set True when tail injection is enqueued (speech→silence edge)
    - Set False when: speech resumes (cancels injection), injection
      completes successfully, or injection is canceled mid-flight
    - This ensures token is not unnecessarily incremented on the next
      speech frame after a completed injection
    
    Initial silence accounting:
    - Stream starts in "paused" state (clock.pause() called immediately)
    - First audio send calls clock.resume() → initial silence contributes
      to pause_offset → provider time 0 maps correctly to session time
    
    Tail silence length is config-driven:
      tail_silence_ms = settings.deepgram_endpointing_ms
    Rounded up to the next full chunk boundary via math.ceil.
    
    Utterance assembly (see §3.6):
    - Accumulate is_final:true segments into a pending utterance
    - On speech_final:true, concatenate accumulated segments → FinalUtterance
    - Generate stable utterance_id from `{role_key}:utt-{N}`
    - Partial revision counter managed locally
    
    Provider abstraction:
    - All provider interactions go through self._provider (STTProviderClient)
    - Version-pinned integration tests catch SDK breaking changes
    
    This design guarantees the existing audio analytics loop in
    _consume_audio_track() is NEVER blocked or slowed by STT latency.
    """

    RECEIVER_DRAIN_TIMEOUT = 5.0

    # Audio chunk timing constants (16kHz, 480 samples = 30ms)
    CHUNK_SAMPLES = 480
    CHUNK_BYTES = CHUNK_SAMPLES * 2   # 16-bit = 2 bytes/sample
    CHUNK_DURATION_S = CHUNK_SAMPLES / 16000  # 0.03

    def __init__(
        self,
        session_id: str,
        role: Role,
        student_index: int,
        clock: SessionClock,
        provider: STTProviderClient,
        tail_silence_ms: int | None = None,
        queue_max_size: int | None = None,
        keepalive_interval: float | None = None,
        on_partial: Callable[[PartialTranscript], Awaitable[None]] | None = None,
        on_final: Callable[[FinalUtterance], Awaitable[None]] | None = None,
        on_drop: Callable[[int], None] | None = None,
    ):
        self._session_id = session_id
        self._role = role
        self._role_key = f"{role.value}:{student_index}"
        self._clock = clock
        self._provider = provider
        self._tail_silence_ms = tail_silence_ms or settings.deepgram_endpointing_ms
        self._keepalive_interval = (
            keepalive_interval or settings.transcription_keepalive_interval_seconds
        )
        self._queue = DroppableAudioQueue(
            maxsize=queue_max_size or settings.transcription_queue_max_size
        )
        self._sender_task: asyncio.Task | None = None
        self._receiver_task: asyncio.Task | None = None
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_drop = on_drop

        # VAD edge state: explicit tracking prevents spurious tail injection
        # at session start, during initial silence, or after reconnects.
        self._in_speech: bool = False
        self._ever_spoken: bool = False

        # Cancelable tail injection.
        # Token semantics:
        # - try_send() increments token when speech resumes (cancels pending)
        # - Sender checks token before AND during injection (per chunk)
        # - _tail_pending tracks the full lifecycle:
        #   True  = injection enqueued, not yet started or in progress
        #   False = injection completed, canceled, or not pending
        self._tail_token: int = 0
        self._tail_pending: bool = False

        # Utterance assembly
        self._pending_segments: list[str] = []
        self._pending_words: list[WordTiming] = []
        self._pending_start_time: float | None = None
        self._utterance_counter: int = 0
        self._partial_revision: int = 0

        # Provider connection offset
        self._provider_time_zero: float | None = None

        # Audio sample counter — used by SessionClock for provider-time
        # anchoring on pause boundaries (see §3.8 pause math).
        self._samples_sent_to_provider: int = 0

        # Observability
        self._voiced_chunks_received = 0    # VAD=true frames into try_send()
        self._voiced_chunks_enqueued = 0    # Audio items accepted into queue
        self._dropped_audio_chunks = 0      # Audio items dropped by overflow
        self._total_chunks_sent = 0         # Audio chunks sent to provider
        self._silence_chunks_skipped = 0
        self._tail_silence_chunks_sent = 0
        self._tail_injections_canceled = 0  # Canceled before or during injection

    async def start(self):
        """Open provider connection and start sender + receiver tasks.
        
        The stream starts in "paused" state: clock.pause() is called
        immediately so that initial silence (before first speech)
        contributes to pause_offset. The sender loop calls clock.resume()
        on the first real audio send.
        """
        await self._provider.connect()
        self._provider_time_zero = self._clock.session_time()
        # Start paused — initial silence accumulates into pause_offset
        # so provider time 0 maps to the correct session time.
        self._clock.pause(self._role_key)
        self._sender_task = asyncio.create_task(
            self._sender_loop(), name=f"stt-sender-{self._role_key}"
        )
        self._receiver_task = asyncio.create_task(
            self._receiver_loop(), name=f"stt-receiver-{self._role_key}"
        )

    def try_send(self, pcm_chunk: bytes, is_speech: bool):
        """Non-blocking enqueue. Called from _consume_audio_track().
        
        NEVER blocks. Uses explicit `_in_speech` state to detect edges:
        
        - Only speech→silence edge triggers tail injection (not initial
          silence, not reconnect silence, not repeated silence frames)
        - Silence→speech edge cancels any pending tail injection via
          token increment (cancels both pre-dequeue AND mid-injection)
        - Speech frames always enqueued
        - Continued silence frames are skipped (counted for metrics)
        """
        if is_speech:
            self._voiced_chunks_received += 1
            self._ever_spoken = True
            # Cancel any pending tail injection (whether queued or mid-flight)
            if self._tail_pending:
                self._tail_token += 1
                self._tail_pending = False
            self._in_speech = True
            self._enqueue_audio(pcm_chunk)
            return

        # Silence frame
        if self._in_speech and not self._tail_pending:
            # Speech→silence edge (first silence frame after speech)
            self._in_speech = False
            self._tail_pending = True
            self._enqueue_control(_TailInjection(token=self._tail_token))
            return

        # Continued silence (or initial silence before any speech)
        self._silence_chunks_skipped += 1

    def _enqueue_audio(self, pcm_chunk: bytes):
        """Enqueue audio. DroppableAudioQueue handles overflow."""
        prev_dropped = self._queue.dropped_count
        self._queue.put_nowait(_QueueItem(kind="audio", payload=pcm_chunk))
        if self._queue.dropped_count > prev_dropped:
            self._dropped_audio_chunks = self._queue.dropped_count
            if self._on_drop:
                self._on_drop(self._dropped_audio_chunks)
        else:
            self._voiced_chunks_enqueued += 1

    def _enqueue_control(self, payload: _TailInjection):
        """Enqueue a control item. Never dropped."""
        self._queue.put_nowait(_QueueItem(kind="control", payload=payload))

    async def _sender_loop(self):
        """Background task: drain queue → provider.
        
        Handles audio, cancelable tail injection, KeepAlive, and shutdown.
        Uses time.monotonic() for all timing (no wall-clock jumps).
        
        Items are consumed in stream order — controls are NOT promoted
        ahead of pending audio, preserving the temporal relationship
        between speech frames and tail injection.
        
        Tail injection is:
        1. Cancelable before start (token check on dequeue)
        2. Cancelable DURING injection (token re-checked each chunk)
        3. Paced at real-time (30ms per chunk) to prevent provider
           timestamp drift — see §3.5 "Tail injection pacing"
        """
        last_keepalive_mono = time.monotonic()

        while True:
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._keepalive_interval
                )
            except asyncio.TimeoutError:
                now_mono = time.monotonic()
                if now_mono - last_keepalive_mono >= self._keepalive_interval:
                    await self._provider.send_keep_alive()
                    last_keepalive_mono = now_mono
                continue

            if item.kind == "stop":
                await self._provider.send_close_stream()
                break

            if item.kind == "control" and isinstance(item.payload, _TailInjection):
                inj_token = item.payload.token

                # ── Pre-start cancellation ──
                # If speech resumed since enqueue, token has been incremented.
                if inj_token != self._tail_token:
                    self._tail_injections_canceled += 1
                    # _tail_pending already cleared by try_send()
                    continue

                # ── Paced injection with per-chunk cancellation ──
                # Inject zero-PCM ≥ endpointing_ms. Paced at real-time
                # (30ms per chunk) so provider timestamps advance in
                # lockstep with session clock. Without pacing, ~800ms
                # of "audio time" transmits in <1ms wall time, causing
                # cumulative drift of ~tail_duration per utterance.
                tail_samples = math.ceil(
                    16000 * self._tail_silence_ms / 1000
                )
                num_chunks = math.ceil(tail_samples / self.CHUNK_SAMPLES)
                zero_chunk = bytes(self.CHUNK_BYTES)

                injection_start = time.monotonic()
                canceled_mid_flight = False

                for i in range(num_chunks):
                    # ── Mid-injection cancellation ──
                    # Speech can resume while we're injecting (~800ms window).
                    # Re-check token each chunk. If speech resumed, try_send()
                    # will have incremented token and cleared _tail_pending.
                    if inj_token != self._tail_token:
                        self._tail_injections_canceled += 1
                        canceled_mid_flight = True
                        break

                    await self._provider.send_audio(zero_chunk)
                    self._tail_silence_chunks_sent += 1
                    self._samples_sent_to_provider += self.CHUNK_SAMPLES

                    # Real-time pacing: sleep until the next chunk boundary.
                    target = injection_start + (i + 1) * self.CHUNK_DURATION_S
                    now = time.monotonic()
                    if target > now:
                        await asyncio.sleep(target - now)

                if not canceled_mid_flight:
                    # Injection completed successfully
                    self._tail_pending = False
                    self._clock.pause(
                        self._role_key,
                        provider_audio_time=self._provider_audio_time(),
                    )
                # If canceled mid-flight, _tail_pending was already cleared
                # by try_send() when it incremented the token.
                continue

            if item.kind == "audio":
                # Resume clock on first audio send (handles initial silence).
                # Also resumes after a completed tail injection.
                self._clock.resume(self._role_key)
                await self._provider.send_audio(item.payload)
                self._samples_sent_to_provider += self.CHUNK_SAMPLES
                self._total_chunks_sent += 1

    def _provider_audio_time(self) -> float:
        """Current provider-relative audio time from sample counter."""
        return self._samples_sent_to_provider / 16000

    async def _receiver_loop(self):
        """Receive and process STT responses from the provider.
        
        Deepgram response handling (see §3.6):
        - interim (is_final=false): emit PartialTranscript with local revision
        - is_final=true, speech_final=false: accumulate segment
        - speech_final=true: concatenate segments → FinalUtterance
        
        Provider timestamps are converted via _map_provider_time() which
        accounts for connection offset + accumulated pause offsets.
        """
        async for response in self._provider.receive_results():
            if response.is_partial:
                if self._on_partial:
                    self._partial_revision += 1
                    partial = PartialTranscript(
                        utterance_id=f"{self._role_key}:utt-{self._utterance_counter}",
                        revision=self._partial_revision,
                        role=self._role.value,
                        text=self._pending_text() + " " + response.text,
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
                        utterance_id=f"{self._role_key}:utt-{self._utterance_counter}",
                        role=self._role.value,
                        text=full_text,
                        start_time=self._map_provider_time(
                            self._pending_start_time or response.start
                        ),
                        end_time=self._map_provider_time(response.end),
                        confidence=response.confidence,
                        sentiment=response.sentiment,
                        sentiment_score=response.sentiment_score,
                        words=self._pending_words or None,
                    )
                    await self._on_final(utterance)

                self._pending_segments.clear()
                self._pending_words.clear()
                self._pending_start_time = None
                self._partial_revision = 0
                self._utterance_counter += 1

    def _map_provider_time(self, provider_audio_time: float) -> float:
        """Convert provider audio-relative timestamp to session time.
        
        Formula: connection_offset + provider_audio_time + pause_offset
        
        - connection_offset: session time when provider WS opened
        - pause_offset: accumulated silence gaps (from SessionClock)
        """
        base = self._provider_time_zero or 0.0
        return base + self._clock.provider_to_session_time(
            provider_audio_time, self._role_key
        )

    def _pending_text(self) -> str:
        return " ".join(self._pending_segments)

    async def stop(self) -> list[FinalUtterance]:
        """Orderly shutdown:
        1. Enqueue stop sentinel (uses put_nowait — always accepted)
        2. Await sender (sends CloseStream to provider)
        3. Await receiver drain (with timeout) for final responses
        4. Close provider connection
        """
        self._queue.put_nowait(_QueueItem(kind="stop"))
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
        return await self._flush_pending()

    async def handle_reconnect(self):
        """Handle provider WebSocket reconnect.
        
        Provider timestamps restart from 0 on each new connection.
        - Reset connection offset to current session time
        - Clear stale pause offsets
        - Reset VAD state (don't inject tail for pre-reconnect speech)
        - Do NOT clear pending segments (let current utterance finalize
          naturally or timeout)
        """
        self._provider_time_zero = self._clock.session_time()
        self._clock.reset_pauses(self._role_key)
        self._in_speech = False
        self._tail_pending = False
        # Start paused again until first post-reconnect speech
        self._clock.pause(self._role_key)

    @property
    def drop_rate(self) -> float:
        """Audio drop rate for backpressure level decisions.
        
        Denominator: voiced_chunks_received (VAD=true frames into try_send).
        This is the right denominator because only voiced frames are
        enqueue candidates. Tail silence chunks are excluded (they are
        synthetic, not user audio).
        """
        if self._voiced_chunks_received == 0:
            return 0.0
        return self._dropped_audio_chunks / self._voiced_chunks_received

    @property
    def stats(self) -> dict:
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
        }
```

### 3.5 VAD-Gated Audio with Tail-Silence Injection

#### The problem: VAD gating vs provider endpointing

Deepgram's endpointing fires after detecting a **configured duration of silence
in the incoming audio stream** (`endpointing=<ms>`). If we stop sending audio
entirely during silence (KeepAlive only), the provider's audio clock pauses
and endpointing never fires — because it never sees "silence audio," only
"no audio."

**This means naively skipping all silence audio breaks utterance boundary
detection.**

#### The solution: tail-silence injection (Option A)

When local VAD transitions from speech→silence:

1. **Inject zero-PCM equal to the endpointing duration** so Deepgram receives
   enough real silence in the audio stream for its endpointing to fire.
2. **After tail silence sent**, switch to KeepAlive-only mode.
3. **On silence→speech transition**, resume sending real audio normally.

**Critical:** The tail silence length is **config-driven, not a constant**:
```python
tail_silence_ms = settings.deepgram_endpointing_ms  # default 800ms
```
This guarantees the provider always sees enough silence to trigger endpointing.
Setting it lower than `endpointing_ms` would risk `speech_final` never firing.

#### Cancelable tail injection (VAD flicker protection)

VAD can briefly drop to silence for 1-2 frames due to noise, plosives, or
aggressive thresholds. Without protection, this causes the sender to inject
~800ms of zeros *burying* the real speech that resumes immediately after.

**Fix: tokenized injection commands with two cancellation points.**

Each `_TailInjection` carries a token. Cancellation is checked:
1. **Before injection starts** (on dequeue) — catches most VAD flicker
2. **During injection, each chunk** — handles speech resuming partway
   through the ~800ms injection window (common in real-world VAD)

```
Timeline (without cancellation — BAD):

  ┌── Speech ──┐ ┌silence┐ ┌── Speech ──────────────────┐
  │ real audio  │ │2 frms │ │ real audio resumes         │
  └─────────────┘ └───────┘ └───────────────────────────┘
                     ↓
              Tail injected (800ms zeros)
              BURIES the resuming speech!

Timeline (cancel before start — GOOD):

  ┌── Speech ──┐ ┌silence┐ ┌── Speech ──────────────────┐
  │ real audio  │ │2 frms │ │ real audio resumes         │
  └─────────────┘ └───────┘ └───────────────────────────┘
                     ↓           ↓
              Tail enqueued   Token incremented →
              (token=5)       sender sees token≠5, skips

Timeline (cancel mid-flight — GOOD):

  ┌─ Speech ─┐ ┌silence┐ ┌ tail start ┐ ┌── Speech ─────┐
  │ real      │ │10 frms│ │ 200ms sent │ │ resumes       │
  └───────────┘ └───────┘ └────────────┘ └───────────────┘
                              ↓               ↓
                      Sender is injecting   Token incremented →
                      (token=5, sending     sender checks token≠5
                       zero chunks)         at next chunk → aborts
```

```
Timeline (real speech end — tail fires correctly):

  ┌─── Speech ───┐  ┌─ Tail ────┐  ┌── KeepAlive only ──┐
  │ real audio    │  │ 800ms     │  │ no audio sent       │
  │ sent normally │  │ zero PCM  │  │ KeepAlive every 5s  │
  │               │  │ (billed)  │  │ (not billed*)       │
  └───────────────┘  └───────────┘  └─────────────────────┘
                          │
                   Provider sees 800ms silence,
                   endpointing fires,
                   speech_final emitted

  * KeepAlive billing: we assume KeepAlive control messages do not
    contribute to billed audio seconds (no audio is sent). Verified
    via cost telemetry reconciliation against provider invoices.
```

#### `_tail_pending` lifecycle

`_tail_pending` tracks whether a tail injection is in-flight:

| Event | `_tail_pending` | `_tail_token` |
|---|---|---|
| Speech→silence: control enqueued | → `True` | unchanged |
| Speech resumes (try_send): cancel | → `False` | `+= 1` |
| Sender: pre-start token mismatch | already `False`* | unchanged |
| Sender: mid-flight token mismatch | already `False`* | unchanged |
| Sender: injection completes | → `False` | unchanged |

*try_send() already cleared it when incrementing the token.

#### Tail injection pacing (real-time)

**Problem:** Without pacing, the sender transmits ~800ms of zero-PCM in a
tight loop that completes in <1ms wall time. The provider's audio clock
advances by 800ms but session clock advances by <1ms. This causes
**cumulative timestamp drift of ~tail_duration per utterance**: each
utterance's timestamps shift later by ~0.8s relative to session time.

Over a 60-minute session with ~15 speech segments, that's ~12s of
accumulated drift — enough to visibly misalign transcripts with the
session timeline and corrupt key-moment detection.

**Fix:** Pace tail injection at real-time using monotonic scheduling:

```python
injection_start = time.monotonic()
for i in range(num_chunks):
    if inj_token != self._tail_token:  # Mid-injection cancel
        break
    await self._provider.send_audio(zero_chunk)
    target = injection_start + (i + 1) * CHUNK_DURATION_S  # 0.03s
    now = time.monotonic()
    if target > now:
        await asyncio.sleep(target - now)
```

This ensures provider audio time and session wall time advance in lockstep
during tail injection. The 30ms-per-chunk pacing also provides natural
"check points" for mid-injection cancellation (token checked each chunk).

#### Queue overflow: DroppableAudioQueue

The queue can overflow under backpressure. `DroppableAudioQueue` (§3.4)
implements a purpose-built bounded queue using `collections.deque` +
`asyncio.Event` (no `asyncio.Queue` internal access):

- **Audio items**: droppable (oldest first)
- **Control items** (tail injection): never dropped — losing them breaks
  endpointing boundary detection
- **Stop sentinel**: never dropped — losing it prevents clean shutdown

Controls maintain stream order (NOT promoted ahead of pending audio).
This is critical: promoting a tail injection ahead of queued speech frames
would inject silence *before* the speech it's supposed to follow.

#### Why Option A over Option B (client-side Finalize)

| | Option A (tail-silence) | Option B (Finalize on VAD stop) |
|---|---|---|
| Utterance boundaries | Provider-consistent (`speech_final`) | Client-controlled (VAD turn counter) |
| Complexity | Lower — provider handles segmentation | Higher — own boundary semantics |
| Deepgram compatibility | Uses standard endpointing flow | `from_finalize` response "not guaranteed" |
| Cost | ~endpointing_ms × N segments | Slightly lower (no tail silence) |
| Reliability | High — endpointing is battle-tested | Medium — edge cases with Finalize |

**We pick Option A.** At ~800ms tail per speech segment (~15 segments in a
60-min session = ~12 extra billed seconds), the cost is negligible and
utterance boundaries are fully provider-determined.

#### Integration into `_consume_audio_track()`

```python
async def _consume_audio_track(self, *, track_sid, track, role, student_index=0):
    stream = rtc.AudioStream.from_track(...)
    
    # Start transcription stream (if enabled)
    transcription_stream = await self._get_or_create_transcription_stream(
        role, student_index
    )
    
    try:
        async for event in stream:
            pcm = pcm_bytes_from_audio_frame(event.frame)
            if pcm:
                # Existing analytics (UNCHANGED — never touched)
                await process_audio_chunk(self.session, role, pcm, ...)
                
                # Get VAD result from the session's audio processor
                resources = get_or_create_resources(self.session)
                processor_key = (
                    f"audio_{role.value}" if student_index == 0
                    else f"audio_student_{student_index}"
                )
                audio_result = resources[processor_key].last_result
                
                # NEW: Send to STT — non-blocking, VAD-gated with tail silence
                if transcription_stream is not None:
                    transcription_stream.try_send(
                        pcm,
                        is_speech=audio_result.is_speech,
                    )
    finally:
        if transcription_stream is not None:
            await transcription_stream.stop()
        await stream.aclose()
```

**Cost impact:** For a 60-minute session where each participant speaks ~40% of
the time with ~15 speech segments, VAD gating with tail silence reduces billed
STT from 60 minutes to ~25 minutes + ~9 seconds of tail — a **~58% cost
reduction** while preserving provider endpointing.

### 3.6 Provider Endpointing and `is_final` Concatenation

#### How Deepgram endpointing works

Deepgram produces three types of transcript responses during streaming:

1. **Interim results** (`is_final: false`): Best-guess partial transcript.
   Changes as more audio arrives. Used for live "typing..." display only.

2. **Finalized segments** (`is_final: true`, `speech_final: false`): A segment
   of transcript that Deepgram has committed to and will not revise. But the
   *utterance* is not yet complete — more segments may follow.

3. **Speech-final** (`speech_final: true`): The utterance boundary. Deepgram
   has detected enough silence (per `endpointing` config) to conclude this
   speech turn is done.

**Critical:** An utterance is built by **concatenating all `is_final: true`
segments until `speech_final: true` arrives.** This is Deepgram's own guidance
and it affects how we generate `utterance_id`, what we send as partial vs
final to the frontend, and what we store.

```
Provider response stream for one utterance:

  interim:     "I think"                    → update partial in UI
  interim:     "I think maybe"              → update partial in UI
  is_final:    "I think maybe it's"         → accumulate segment #1
  interim:     "the derivative"             → update partial in UI (prepend segment #1)
  is_final:    "the derivative"             → accumulate segment #2
  speech_final: ""                          → concatenate: "I think maybe it's the derivative"
                                              → emit FinalUtterance
```

#### Why this matters for the TranscriptionStream

- **`utterance_id`** is generated from our own turn counter (incremented on
  each `speech_final`), NOT from provider IDs.
- **Partial transcripts** sent to the UI include accumulated `is_final` text
  + current interim text, so the partial always shows the full in-progress
  utterance.
- **`FinalUtterance`** is only emitted on `speech_final`, containing the
  concatenation of all accumulated `is_final` segments.
- **Word timings** are accumulated across segments and included in the final.

#### Provider configuration

```python
deepgram_options = {
    "model": "nova-2",
    "language": "en",
    "encoding": "linear16",
    "sample_rate": 16000,
    "channels": 1,
    "punctuate": True,
    "endpointing": 800,         # 800ms silence in audio → speech_final
    "interim_results": True,    # Required for live partial display
    "smart_format": True,
    # Optional — gate behind language support:
    # "sentiment": True,        # English only per Deepgram docs
    #
    # NOTE: utterance_end_ms / UtteranceEnd is NOT used in Tier 1.
    # If enabled later, it requires BOTH of these settings:
    #   "utterance_end_ms": 1200,  # UtteranceEnd after 1.2s gap
    #   "vad_events": True,        # Required to receive UtteranceEnd events
    # We rely solely on `speech_final` (from `endpointing`) for utterance
    # boundaries in Tier 1.
}
```

**Note on tail silence interaction:** Our tail-silence injection (§3.5, duration = `endpointing_ms`)
gives Deepgram enough silence audio for its 800ms endpointing timer to start.
Combined with any natural trailing silence the speaker produced, this reliably
triggers `speech_final`. If endpointing still doesn't fire within 2s of tail
injection, the sender loop can fall back to sending a `Finalize` message as
a safety net.

### 3.7 Data Models

```python
@dataclass
class PartialTranscript:
    """Intermediate, still-changing transcript (for live display).
    
    Includes a stable utterance_id so the UI can update existing lines
    instead of appending new ones (prevents jitter/spam).
    """
    utterance_id: str          # Stable ID across revisions of same utterance
    revision: int              # Increments as partial updates come in
    role: str                  # "tutor" or "student"
    text: str                  # Current partial text
    confidence: float          # 0-1
    session_time: float        # Seconds from session start (see §3.8 Time Alignment)

@dataclass
class FinalUtterance:
    """A completed utterance from the STT provider (speech_final=true).
    
    Boundary determined by provider endpointing, NOT custom segmentation.
    """
    utterance_id: str
    role: str
    text: str
    start_time: float          # Seconds from session start
    end_time: float
    confidence: float
    sentiment: str | None      # "positive" | "negative" | "neutral" (English only, may be None)
    sentiment_score: float     # -1.0 to 1.0 (0.0 if sentiment unavailable)
    words: list[WordTiming] | None  # Per-word timestamps (for highlight sync)
    student_index: int = 0     # For multi-student sessions

@dataclass
class WordTiming:
    word: str
    start: float               # Seconds from session start
    end: float
    confidence: float
```

### 3.8 Time Alignment with Audio Gating

**Problem:** STT provider timestamps are relative to the **audio stream**,
not session wall time. When we gate audio (KeepAlive-only during silence),
the provider's audio clock pauses but session time keeps ticking. Without
correction, transcript timestamps will drift earlier and earlier relative
to the actual session timeline whenever there are long silent stretches.

**Example of the drift problem:**
```
Session time:   0s ──── 30s ──── 60s ──── 90s ──── 120s
Audio sent:     0s ──── 30s       (silence 30s)     60s ──── 90s
Provider clock: 0s ──── 30s ─────────────────────── 30s ──── 60s
                                                    ↑ Provider thinks
                                                      this is t=30s
                                                      but it's really t=90s
```

**Solution:** Maintain an accumulated **pause offset** that tracks how much
session time elapsed while audio was not being sent:

```python
@dataclass
class _PauseSegment:
    """A completed pause: provider audio time at pause start + wall duration."""
    provider_time_start: float   # Provider audio-time when pause began
    duration_s: float            # Wall-clock duration of the pause


@dataclass
class _ActivePause:
    """An in-progress pause (not yet completed via resume())."""
    provider_time_start: float   # Provider audio-time when pause began
    wall_start_mono: float       # time.monotonic() when pause began


class SessionClock:
    """Single source of truth for session-relative timestamps.
    
    Handles three time-alignment problems:
    
    1. Audio gating: provider audio clock pauses during KeepAlive-only
       periods. Pause segments record the provider audio time at which
       each pause began, so late-arriving STT results (timestamps
       before the pause boundary) are NOT shifted by that pause.
    
    2. Delayed start / initial silence: TranscriptionStream starts each
       track in "paused" state. The sender calls resume() on the first
       real audio send. Initial silence contributes to pause_offset.
    
    3. Reconnects: provider timestamps restart from 0. TranscriptionStream
       calls reset_pauses() and re-enters paused state.
    
    Conversion formula:
      session_time = connection_offset + provider_audio_time + applicable_pause_offset
    
    Unlike the simpler "add total pause offset" approach, this version
    only adds pause durations for pauses whose provider_time_start <=
    the provider timestamp being mapped. This prevents late-arriving
    STT results (network jitter, provider batching) from being shifted
    forward by a pause that hadn't started yet in provider-time.
    
    All internal timing uses time.monotonic() (no wall-clock jumps).
    """
    
    def __init__(self):
        self._session_start: float = time.monotonic()
        # Per-track pause segments (completed pauses)
        self._pause_segments: dict[str, list[_PauseSegment]] = {}
        # Per-track active pause (in progress, not yet resumed)
        self._active_pause: dict[str, _ActivePause | None] = {}
    
    def session_time(self) -> float:
        """Current session-relative time in seconds (monotonic clock)."""
        return time.monotonic() - self._session_start
    
    def pause(self, role_key: str, provider_audio_time: float = 0.0):
        """Mark that audio sending has paused for this track.
        
        Args:
            role_key: Track identifier
            provider_audio_time: Provider-relative audio time at which
                the pause begins (from sample counter). Used to anchor
                the pause so only timestamps >= this point get the
                offset applied.
        
        Called by sender loop after tail silence injection completes,
        and by start() for initial silence accounting.
        """
        if self._active_pause.get(role_key) is None:
            self._active_pause[role_key] = _ActivePause(
                provider_time_start=provider_audio_time,
                wall_start_mono=time.monotonic(),
            )
    
    def resume(self, role_key: str):
        """Mark that audio sending has resumed for this track.
        
        Moves the active pause to pause_segments with its wall duration.
        """
        active = self._active_pause.get(role_key)
        if active is not None:
            duration = time.monotonic() - active.wall_start_mono
            segments = self._pause_segments.setdefault(role_key, [])
            segments.append(_PauseSegment(
                provider_time_start=active.provider_time_start,
                duration_s=duration,
            ))
            self._active_pause[role_key] = None
    
    def reset_pauses(self, role_key: str):
        """Reset pause tracking for a track (used on provider reconnect)."""
        self._pause_segments.pop(role_key, None)
        self._active_pause.pop(role_key, None)
    
    def provider_to_session_time(
        self,
        provider_audio_time: float,
        role_key: str,
    ) -> float:
        """Convert a provider audio-relative timestamp to a pause-adjusted value.
        
        Only adds pause durations for pauses whose provider_time_start <=
        the timestamp being mapped. This handles late-arriving STT results
        correctly — a result timestamped before a pause boundary won't be
        shifted by that pause.
        
        NOTE: Returns provider_audio_time + applicable_pause_offset only.
        The caller (TranscriptionStream._map_provider_time) adds the
        connection offset.
        """
        total_offset = 0.0

        # Completed pauses
        for seg in self._pause_segments.get(role_key, []):
            if provider_audio_time >= seg.provider_time_start:
                total_offset += seg.duration_s

        # Active (in-progress) pause
        active = self._active_pause.get(role_key)
        if active is not None and provider_audio_time >= active.provider_time_start:
            total_offset += time.monotonic() - active.wall_start_mono

        return provider_audio_time + total_offset
```

**Integration points:**
- **`start()`**: sets `_provider_time_zero`, immediately calls
  `clock.pause(role_key, provider_audio_time=0.0)` → initial silence
  accumulates as pause_offset anchored at provider time 0
- **Sender loop**: calls `clock.resume()` before first audio send.
  Calls `clock.pause(role_key, provider_audio_time=X)` after tail injection,
  where X is the current `_provider_audio_time()` from the sample counter.
- **`_map_provider_time()`**: combines `connection_offset + clock.provider_to_session_time()`
- **`handle_reconnect()`**: resets `_provider_time_zero`, calls `clock.reset_pauses()`,
  re-enters paused state, resets VAD edge state

**Example: initial silence accounting**
```
Session starts at t=0. Student doesn't speak until t=40.
  - start() at t=10: _provider_time_zero = 10
    clock.pause("student:0", provider_audio_time=0.0)
  - t=10..40: silence frames → try_send skips (no _in_speech, no tail)
  - t=40: first speech → sender sends audio, calls clock.resume()
    → pause_segment: { provider_time_start=0.0, duration=30.0 }
  - Provider time 0 → clock maps: 0.0 + 30.0 (pause applies: 0.0 >= 0.0)
    → _map_provider_time(0) = 10 + 30 = 40 ✓
```

**Example: late-arriving result after pause**
```
Speech from provider t=2.0..5.0. Tail injection at provider t=5.0.
clock.pause("student:0", provider_audio_time=5.0)
  - An is_final result arrives with timestamp 4.8 (before the pause):
    → pause at t=5.0 does NOT apply (4.8 < 5.0)
    → Correct: no extra offset added for this result
  - Next speech resumes. An is_final result arrives with timestamp 5.5:
    → pause at t=5.0 DOES apply (5.5 >= 5.0)
    → Correct: pause duration added to align with session time
```

### 3.9 STTProviderClient Abstraction

```python
class STTProviderClient(Protocol):
    """Abstract interface for STT provider WebSocket connections.
    
    TranscriptionStream interacts with the provider exclusively through
    this interface, making it easy to:
    - Swap providers (Deepgram → AssemblyAI)
    - Inject a mock for testing
    - Pin and test against specific SDK versions
    
    Method names are our own convention. The concrete implementation
    maps them to SDK-specific calls (e.g., Deepgram Python SDK v6
    uses send(), keep_alive(), finalize(), close()).
    """

    async def connect(self) -> None:
        """Open the streaming WebSocket connection."""
        ...

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Send a raw PCM audio chunk to the provider."""
        ...

    async def send_keep_alive(self) -> None:
        """Send a KeepAlive control message (not billed)."""
        ...

    async def send_finalize(self) -> None:
        """Request the provider finalize any buffered audio (safety net)."""
        ...

    async def send_close_stream(self) -> None:
        """Signal end-of-stream for final flush and metadata."""
        ...

    async def receive_results(self) -> AsyncIterator[ProviderResponse]:
        """Yield parsed STT responses from the provider."""
        ...

    async def close(self) -> None:
        """Close the WebSocket connection."""
        ...


class DeepgramSTTClient(STTProviderClient):
    """Concrete Deepgram implementation using deepgram-python-sdk.
    
    Maps our interface to SDK v6 methods:
    - send_audio()       → connection.send(data)
    - send_keep_alive()  → connection.keep_alive()
    - send_finalize()    → connection.finalize()
    - send_close_stream()→ connection.finish()
    - receive_results()  → event-based → asyncio.Queue adapter
    
    IMPORTANT: Pin SDK version in requirements.txt and add an integration
    test that verifies these method names still exist. SDK upgrades have
    renamed methods in the past (v5 → v6 migration).
    """
    
    def __init__(self, api_key: str, options: dict):
        self._api_key = api_key
        self._options = options
        self._client = None
        self._connection = None
        self._response_queue: asyncio.Queue[ProviderResponse] = asyncio.Queue()
    
    async def connect(self) -> None:
        self._client = DeepgramClient(self._api_key)
        self._connection = self._client.listen.asyncwebsocket.v("1")
        # Register event handlers that push to _response_queue
        self._connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
        await self._connection.start(LiveOptions(**self._options))

    # ... (implementation maps events → ProviderResponse → queue)
```

> **Version pinning:** Add `deepgram-sdk>=6.0,<7.0` to requirements and a
> test that imports the SDK and asserts `keep_alive`, `finalize`, `finish`
> methods exist on the connection object. This catches SDK breaking changes
> before they reach production.

### 3.10 TranscriptBuffer (Rolling Window)

```python
class TranscriptBuffer:
    """Rolling window of recent utterances for real-time analysis.
    
    Maintains per-role utterance history. Used by:
    - AI coaching copilot (last 90s of context)
    - Uncertainty detector (student recent text)
    - Frontend transcript panel (last N messages)
    """

    def __init__(self, window_seconds: float = 120.0):
        self._utterances: deque[FinalUtterance] = deque()
        self._window_seconds = window_seconds

    def add(self, utterance: FinalUtterance):
        self._utterances.append(utterance)
        self._trim()

    def recent_text(self, seconds: float = 90.0) -> str:
        """Get formatted transcript of last N seconds.
        
        Returns:
            "[Tutor]: Can you explain what a derivative is?\n"
            "[Student]: Um... I think it's like... the slope of something?"
        """
        ...

    def student_recent_text(self, seconds: float = 30.0) -> str:
        """Get only student utterances for uncertainty analysis."""
        ...

    def word_count_by_role(self, seconds: float = 60.0) -> dict[str, int]:
        """Word counts per role in the window."""
        ...

    def last_topic_keywords(self, n: int = 5) -> list[str]:
        """Extract likely topic keywords from tutor questions.
        
        Note: TF-IDF on tiny windows is noisy. Instead, extract keywords
        primarily from TUTOR utterances (they carry topic intent) combined
        with a curated subject-vocabulary list. Upgrade to embeddings or
        post-session LLM extraction later if needed.
        """
        ...
```

### 3.11 TranscriptStore — Size Control

**Problem:** Storing word-level timings for a full hour can produce 5-10MB of
JSON per session, which is too large for Postgres JSONB.

**Solution:** Tiered storage:

```python
class TranscriptStore:
    """Full session transcript with tiered storage.
    
    - Postgres: summary + searchable full text (no word timings)
    - S3/R2: full artifact with word timings (using existing s3_trace_store.py)
    - Word timings retained in-memory only for:
      - Last N minutes (for live features)
      - Key moments (flagged by uncertainty/coaching)
    """
    
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._utterances: list[FinalUtterance] = []
        self._key_moment_utterance_ids: set[str] = set()
    
    def add(self, utterance: FinalUtterance):
        self._utterances.append(utterance)
    
    def mark_key_moment(self, utterance_id: str):
        """Preserve word timings for this utterance (it's a key moment)."""
        self._key_moment_utterance_ids.add(utterance_id)
    
    def to_postgres_payload(self) -> dict:
        """Compact representation for Postgres JSONB storage.
        
        Includes full text but strips word-level timings (except key moments).
        """
        return {
            "session_id": self._session_id,
            "utterances": [
                {
                    "role": u.role,
                    "text": u.text,
                    "start_time": u.start_time,
                    "end_time": u.end_time,
                    "sentiment": u.sentiment,
                    # Only include word timings for key moments
                    "words": [w.__dict__ for w in (u.words or [])]
                    if u.utterance_id in self._key_moment_utterance_ids
                    else None,
                }
                for u in self._utterances
            ],
            "total_words": self._count_words(),
            "searchable_text": self._to_searchable_text(),
        }
    
    def to_s3_artifact(self) -> dict:
        """Full artifact with all word timings for S3/R2 storage."""
        return {
            "session_id": self._session_id,
            "utterances": [u.__dict__ for u in self._utterances],
        }
```

### 3.12 Sending Transcripts to Frontend

Two delivery paths (matching existing metrics/nudge pattern):

**A. Real-time transcripts via LiveKit data packets:**
```python
TOPIC_TRANSCRIPT_PARTIAL = "lsa.transcript.partial.v1"
TOPIC_TRANSCRIPT_FINAL = "lsa.transcript.final.v1"
```

**B. WebSocket fallback:**
```python
# New WSMessage types
{"type": "transcript_partial", "data": {"utterance_id": "abc123", "revision": 3, "role": "student", "text": "I think maybe..."}}
{"type": "transcript_final", "data": {"utterance_id": "abc123", "role": "student", "text": "I think maybe it's the derivative?", ...}}
```

**Important:** Partial transcripts include a stable `utterance_id` and
`revision` so the frontend can update existing lines instead of appending
new ones. Without this, the UI will show jittery, spammy transcript updates.

### 3.13 Student-Only Transcription (Pilot Mode)

For the initial production pilot, consider enabling transcription for
**student audio only**. This:

- **Halves STT cost** (~$0.14/session instead of ~$0.28)
- **Reduces privacy exposure** (tutor speech is not transcribed)
- **Eliminates cross-talk risk** (tutor mic picking up student audio)
- **Still enables the full AI copilot** — the copilot primarily needs student
  speech to detect uncertainty and suggest responses

Tutor transcription can be kept behind a separate flag for internal testing:

```python
transcription_roles: list[str] = ["student"]  # ["student"] or ["tutor", "student"]
```

### 3.14 Vendor Feature Gating

Deepgram's sentiment analysis is **English-only**. Don't hard-require sentiment
in the core data model:

```python
@dataclass
class FinalUtterance:
    # ...
    sentiment: str | None = None         # None when language not supported
    sentiment_score: float = 0.0         # 0.0 when unavailable — not an error
```

Gate sentiment features behind language + model support:
```python
def _provider_supports_sentiment(language: str, model: str) -> bool:
    """Check if the provider/model combination supports sentiment."""
    if settings.transcription_provider == "deepgram":
        return language.startswith("en") and model in ("nova-2", "nova-3")
    return False
```

### 3.15 Configuration

New settings in `config.py` (defaults shown — override via `LSA_` env vars):

```python
# Transcription
enable_transcription: bool = False
transcription_provider: str = "assemblyai"    # "assemblyai" | "deepgram" | "mock"
transcription_roles: list[str] = ["student"]  # Student-only for pilot (halves cost + privacy)
assemblyai_api_key: str = ""                  # Get from https://www.assemblyai.com/
deepgram_api_key: str = ""                    # Alternative provider
transcription_language: str = "en"
transcription_model: str = "nova-2"           # Deepgram model (ignored for AssemblyAI)
transcription_enable_sentiment: bool = False  # Gate behind language support; Deepgram-only
transcription_buffer_window_seconds: float = 120.0  # Rolling window for AI context
transcription_queue_max_size: int = 200       # ~6s buffer at 16kHz/480-sample
transcription_keepalive_interval_seconds: float = 8.0
deepgram_endpointing_ms: int = 800            # Must match tail silence injection duration
deepgram_mip_opt_out: bool = True             # Opt out of Deepgram model training

# Uncertainty Detection
enable_uncertainty_detection: bool = False
uncertainty_persistence_utterances: int = 2   # Must sustain 2+ utterances before surfacing
uncertainty_persistence_window_seconds: float = 45.0

# AI Coaching Copilot
enable_ai_coaching: bool = False
ai_coaching_provider: str = "openrouter"      # "openrouter" | "anthropic"
ai_coaching_model: str = "anthropic/claude-3.5-haiku"  # OpenRouter model ID
openrouter_api_key: str = ""                  # Get from https://openrouter.ai/
anthropic_api_key: str = ""                   # Only if ai_coaching_provider = "anthropic"
ai_coaching_baseline_interval_seconds: float = 45.0   # Check every 45s
ai_coaching_burst_interval_seconds: float = 15.0      # Burst on high uncertainty
ai_coaching_max_calls_per_hour: int = 60      # Hard budget cap
```

### 3.16 Observability

Record per-session and expose in trace artifacts:

```python
@dataclass
class TranscriptionStats:
    """Per-session transcription observability metrics.
    
    Metric naming convention (for backpressure denominator clarity):
    - voiced_chunks_received: VAD=true frames into try_send (denominator)
    - voiced_chunks_enqueued: accepted into queue (no overflow)
    - dropped_audio_chunks: dropped by queue overflow (numerator)
    - drop_rate: dropped / received (used by backpressure levels)
    - tail_silence_chunks_sent: synthetic zero-PCM (excluded from drop_rate)
    """
    voiced_chunks_received: int = 0           # VAD=true frames into try_send
    voiced_chunks_enqueued: int = 0           # Accepted into queue
    dropped_audio_chunks: int = 0             # Dropped by queue overflow
    drop_rate: float = 0.0                    # dropped / received
    total_chunks_sent_to_provider: int = 0    # Audio chunks actually sent
    silence_chunks_skipped: int = 0
    tail_silence_chunks_sent: int = 0         # Synthetic zero-PCM (excluded from drop_rate)
    tail_injections_canceled: int = 0         # Before or during injection
    provider_reconnect_count: int = 0
    partial_latency_p50_ms: float = 0.0       # Enqueue time → partial receipt
    partial_latency_p95_ms: float = 0.0
    final_latency_p50_ms: float = 0.0         # Enqueue time → final receipt
    final_latency_p95_ms: float = 0.0
    total_billed_seconds: float = 0.0         # Estimated: chunks_sent * 30ms
    provider_audio_time_s: float = 0.0        # From sample counter
    utterance_count: int = 0
    word_count: int = 0
    provider_errors: int = 0
```

### 3.17 Deliverables Checklist

#### Core streaming
- [ ] `TranscriptionStream` with `DroppableAudioQueue` + background sender/receiver
- [ ] `DroppableAudioQueue`: deque + Event, audio-only drops, stale control coalescing
- [ ] `STTProviderClient` protocol + `DeepgramSTTClient` concrete implementation
- [ ] Version-pinned SDK dependency (`deepgram-sdk>=6.0,<7.0`) + method-existence test

#### VAD edge state + tail injection
- [ ] Explicit `_in_speech` state tracking (no tail on initial silence or reconnect)
- [ ] **Tail-silence injection** only on speech→silence edge (duration = `settings.deepgram_endpointing_ms`)
- [ ] Tail silence rounded up to full chunk boundary via `math.ceil`
- [ ] **Cancelable tail injection** via `_TailInjection(token=N)`:
  - [ ] Pre-start cancellation (token check on dequeue)
  - [ ] **Mid-injection cancellation** (token re-checked each chunk)
- [ ] **Real-time pacing** of tail injection (30ms/chunk, monotonic scheduling)
- [ ] **`_tail_pending` lifecycle**: cleared on completion, cancel, or mid-flight abort
- [ ] KeepAlive interval config-driven (`settings.transcription_keepalive_interval_seconds`)

#### Utterance assembly
- [ ] **`is_final` segment concatenation** → `speech_final` = FinalUtterance boundary
- [ ] `_receiver_loop` accumulates `is_final:true` segments, emits on `speech_final:true`
- [ ] Deepgram config: `endpointing=800` + `interim_results=true` (NOT `utterance_end_ms` for Tier 1)
- [ ] `CloseStream` on session end for final flush
- [ ] Fallback: `Finalize` message if endpointing doesn't fire within 2s of tail injection

#### Time alignment
- [ ] `SessionClock` with **provider-time-anchored pause segments** (not just wall-time offsets)
- [ ] `pause(role_key, provider_audio_time)` anchors pause to provider sample counter
- [ ] `provider_to_session_time()` only applies pauses where `provider_time >= pause_start`
- [ ] Late-arriving STT results (before pause boundary) are NOT shifted by that pause
- [ ] **Start paused** until first audio send (handles initial silence)
- [ ] `SessionClock.reset_pauses()` on provider reconnect
- [ ] **Connection offset** (`_provider_time_zero`) set on `start()` and `handle_reconnect()`
- [ ] `_samples_sent_to_provider` counter for provider_audio_time anchoring

#### IDs and lifecycle
- [ ] **Unique IDs**: `utterance_id = f"{role_key}:utt-{N}"` (no cross-track collisions)
- [ ] `role_key = f"{role.value}:{student_index}"` (multi-student safe)
- [ ] **Receiver task lifecycle** — stored, awaited on stop with 5s drain timeout
- [ ] Shutdown order: stop sentinel → sender CloseStream → receiver drain → WS close
- [ ] **Partial revision counter** managed locally (not from provider)
- [ ] All internal timing uses `time.monotonic()` (no wall-clock jumps)
- [ ] Reconnect handler resets VAD state, connection offset, pause tracking

#### Data + storage
- [ ] `TranscriptBuffer` with rolling window
- [ ] `TranscriptStore` with tiered storage (Postgres compact + S3 full)
- [ ] Student-only transcription mode for pilot
- [ ] Sentiment gated behind language/model support (English-only, may be None)
- [ ] Data packet delivery to tutor frontend

#### Observability + resilience
- [ ] `TranscriptionStats` with precise denominators:
  - `voiced_chunks_received` (denominator), `voiced_chunks_enqueued`, `dropped_audio_chunks`
  - `drop_rate = dropped / received` (tail chunks excluded)
  - `tail_silence_chunks_sent`, `tail_injections_canceled`
  - `provider_audio_time_s` (from sample counter)
- [ ] **Backpressure levels** with feature degradation (L0-L4), not just metrics
- [ ] L2 threshold: `drop_rate > 0.5%` sustained over 30s
- [ ] L3: disable transcription entirely, fall back to rule-based coaching
- [ ] Deepgram `mip_opt_out=true` for privacy (verify pricing impact)

#### Testing (see §11.2 for full scenarios)
- [ ] Mock STT provider for unit tests
- [ ] **Test 1: initial silence 30s → first speech** (no tail, correct timestamps)
- [ ] **Test 2: VAD flicker** (1-2 silence frames → tail canceled before start, not split)
- [ ] **Test 3: queue backpressure** (audio dropped, tail preserved, ordering correct)
- [ ] **Test 4: reconnect** (timestamp reset, pause offset reset, correct mapping)
- [ ] **Test 5: tail pacing prevents drift** (3 utterances, <500ms total drift)
- [ ] **Test 6: mid-injection cancel** (speech during injection aborts it, not split)
- [ ] Test: `speech_final` fires correctly with tail-silence injection
- [ ] Test: transcript timestamps don't drift with long silence gaps
- [ ] Test: SDK version pinning (method existence check)
- [ ] Integration test with recorded audio fixtures

---

## 4. Tier 2 — Tone & Uncertainty Detection

**Goal:** Detect when the student sounds uncertain, confused, hesitant, or
disengaged — and quantify it as a signal for the coaching system  
**Estimated time:** 3–4 weeks  
**Dependencies:** Tier 1 (transcripts) for linguistic analysis; paralinguistic
analysis can start independently

### 4.1 Two Complementary Signals

Uncertainty detection works best as a **fusion** of two independent signals:

```
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│  PARALINGUISTIC (audio signal)   │   │  LINGUISTIC (text signal)        │
│                                  │   │                                  │
│  • Pitch (F0) rising at end      │   │  • Hedging: "I think", "maybe"   │
│  • High pitch variance           │   │  • Filler words: "um", "uh"      │
│  • Slower speech rate             │   │  • Tag questions: "...right?"    │
│  • Longer pauses mid-utterance    │   │  • Self-corrections: "wait, no"  │
│  • Lower volume / trailing off    │   │  • Short responses: "I guess"    │
│  • Creaky voice / vocal fry       │   │  • Question intonation on        │
│                                  │   │    declarative statements        │
│  Score: 0.0 - 1.0               │   │  Score: 0.0 - 1.0               │
│  (FEATURE, not final label)      │   │  (FEATURE, not final label)      │
└──────────────┬───────────────────┘   └──────────────┬───────────────────┘
               │                                      │
               └──────────────┬───────────────────────┘
                              │
                    ┌─────────▼──────────────┐
                    │  UncertaintyDetector    │
                    │                        │
                    │  Fusion: weighted       │
                    │  0.5 * para + 0.5 * ling│
                    │                        │
                    │  Per-speaker calibrated │
                    │  Persistence required   │
                    │  Topic from tutor Q's   │
                    └────────────────────────┘
```

**Key insight from review:** Both the paralinguistic and linguistic detector
outputs are **features**, not final labels. The fusion layer handles
calibration, persistence, and contextual gating.

### 4.2 Paralinguistic Analysis — Enhancing `prosody.py`

#### 4.2.1 New Fields in ProsodyResult

```python
@dataclass
class ProsodyResult:
    # Existing
    rms_energy: float
    rms_db: float
    zero_crossing_rate: float
    speech_rate_proxy: float
    
    # NEW — Pitch / F0
    pitch_hz: float              # Fundamental frequency estimate (0 if unvoiced)
    pitch_confidence: float      # How reliable the F0 estimate is (0-1)
    
    # NEW — Hesitation markers
    pause_ratio: float           # Fraction of chunk that is silence within speech
    trailing_energy: bool        # Energy drops at end (trailing off)
```

**Note:** Relative pitch (deviation from baseline) and rising/falling contour
are computed by `SpeakerBaseline`, not raw prosody. This keeps `prosody.py`
purely signal-level.

#### 4.2.2 Pitch Estimation

| Library | Method | Accuracy | Speed | GPU needed |
|---------|--------|----------|-------|------------|
| **`parselmouth` (Praat)** | Autocorrelation | High | ~2ms/chunk | No |
| `librosa.pyin` | Probabilistic YIN | High | ~5ms/chunk | No |
| `crepe` | Neural network | Very high | ~20ms/chunk | Recommended |
| Custom autocorrelation | Signal processing | Medium | ~0.1ms/chunk | No |

**Recommendation:** Start with `parselmouth`. Fast, accurate, widely used
in speech research, no GPU needed.

**Pitch is fragile in the wild.** Background noise, bad mics, and unvoiced
speech segments will tank raw pitch estimates. Mitigations:

```python
def estimate_pitch_robust(
    samples: np.ndarray,
    sample_rate: int = 16000,
) -> tuple[float, float]:
    """Estimate F0 with noise-robust safeguards.
    
    Returns (pitch_hz, confidence).
    
    Safeguards:
    1. Only compute on voiced segments (VAD-gated)
    2. Median filter across recent voiced windows (not single-frame)
    3. Ignore if confidence < 0.5
    4. Search range: 80-500 Hz (covers male and female speech)
    """
    ...
```

#### 4.2.3 Speaker Baseline — Bootstrapping Without Circularity

**Problem:** The original plan bootstrapped baselines from "confident segments,"
but detecting confidence requires a baseline — that's circular.

**Solution:** Use a robust, unconditional approach:

```python
class SpeakerBaseline:
    """Tracks a participant's vocal baseline for relative scoring.
    
    Bootstrapping strategy (avoids circularity):
    1. First 15-30s: collect ALL voiced pitch, speech-rate, energy samples
       (no confidence filtering — we don't have a baseline yet)
    2. Compute baseline as robust MEDIAN of collected samples
       (median is resistant to outliers from noise/filler)
    3. After warmup: update slowly via EMA (alpha=0.02) so the baseline
       adapts to mic position changes, energy drift, etc.
    4. Clamp deviations to ±2σ to prevent runaway on equipment changes
    
    All measurements are reported as deviations from this baseline.
    """
    
    WARMUP_SECONDS = 20.0
    EMA_ALPHA = 0.02            # Slow adaptation after warmup
    MAX_DEVIATION_SIGMA = 2.0   # Clamp extreme deviations
    
    def __init__(self):
        self._pitch_warmup: list[float] = []
        self._rate_warmup: list[float] = []
        self._energy_warmup: list[float] = []
        self._first_sample_at: float | None = None
        self._calibrated = False
        
        # Post-warmup EMA baselines
        self._pitch_baseline: float = 0.0
        self._rate_baseline: float = 0.0
        self._energy_baseline: float = 0.0
        self._pitch_std: float = 1.0
        self._rate_std: float = 1.0
    
    @property
    def calibrated(self) -> bool:
        return self._calibrated
    
    def update(self, pitch_hz: float, speech_rate: float, energy: float):
        """Add a voiced sample. Handles warmup and post-warmup EMA."""
        if pitch_hz <= 0:
            return  # Unvoiced — skip
        
        now = time.time()
        if self._first_sample_at is None:
            self._first_sample_at = now
        
        elapsed = now - self._first_sample_at
        
        if not self._calibrated:
            self._pitch_warmup.append(pitch_hz)
            self._rate_warmup.append(speech_rate)
            self._energy_warmup.append(energy)
            
            if elapsed >= self.WARMUP_SECONDS and len(self._pitch_warmup) >= 10:
                self._finalize_warmup()
        else:
            # Slow EMA update
            self._pitch_baseline += self.EMA_ALPHA * (pitch_hz - self._pitch_baseline)
            self._rate_baseline += self.EMA_ALPHA * (speech_rate - self._rate_baseline)
            self._energy_baseline += self.EMA_ALPHA * (energy - self._energy_baseline)
    
    def _finalize_warmup(self):
        """Compute baselines from warmup data using robust median."""
        self._pitch_baseline = float(np.median(self._pitch_warmup))
        self._rate_baseline = float(np.median(self._rate_warmup))
        self._energy_baseline = float(np.median(self._energy_warmup))
        self._pitch_std = max(1.0, float(np.std(self._pitch_warmup)))
        self._rate_std = max(0.01, float(np.std(self._rate_warmup)))
        self._calibrated = True
    
    def pitch_deviation(self, current_pitch: float) -> float:
        """Relative pitch deviation, clamped to ±MAX_DEVIATION_SIGMA.
        
        Returns 0.0 if not calibrated or pitch is unvoiced.
        Positive = higher than normal, Negative = lower than normal.
        """
        if not self._calibrated or current_pitch <= 0:
            return 0.0
        raw = (current_pitch - self._pitch_baseline) / self._pitch_std
        return max(-self.MAX_DEVIATION_SIGMA, min(self.MAX_DEVIATION_SIGMA, raw))
    
    def speech_rate_deviation(self, current_rate: float) -> float:
        """Relative speech rate deviation, clamped."""
        if not self._calibrated:
            return 0.0
        raw = (current_rate - self._rate_baseline) / self._rate_std
        return max(-self.MAX_DEVIATION_SIGMA, min(self.MAX_DEVIATION_SIGMA, raw))
```

### 4.3 Linguistic Uncertainty Detection — Per-Speaker Calibration

**Problem from review:** Hedging/filler heuristics will overfire on normal
speech patterns. "Like" and "you know" vary by personality and culture.

**Solution:** The linguistic detector's raw output is a **feature**, not a
label. Per-speaker calibration normalizes against their own baseline filler
density, and persistence is required before surfacing a signal.

```python
class LinguisticUncertaintyDetector:
    """Detect uncertainty signals in transcribed text.
    
    Raw scores are FEATURES, not labels. The UncertaintyDetector fusion
    layer handles:
    - Per-speaker calibration (compare against their own filler baseline)
    - Persistence requirement (score > threshold for 2-3 utterances in 30-60s)
    - Contextual gating (uncertainty during problem-solving ≠ uncertainty
      during casual conversation)
    """
    
    # Hedging phrases (weighted by strength)
    HEDGING_PHRASES = {
        "i think": 0.4,
        "i guess": 0.5,
        "maybe": 0.5,
        "probably": 0.3,
        "i'm not sure": 0.7,
        "i don't know": 0.8,
        "sort of": 0.4,
        "kind of": 0.4,
        "possibly": 0.4,
        "it might be": 0.5,
        "i believe": 0.3,
        "is it": 0.5,
        "right?": 0.5,
        "isn't it": 0.4,
        "wait": 0.6,
        "actually no": 0.7,
        "never mind": 0.6,
        "let me think": 0.3,
    }
    
    # Fillers — scored by density relative to speaker's own baseline
    FILLER_WORDS = {"um", "uh", "er", "ah", "hmm"}
    # "like" and "you know" excluded from fillers — too personality-dependent.
    # They are only counted in _detect_hedging() where the phrase context matters.
    
    def __init__(self):
        self._speaker_filler_baselines: dict[str, deque[float]] = {}
    
    def analyze(self, text: str, role: str = "student") -> LinguisticUncertaintyResult:
        """Analyze a single utterance for uncertainty FEATURES.
        
        Returns raw feature scores — NOT a final uncertainty label.
        """
        hedging_score = self._detect_hedging(text)
        filler_density = self._count_filler_density(text)
        relative_filler = self._relative_filler_density(role, filler_density)
        question_in_statement = self._detect_question_intonation(text)
        self_correction = self._detect_self_correction(text)
        response_brevity = self._score_brevity(text)
        
        # Raw weighted fusion — this is a FEATURE SCORE, not a final label
        raw_score = (
            0.30 * hedging_score +
            0.20 * relative_filler +     # Relative to speaker's own baseline
            0.20 * question_in_statement +
            0.15 * self_correction +
            0.15 * response_brevity
        )
        
        return LinguisticUncertaintyResult(
            raw_score=min(1.0, raw_score),
            hedging_score=hedging_score,
            filler_density=filler_density,
            relative_filler_density=relative_filler,
            question_in_statement=question_in_statement,
            self_correction=self_correction,
            response_brevity=response_brevity,
            detected_hedges=[...],
        )
    
    def _relative_filler_density(self, role: str, current_density: float) -> float:
        """Compare current filler density against speaker's own baseline.
        
        Returns 0.0 if this density is normal for this speaker,
        up to 1.0 if it's significantly above their baseline.
        """
        if role not in self._speaker_filler_baselines:
            self._speaker_filler_baselines[role] = deque(maxlen=50)
        
        baseline_history = self._speaker_filler_baselines[role]
        baseline_history.append(current_density)
        
        if len(baseline_history) < 5:
            return current_density  # Not enough data, use raw
        
        baseline = float(np.median(list(baseline_history)))
        if baseline < 0.01:
            return current_density
        
        excess = max(0.0, current_density - baseline) / max(0.01, baseline)
        return min(1.0, excess)
```

### 4.4 Uncertainty Fusion — Per-Student, Persistence-Gated

```python
class UncertaintyDetector:
    """Fuses paralinguistic and linguistic uncertainty signals.
    
    Key design decisions from architecture review:
    1. Per-student instances (not global) for multi-student sessions
    2. Both signal types are FEATURES — fusion handles calibration
    3. Persistence required: score > threshold for 2-3 utterances
       within 30-60 seconds before surfacing to coaching/UI
    4. Topic association uses tutor questions (they carry topic intent)
       + curated subject vocabulary, not TF-IDF on tiny windows
    """
    
    # Persistence: uncertainty must be sustained before we report it
    PERSISTENCE_UTTERANCES = 2        # Need N uncertain utterances
    PERSISTENCE_WINDOW_SECONDS = 45.0 # Within this time window
    UNCERTAINTY_THRESHOLD = 0.5       # Raw fusion score threshold
    
    def __init__(self, student_index: int = 0):
        self._student_index = student_index
        self._paralinguistic = ParalinguisticAnalyzer()
        self._linguistic = LinguisticUncertaintyDetector()
        self._speaker_baseline = SpeakerBaseline()
        
        # Persistence tracking
        self._recent_scores: deque[tuple[float, float]] = deque(maxlen=20)  # (timestamp, score)
        
        # Topic tracking
        self._current_topic: str = ""
        self._topic_extractor = TutorQuestionTopicExtractor()
    
    def update_audio(self, prosody: ProsodyResult, timestamp: float):
        """Update paralinguistic signals from audio processing."""
        if prosody.pitch_hz > 0 and prosody.pitch_confidence >= 0.5:
            self._speaker_baseline.update(
                prosody.pitch_hz,
                prosody.speech_rate_proxy,
                prosody.rms_energy,
            )
    
    def update_transcript(
        self,
        utterance: FinalUtterance,
        recent_tutor_utterances: list[FinalUtterance],
    ) -> UncertaintySignal | None:
        """Update from a new student utterance.
        
        Returns an UncertaintySignal only if:
        1. Raw fusion score exceeds threshold
        2. Persistence requirement met (sustained uncertainty)
        """
        # Linguistic features
        ling_result = self._linguistic.analyze(utterance.text, utterance.role)
        
        # Paralinguistic features (from most recent audio around this utterance)
        para_score = self._paralinguistic.current_score
        
        # Fusion
        fusion_score = 0.5 * para_score + 0.5 * ling_result.raw_score
        
        # Record for persistence tracking
        self._recent_scores.append((utterance.end_time, fusion_score))
        
        # Update topic from tutor questions
        self._topic_extractor.update(recent_tutor_utterances)
        self._current_topic = self._topic_extractor.current_topic
        
        # Check persistence: need N scores > threshold within the window
        if not self._persistence_met(utterance.end_time):
            return None
        
        return UncertaintySignal(
            score=fusion_score,
            paralinguistic_score=para_score,
            linguistic_score=ling_result.raw_score,
            topic=self._current_topic,
            trigger_text=utterance.text,
            trigger_hedges=ling_result.detected_hedges,
            confidence=self._compute_confidence(fusion_score, ling_result),
        )
    
    def _persistence_met(self, current_time: float) -> bool:
        """Check if uncertainty has been sustained (not a one-off spike)."""
        window_start = current_time - self.PERSISTENCE_WINDOW_SECONDS
        recent_high = [
            score for ts, score in self._recent_scores
            if ts >= window_start and score >= self.UNCERTAINTY_THRESHOLD
        ]
        return len(recent_high) >= self.PERSISTENCE_UTTERANCES
    
    @property
    def current_uncertainty_score(self) -> float:
        """Smoothed uncertainty score (0-1) for the student."""
        if not self._recent_scores:
            return 0.0
        # Exponentially-weighted recent mean
        scores = [s for _, s in self._recent_scores]
        if len(scores) <= 2:
            return scores[-1]
        weights = np.exp(np.linspace(-1, 0, len(scores)))
        return float(np.average(scores, weights=weights))
    
    @property
    def uncertainty_topic(self) -> str:
        return self._current_topic
```

### 4.5 Topic Association — Tutor Questions as Source of Truth

TF-IDF on tiny transcript windows is noisy. Better approach:

```python
class TutorQuestionTopicExtractor:
    """Extract current topic from tutor questions.
    
    Tutor utterances (especially questions) carry topic intent.
    Combine with a curated subject-vocabulary list for math/science.
    Upgrade to embeddings or post-session LLM extraction later.
    """
    
    # Curated vocabulary hints — expand per subject area
    SUBJECT_VOCABULARY = {
        "math": {"derivative", "integral", "function", "equation", "slope",
                 "limit", "variable", "coefficient", "polynomial", "quadratic",
                 "factor", "exponent", "logarithm", "trigonometry", "sine",
                 "cosine", "tangent", "theorem", "proof", "graph"},
        "science": {"hypothesis", "experiment", "molecule", "atom", "cell",
                    "energy", "force", "velocity", "acceleration", "reaction",
                    "element", "compound", "evolution", "photosynthesis"},
        # Add more subject areas as needed
    }
    
    def __init__(self):
        self._recent_tutor_questions: deque[str] = deque(maxlen=10)
        self._current_topic = ""
    
    def update(self, tutor_utterances: list[FinalUtterance]):
        """Extract topic from recent tutor utterances."""
        for u in tutor_utterances:
            if self._is_question(u.text):
                self._recent_tutor_questions.append(u.text)
        
        # Find subject keywords in recent tutor questions
        all_text = " ".join(self._recent_tutor_questions).lower()
        found_keywords = []
        for subject, vocab in self.SUBJECT_VOCABULARY.items():
            matches = [w for w in vocab if w in all_text]
            if matches:
                found_keywords.extend(matches)
        
        self._current_topic = ", ".join(found_keywords[-3:]) if found_keywords else ""
    
    def _is_question(self, text: str) -> bool:
        """Heuristic: ends with '?' or starts with question words."""
        text = text.strip()
        if text.endswith("?"):
            return True
        lower = text.lower()
        return any(lower.startswith(w) for w in
                   ["what", "why", "how", "can you", "could you", "do you",
                    "does", "is ", "are ", "would", "explain", "tell me"])
    
    @property
    def current_topic(self) -> str:
        return self._current_topic
```

### 4.6 Optional: Pre-trained Emotion Model

| Option | What it gives you | Integration | Cost |
|--------|-------------------|-------------|------|
| **Hume AI Streaming** | 48 emotion dimensions (confusion, doubt, interest) | WebSocket API | ~$0.005/min |
| **SpeechBrain** | 4-7 emotion classes | Self-hosted Python | Free (compute) |

**Recommendation:** Start with pitch heuristics + linguistic analysis. They're
fast, cheap, and good enough. Add Hume AI later as another parallel stream
if richer emotional granularity is needed.

### 4.7 New Files

```
backend/app/
  uncertainty/
    __init__.py
    detector.py           # UncertaintyDetector — fusion, persistence, per-student
    paralinguistic.py     # Pitch analysis, SpeakerBaseline
    linguistic.py         # Text-based detection with per-speaker filler calibration
    models.py             # UncertaintySignal, LinguisticUncertaintyResult
    topic_extractor.py    # TutorQuestionTopicExtractor with subject vocabulary
    
  audio_processor/
    prosody.py            # MODIFIED — add pitch_hz, pitch_confidence, pause_ratio
```

### 4.8 Deliverables Checklist

- [ ] Pitch (F0) estimation via `parselmouth` with noise-robust safeguards
- [ ] `SpeakerBaseline` with unconditional median warmup (no circular confidence)
- [ ] `SpeakerBaseline` slow EMA post-warmup + deviation clamping
- [ ] `LinguisticUncertaintyDetector` with per-speaker filler calibration
- [ ] Excluded personality-dependent fillers ("like", "you know") from filler detection
- [ ] `UncertaintyDetector` fusion with persistence gating (2+ utterances in 45s)
- [ ] Per-student uncertainty instances for multi-student sessions
- [ ] `TutorQuestionTopicExtractor` with subject vocabulary
- [ ] Integration into `process_audio_chunk()` for paralinguistic signals
- [ ] Integration into transcript callback for linguistic signals
- [ ] `UncertaintySignal` added to `MetricsSnapshot`
- [ ] Unit tests with curated uncertain/confident text pairs
- [ ] False positive suppression tests (high-filler but confident speakers)
- [ ] Eval fixtures: monotone prosody, noisy environments, personality fillers

---

## 5. Tier 3 — AI Coaching Copilot

**Goal:** An LLM that follows the conversation and generates contextual,
topic-aware coaching suggestions — including specific things the tutor could say  
**Estimated time:** 3–4 weeks  
**Dependencies:** Tier 1 (transcripts), Tier 2 (uncertainty signals)

### 5.1 Design Principles

1. **Precision > recall** — "no suggestion" is the most common correct answer
2. **Non-intrusive** — supplements rule-based nudges, doesn't replace them
3. **Pedagogy only** — suggest *teaching moves*, never provide "the answer"
4. **Cooldowns respected** — flows through existing `Coach` pipeline
5. **Tutor-only** — never shown to the student
6. **Latency-tolerant** — runs on a slower loop, not on every frame
7. **Graceful degradation** — LLM failure = rule-based coaching continues
8. **Cost-bounded** — hard per-session budget, prompt caching, event-triggered

### 5.2 LLM Selection

| Model | Latency | Cost/1M tokens (in/out) | Context | Notes |
|-------|---------|------------------------|---------|-------|
| **Claude 3.5 Haiku** | ~400ms | ~$0.25 / $1.25 | 200K | **Primary** — fast, cheap, great structured output |
| **GPT-4o-mini** | ~500ms | $0.15 / $0.60 | 128K | Strong alternative |
| **Gemini 2.0 Flash** | ~300ms | $0.075 / $0.30 | 1M | Cheapest, very fast |

**Note:** Verify exact pricing tiers at implementation time. Use prompt
caching where available (80-95% of the prompt repeats across calls).

### 5.3 Call Volume & Cost Control

**Revised from architecture review:** The original estimate of "~4 calls/min"
(every 15s) underestimates cost because the rolling transcript repeats heavily
across calls. New strategy:

```
Call frequency strategy:
├─ Baseline: every 30-45 seconds (NOT every 15s)
├─ Burst mode: every 10-15 seconds ONLY WHEN:
│   ├─ Student uncertainty score > 0.7
│   ├─ A rule-based nudge just fired (AI can enhance with context)
│   └─ Engagement trend is "declining"
├─ Hard budget: max 60 calls/hour per session
├─ Prompt caching: ~80-95% of tokens are identical across calls
└─ Intensity setting: tutor can adjust (subtle → fewer, aggressive → more)
```

**Revised cost estimate (60-minute session):**
- Baseline: ~80 calls × ~600 tokens = ~48K tokens → ~$0.02 (Haiku)
- Burst: ~20 calls × ~800 tokens = ~16K tokens → ~$0.01
- **Total LLM cost: ~$0.03/session** (much lower than original estimate)

### 5.4 AICoachingCopilot Design

```python
class AICoachingCopilot:
    """LLM-powered coaching that follows the conversation.
    
    Design constraints from architecture review:
    1. Event-triggered + low-frequency baseline (NOT every 15s)
    2. Hard per-session call budget
    3. Prompt caching for token efficiency
    4. Pedagogy-only constraint (teaching moves, never answers)
    5. PII scrubbing before sending transcript to LLM
    6. Suggestion dedupe via normalized text hash + per-topic cooldown
    """
    
    BASELINE_INTERVAL_SECONDS = 35.0     # Default call frequency
    BURST_INTERVAL_SECONDS = 12.0        # When triggered by uncertainty/nudge
    MAX_CALLS_PER_HOUR = 60              # Hard budget
    MIN_TRANSCRIPT_WORDS = 20            # Don't call with too little context
    SUGGESTION_TOPIC_COOLDOWN_SECONDS = 300.0  # Same topic at most every 5 min
    
    def __init__(
        self,
        session_id: str,
        session_type: str,
        transcript_buffer: TranscriptBuffer,
        uncertainty_detector: UncertaintyDetector,
        llm_provider: str = "claude",
    ):
        self._session_id = session_id
        self._session_type = session_type
        self._transcript_buffer = transcript_buffer
        self._uncertainty_detector = uncertainty_detector
        self._last_eval_at: float = 0.0
        self._call_count: int = 0
        self._session_start: float = time.time()
        self._suggestion_history: list[AISuggestion] = []
        self._topic_last_suggested_at: dict[str, float] = {}
        self._pii_scrubber = PIIScrubber()
    
    async def maybe_evaluate(
        self,
        snapshot: MetricsSnapshot,
        elapsed_seconds: float,
        rule_nudge_just_fired: bool = False,
        now: float | None = None,
    ) -> AISuggestion | None:
        """Check if an LLM evaluation should run.
        
        Trigger conditions:
        1. Baseline interval elapsed AND new transcript content
        2. Burst mode: uncertainty high OR rule-based nudge just fired
        3. Budget not exhausted
        4. Enough transcript context available
        """
        now = now or time.time()
        
        # Budget check
        elapsed_hours = (now - self._session_start) / 3600
        if elapsed_hours > 0 and self._call_count / elapsed_hours >= self.MAX_CALLS_PER_HOUR:
            return None
        
        # Determine interval based on state
        interval = self._current_interval(snapshot, rule_nudge_just_fired)
        if now - self._last_eval_at < interval:
            return None
        
        # Enough context?
        word_count = sum(self._transcript_buffer.word_count_by_role(seconds=90).values())
        if word_count < self.MIN_TRANSCRIPT_WORDS:
            return None
        
        # Build context with PII scrubbing
        context = self._build_context(snapshot, elapsed_seconds)
        context.recent_transcript = self._pii_scrubber.scrub(context.recent_transcript)
        
        # Call LLM
        suggestion = await self._call_llm(context)
        
        self._last_eval_at = now
        self._call_count += 1
        
        if suggestion is not None:
            # Dedupe: check if we already suggested something similar on this topic
            if self._is_duplicate(suggestion, now):
                return None
            
            self._suggestion_history.append(suggestion)
            self._topic_last_suggested_at[suggestion.topic] = now
        
        return suggestion
    
    def _current_interval(
        self,
        snapshot: MetricsSnapshot,
        rule_nudge_just_fired: bool,
    ) -> float:
        """Determine current call interval — baseline or burst mode."""
        # Burst mode triggers
        if rule_nudge_just_fired:
            return self.BURST_INTERVAL_SECONDS
        if self._uncertainty_detector.current_uncertainty_score > 0.7:
            return self.BURST_INTERVAL_SECONDS
        if snapshot.session.engagement_trend == "declining":
            return self.BURST_INTERVAL_SECONDS
        return self.BASELINE_INTERVAL_SECONDS
    
    def _is_duplicate(self, suggestion: AISuggestion, now: float) -> bool:
        """Check if this suggestion is too similar to a recent one.
        
        Uses:
        1. Per-topic cooldown (same topic within 5 minutes)
        2. Normalized text hash for near-exact matches
        """
        # Topic cooldown
        if suggestion.topic in self._topic_last_suggested_at:
            last = self._topic_last_suggested_at[suggestion.topic]
            if now - last < self.SUGGESTION_TOPIC_COOLDOWN_SECONDS:
                return True
        
        # Text similarity (simple normalized hash — upgrade to embeddings later)
        normalized = suggestion.suggestion.lower().strip()
        for prev in self._suggestion_history[-5:]:
            prev_normalized = prev.suggestion.lower().strip()
            if normalized == prev_normalized:
                return True
            # TODO: Add embedding similarity threshold for "close enough"
        
        return False
```

### 5.5 LLM Prompt Design — Pedagogy-Only Constraint

**Critical addition from review:** The prompt must explicitly prohibit the AI
from providing "the answer" to academic questions. It should only suggest
*teaching moves* (check understanding, ask for reasoning, propose scaffolds).
This dramatically reduces hallucination impact because the AI never asserts
domain facts.

```python
SYSTEM_PROMPT = """You are a real-time tutoring coach assistant. You observe a live
tutoring session and provide private coaching suggestions to the tutor ONLY when
they would meaningfully improve the session.

Session type: {session_type}
{session_type_guidance}

CRITICAL CONSTRAINTS:
1. NEVER provide "the answer" to the academic content being discussed.
   You suggest TEACHING MOVES only: check for understanding, ask for reasoning,
   propose scaffolding steps, suggest analogies, recommend practice problems.
2. Only suggest when there is a clear, actionable opportunity. "Everything is
   fine" is the most common correct answer — return null.
3. Never repeat a suggestion you've already given in this session.
4. Keep suggestions under 2 sentences. The tutor is busy teaching.
5. When suggesting what to say, frame it as a natural conversation move,
   not a script. The tutor should adapt it to their style.
6. Focus on the STUDENT's learning experience, not abstract metrics.
7. You are a pedagogy coach, not a subject matter expert. If you're unsure
   about the academic content, focus on process suggestions instead.

You will receive:
- Recent transcript (last ~90 seconds, PII-scrubbed)
- Student uncertainty score (0-1, from audio + text analysis)
- Session metrics (talk balance, engagement, attention)

Respond with a JSON object or null:
{{
  "action": "suggest" | "alert",
  "topic": "the specific topic/concept being discussed",
  "observation": "1-sentence observation about what you noticed",
  "suggestion": "What the tutor could do (teaching move, not content answer)",
  "suggested_prompt": "A natural question/statement the tutor could use" | null,
  "priority": "low" | "medium" | "high",
  "confidence": 0.0 - 1.0
}}

Return null when no action is needed. This is expected to be the most common response."""

SESSION_TYPE_GUIDANCE = {
    "general": "Balance between tutor explanation and student practice. Flag if one side dominates too long.",
    "lecture": "Tutor-heavy is expected. Only suggest check-ins if the student shows clear disengagement or confusion.",
    "practice": "Student should be doing most of the work. Suggest scaffolding if stuck, backing off if tutor is solving for them.",
    "socratic": "Tutor should be asking questions, not explaining. Flag if tutor shifts to lecture mode or gives away answers.",
    "discussion": "Both participants should contribute roughly equally. Flag one-sided conversations.",
}
```

### 5.6 PII Scrubbing Before LLM

Transcripts may contain names, emails, phone numbers. Scrub before sending
to the LLM and before persisting to storage.

**Scope of the claim:** This scrubber catches **obvious structured PII patterns**
(emails, phone numbers, SSNs, street addresses). It will **NOT reliably remove**
names, locations, or other contextual PII that requires NER. Any documentation
or consent language should scope the claim to "structured PII patterns" and not
promise comprehensive PII removal.

**Upgrade path for stronger redaction:**
1. Add a lightweight NER model (e.g., spaCy `en_core_web_sm`) for name/location
   detection — runs locally, ~5ms per utterance
2. Use Deepgram's built-in redaction add-on for STT-level PII removal (paid
   feature, removes PII before text ever reaches our backend)
3. For stored transcripts specifically, apply both regex + NER at persist time

```python
class PIIScrubber:
    """Lightweight PII redaction for obvious structured patterns.
    
    Catches: emails, phone numbers, SSNs, street addresses.
    Does NOT catch: names, locations, or contextual PII.
    
    This is Layer 1 of a multi-layer strategy:
    - Layer 1: Regex patterns (this class) — cheap, fast, always-on
    - Layer 2 (future): NER-based name/location detection
    - Layer 3 (future): Provider-level redaction (Deepgram add-on)
    """
    
    PATTERNS = [
        (r'\b[\w.+-]+@[\w-]+\.[\w.]+\b', '[EMAIL]'),           # Emails
        (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]'),         # US phone numbers
        (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),                   # SSN
        (r'\b\d{1,5}\s\w+\s(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd)\b', '[ADDRESS]'),
    ]
    
    def scrub(self, text: str) -> str:
        """Redact obvious structured PII patterns from text.
        
        Does NOT guarantee removal of names or contextual PII.
        See class docstring for upgrade path.
        """
        for pattern, replacement in self.PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text
```

### 5.7 AI Output Validation — Code-Level Guardrail

The pedagogy-only constraint in the system prompt (§5.5) is necessary but not
sufficient. LLMs can ignore instructions. Add a **code-level validator** that
rejects suggestions containing declarative content answers, even if the model
produces them:

```python
class AIOutputValidator:
    """Reject AI suggestions that violate the pedagogy-only constraint.
    
    This is a hard code-level guardrail, not a prompt suggestion.
    If the model outputs a domain answer despite instructions, we
    discard it and return null rather than passing it to the tutor.
    
    Pattern design principles:
    - Only reject DECLARATIVE answer statements ("the answer is X")
    - Do NOT reject questions that reference content ("What do you think
      the derivative is?") — those are valid teaching moves
    - suggested_prompt is held to a stricter standard: reject if it
      contains `=` with operands (likely a solved expression)
    - When in doubt, let the suggestion through — false rejection is
      worse than a borderline suggestion reaching the tutor
    """
    
    # Declarative answer patterns — reject in BOTH suggestion and prompt
    ANSWER_PATTERNS = [
        r'\bthe answer is\b',
        r'\bthe solution is\b',
        r'\bthe result is\b',
        r'\bthe correct answer\b',
        r'\bit equals\b',
        r'\byou should tell (?:them|the student) (?:that |it.s )',
    ]
    
    # Stricter patterns — reject only in suggested_prompt (not observation)
    # These catch "give them the answer" phrasing that would be fine in
    # an observation ("the derivative is hard for them") but not in a
    # prompt the tutor would read aloud.
    PROMPT_ONLY_PATTERNS = [
        # Expression-like: "= <number>" or "= <number> <operator>"
        # Catches "x = 5", "it = 2x + 3", but NOT "x = ?" (question form)
        r'=\s*-?\d+[\d\s+\-*/^().]*(?<!\?)\s*$',
        # "Tell them [that] <fact>"
        r'\btell (?:them|the student|him|her) (?:that |it.s |the )',
    ]
    
    def validate(self, suggestion: AISuggestion) -> AISuggestion | None:
        """Return the suggestion if it passes validation, or None if rejected.
        
        Checks:
        1. ANSWER_PATTERNS against both suggestion text and suggested_prompt
        2. PROMPT_ONLY_PATTERNS against suggested_prompt only
        """
        # Check suggestion text (observation + suggestion)
        for text in [suggestion.suggestion, suggestion.observation]:
            if self._matches_answer_patterns(text):
                self._log_rejection("answer_pattern", text)
                return None
        
        # Check suggested_prompt with stricter rules
        if suggestion.suggested_prompt:
            if self._matches_answer_patterns(suggestion.suggested_prompt):
                self._log_rejection("answer_pattern_in_prompt", suggestion.suggested_prompt)
                return None
            if self._matches_prompt_patterns(suggestion.suggested_prompt):
                self._log_rejection("prompt_only_pattern", suggestion.suggested_prompt)
                return None
        
        return suggestion
    
    def _matches_answer_patterns(self, text: str) -> bool:
        lower = text.lower()
        return any(re.search(p, lower) for p in self.ANSWER_PATTERNS)
    
    def _matches_prompt_patterns(self, text: str) -> bool:
        return any(re.search(p, text) for p in self.PROMPT_ONLY_PATTERNS)
    
    def _log_rejection(self, reason: str, text: str):
        logger.warning(
            "AI suggestion rejected by output validator (%s): %s",
            reason, text[:120],
        )
```

**Integration:** The validator runs **after** LLM parsing and **before** the
suggestion enters the coaching pipeline. If rejected, `maybe_evaluate()` returns
`None` and the call is counted against the budget (so a misbehaving model
doesn't cause infinite retries).

### 5.8 Integration into Existing Coach Pipeline

AI suggestions flow through the existing coaching system:

```python
# In session_runtime.py emit_metrics_snapshot(), after rule-based coaching:

if allow_coaching and ai_copilot is not None:
    ai_suggestion = await ai_copilot.maybe_evaluate(
        snapshot,
        room.elapsed_seconds(),
        rule_nudge_just_fired=bool(evaluation.emitted_nudge_type),
    )
    
    if ai_suggestion is not None:
        # Code-level validation: reject domain answers
        ai_suggestion = output_validator.validate(ai_suggestion)
    
    if ai_suggestion is not None:
        ai_nudge = Nudge(
            nudge_type="ai_coaching_suggestion",
            message=ai_suggestion.observation,
            priority=NudgePriority(ai_suggestion.priority),
            trigger_metrics={
                "ai_topic": ai_suggestion.topic,
                "ai_suggestion": ai_suggestion.suggestion,
                "ai_suggested_prompt": ai_suggestion.suggested_prompt,
                "ai_confidence": ai_suggestion.confidence,
                "uncertainty_score": uncertainty_detector.current_uncertainty_score,
                "source": "ai_copilot",
            },
        )
        # Flows through same budget/cooldown system
        room.nudges_sent.append(ai_nudge)
        nudges_to_send.append(ai_nudge)
```

### 5.8 "Suggest What to Say" Button (On-Demand)

```python
@router.post("/api/sessions/{session_id}/suggest")
async def request_suggestion(
    session_id: str,
    token: str = Query(...),
):
    """Tutor-initiated request for an immediate AI coaching suggestion.
    
    Uses the same copilot but with a focused prompt addition:
    "The tutor is explicitly asking for help right now."
    Bypasses the interval check but still respects the per-session budget.
    """
    ...
```

### 5.9 Tutor Feedback for Eval Dataset

**From review:** Add a simple feedback mechanism to build an eval dataset:

```python
@router.post("/api/sessions/{session_id}/suggestion-feedback")
async def suggestion_feedback(
    session_id: str,
    body: SuggestionFeedback,
    token: str = Query(...),
):
    """Record tutor feedback on an AI suggestion.
    
    Stored with the suggestion context for eval dataset construction.
    """
    # body: { suggestion_id: str, helpful: bool, comment: str | None }
    ...
```

This creates a labeled dataset over time: suggestion + context + was it helpful.

### 5.10 New Files

```
backend/app/
  ai_coaching/
    __init__.py
    copilot.py            # AICoachingCopilot with event-triggered + budget
    context.py            # AICoachingContext, AISuggestion data models
    prompts.py            # System prompts with pedagogy-only constraint
    llm_client.py         # Async LLM client (Claude/GPT) with prompt caching
    pii_scrubber.py       # Regex PII redaction (structured patterns only, scoped claim)
    output_validator.py   # Code-level guardrail: reject domain answers from LLM
    on_demand.py          # Manual /suggest endpoint
    feedback.py           # Tutor feedback collection for eval
```

### 5.11 Deliverables Checklist

- [ ] `AICoachingCopilot` with event-triggered + baseline intervals
- [ ] Hard per-session budget (max 60 calls/hour)
- [ ] Prompt caching support (provider-dependent)
- [ ] **Pedagogy-only constraint** in system prompt (no domain answers)
- [ ] **`AIOutputValidator`** — code-level rejection of domain answers (regex, not just prompt)
- [ ] Validator rejects: "the answer is", "it equals", "solve by", "= {number}", etc.
- [ ] Rejected suggestions counted against budget (no infinite retries)
- [ ] `PIIScrubber` — regex PII redaction (scoped to structured patterns: email/phone/SSN)
- [ ] PII claim scoped in docs/consent: "obvious structured patterns" not "all PII"
- [ ] Suggestion dedupe: normalized hash + per-topic cooldown (5 min)
- [ ] Integration into `emit_metrics_snapshot()` coaching flow
- [ ] Respects existing cooldowns, budget, and intensity settings
- [ ] On-demand `/suggest` endpoint
- [ ] `/suggestion-feedback` endpoint for tutor 👍/👎
- [ ] Trace recording of all AI suggestions + context for eval
- [ ] LLM client abstraction (Claude / GPT / Gemini switchable)
- [ ] Mock LLM provider for testing
- [ ] Eval fixtures: should-suggest vs should-not scenarios
- [ ] Eval fixtures: domain-answer-in-output rejection

---

## 6. Tier 4 — Frontend UX

**Goal:** Surface transcripts, uncertainty indicators, AI suggestions, and
the "suggest what to say" button in the tutor's session UI  
**Estimated time:** 2–3 weeks  
**Dependencies:** Tier 1 (transcripts), Tier 3 (AI suggestions)

### 6.1 Live Transcript Panel

A collapsible sidebar/panel showing the rolling conversation with speaker labels:

```
┌─────────────────────────────────────────┐
│ 📝 Live Transcript              [Hide] │
│                                         │
│ 12:03 [Tutor]                           │
│ So try taking the derivative of x²+3x. │
│                                         │
│ 12:15 [Student]  🔶 uncertain          │
│ Um... okay so... I think... is it 2x    │
│ plus... 3? Or wait...                   │
│                                         │
│ 12:22 [Tutor]                           │
│ That's right! 2x + 3. Good job.        │
│                                         │
│ 12:28 [Tutor]                           │
│ Now try the integral of 2x.            │
│                                         │
│ ▌ typing...                             │
└─────────────────────────────────────────┘
```

**Key design decisions:**
- **Stable utterance IDs** — partials update existing lines via `utterance_id` + `revision`
- **Auto-scroll** with "scroll to bottom" button when user scrolls up
- **Compact by default** — tutor can expand/collapse
- **Uncertainty badges** appear inline next to uncertain student utterances
- **Tutor-only** — never shown to students
- The panel handles partial → final transitions without flicker

#### Components

```
frontend/src/
  components/
    transcript/
      TranscriptPanel.tsx        # Collapsible panel with auto-scroll
      TranscriptMessage.tsx      # Single utterance with speaker label + time
      UncertaintyBadge.tsx       # 🔶 indicator on uncertain utterances
      PartialTranscript.tsx      # Live "typing..." indicator (updates in-place)
```

### 6.2 Uncertainty Indicator on Student Video

A small, persistent indicator near the student's video tile:

```tsx
function UncertaintyIndicator({ 
  score, 
  topic 
}: { 
  score: number
  topic: string | null 
}) {
  // Only show when persistence threshold met (backend handles this)
  if (score < 0.6) return null
  
  return (
    <div className={`
      absolute bottom-12 left-3 
      rounded-full border px-3 py-1 
      text-xs font-medium
      transition-all duration-500
      ${score > 0.8 
        ? 'border-amber-400/40 bg-amber-500/10 text-amber-100' 
        : 'border-yellow-400/30 bg-yellow-500/10 text-yellow-100'}
    `}>
      🔶 Seems uncertain{topic ? ` about ${topic}` : ''}
    </div>
  )
}
```

Properties:
- Fades in/out with CSS transition (not jarring)
- Minimum display duration (3s) to prevent flash
- Same pill/badge styling as existing attention state indicators
- Topic label when available

### 6.3 AI Coaching Suggestion Card

When the AI copilot generates a suggestion, it appears as a special nudge card:

```
┌─────────────────────────────────────────────────┐
│ 🤖 AI Coaching Insight                     [✕] │
│                                                 │
│ The student got the derivative right but with    │
│ hesitation. They may not understand the          │
│ underlying pattern yet.                         │
│                                                 │
│ 💡 Suggestion:                                   │
│ Before moving to integrals, check understanding. │
│                                                 │
│ ┌─────────────────────────────────────────────┐ │
│ │ 💬 "Can you explain in your own words why   │ │
│ │    the derivative of x² is 2x?"             │ │
│ │                              [Copy] [Use]   │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ Was this helpful?  👍  👎                        │
│ Confidence: ████████░░ 82%                      │
└─────────────────────────────────────────────────┘
```

Features:
- **"Copy"** — copies suggested prompt to clipboard
- **👍 / 👎** — sends feedback to `/suggestion-feedback` endpoint
- **Confidence bar** — shows AI confidence
- **Distinct styling** — clearly marked as AI-generated (🤖, violet border)
- **Dismissible** — same dismiss pattern as existing nudges
- Plays the nudge chime (configurable)

### 6.4 "Get Suggestion" Button

Persistent button in tutor's control bar:

```tsx
<button
  onClick={requestSuggestion}
  disabled={suggestionLoading}
  className="rounded-full border border-violet-400/40 bg-violet-500/10 
             px-4 py-2 text-sm text-violet-100 
             hover:bg-violet-500/20 transition-all"
>
  {suggestionLoading ? '⏳ Thinking...' : '💡 Get suggestion'}
</button>
```

### 6.5 New Types & Hooks

```typescript
// types.ts additions
export interface TranscriptMessage {
  utterance_id: string
  revision: number
  role: 'tutor' | 'student'
  text: string
  start_time: number
  end_time: number
  is_partial: boolean
  uncertainty_score?: number
  uncertainty_topic?: string
  sentiment?: 'positive' | 'negative' | 'neutral'
}

export interface AISuggestion {
  id: string
  topic: string
  observation: string
  suggestion: string
  suggested_prompt: string | null
  priority: NudgePriority
  confidence: number
}
```

```
frontend/src/hooks/
  useTranscript.ts           # Manages transcript state with partial→final transitions
  useUncertainty.ts          # Tracks uncertainty score + topic from MetricsSnapshot
  useAISuggestion.ts         # On-demand suggestion requests + feedback submission
```

### 6.6 Deliverables Checklist

- [ ] `TranscriptPanel` with stable utterance ID updates (no jitter)
- [ ] `UncertaintyIndicator` overlay with fade transitions
- [ ] `AISuggestionCard` with copy, feedback buttons
- [ ] `SuggestButton` for on-demand suggestions
- [ ] `useTranscript` hook managing partial→final transitions
- [ ] Wire up `transcript_partial` / `transcript_final` message types
- [ ] Wire up LiveKit data packet topics
- [ ] Keyboard shortcut for toggling transcript panel
- [ ] Responsive layout (collapse on mobile)
- [ ] Tutor-only visibility enforcement

---

## 7. Tier 5 — Post-Session Enrichment

**Goal:** After the session ends, use the full transcript to generate richer
analytics and a searchable session record  
**Estimated time:** 2–3 weeks  
**Dependencies:** Tiers 1-4

### 7.1 Full Transcript Storage

See §3.11 for tiered storage strategy:
- **Postgres JSONB:** Compact format (no word timings except key moments)
- **S3/R2:** Full artifact with all word timings (via existing `s3_trace_store.py`)

### 7.2 AI-Generated Session Summary

After the session, run the full transcript through an LLM:

```python
@dataclass
class AISessionSummary:
    """LLM-generated post-session analysis."""
    topics_covered: list[str]                    # ["derivatives", "power rule"]
    key_moments: list[KeyMoment]                 # Significant teaching moments
    student_understanding_map: dict[str, str]    # topic → "strong" | "developing" | "weak"
    tutor_strengths: list[str]                   # What the tutor did well
    tutor_growth_areas: list[str]                # Where to improve
    recommended_follow_up: list[str]             # Topics to revisit next session
    session_narrative: str                       # 2-3 sentence natural language summary

@dataclass
class KeyMoment:
    timestamp: float
    type: str        # "breakthrough" | "confusion" | "good_question" | "missed_opportunity"
    description: str
    transcript_excerpt: str
```

### 7.3 Enhanced Analytics Dashboard

Add to `/analytics/[id]`:
1. **Transcript tab** — searchable, scrollable full transcript
2. **Topics covered** — visual display with understanding levels
3. **Key moments timeline** — clickable moments on engagement chart
4. **AI summary card** — natural language recap
5. **Follow-up recommendations** — AI-generated next-session suggestions

### 7.4 Cross-Session Topic Tracking

```python
class TopicMastery(BaseModel):
    session_id: str
    date: str
    understanding: str  # "weak" | "developing" | "strong"
    uncertainty_score: float
```

### 7.5 Deliverables Checklist

- [ ] Transcript persistence (Postgres compact + S3 full)
- [ ] Post-session LLM analysis endpoint
- [ ] `AISessionSummary` generation (PII-scrubbed input)
- [ ] Transcript tab in analytics detail page
- [ ] Topic understanding visualization
- [ ] Key moments timeline
- [ ] Cross-session topic tracking in trends
- [ ] Deletion endpoint + retention TTL automation

---

## 8. Data Model Changes

### 8.1 Backend Models (`models.py`)

```python
# Add to MetricsSnapshot
class MetricsSnapshot(BaseModel):
    # ... existing fields ...
    
    # NEW — Transcription
    transcript_available: bool = False
    
    # NEW — Uncertainty (only populated when persistence threshold met)
    student_uncertainty_score: float = 0.0
    student_uncertainty_topic: str = ""
    student_uncertainty_confidence: float = 0.0
    
    # NEW — AI coaching
    ai_suggestion: dict | None = None

# Add to SessionSummary
class SessionSummary(BaseModel):
    # ... existing fields ...
    
    # NEW
    transcript_word_count: dict[str, int] = Field(default_factory=dict)
    topics_covered: list[str] = Field(default_factory=list)
    ai_summary: str = ""
    student_understanding_map: dict[str, str] = Field(default_factory=dict)
    key_moments: list[dict] = Field(default_factory=list)
    uncertainty_timeline: list[float] = Field(default_factory=list)
```

### 8.2 Database Schema

```sql
ALTER TABLE session_summaries 
  ADD COLUMN transcript_compact JSONB DEFAULT NULL,
  ADD COLUMN ai_summary TEXT DEFAULT '',
  ADD COLUMN topics_covered JSONB DEFAULT '[]',
  ADD COLUMN student_understanding_map JSONB DEFAULT '{}',
  ADD COLUMN key_moments JSONB DEFAULT '[]',
  ADD COLUMN uncertainty_timeline JSONB DEFAULT '[]';
```

---

## 9. Infrastructure & Cost

### 9.1 Revised Per-Session Cost (60-minute session)

| Service | Usage | Cost |
|---------|-------|------|
| **Deepgram Nova-2** (student only, VAD-gated ~24 min voiced) | ~24 billed minutes | ~$0.14 |
| **Deepgram Nova-2** (tutor, if enabled, ~24 min voiced) | ~24 billed minutes | ~$0.14 |
| **LLM coaching calls** (~100 calls × ~600 tokens avg) | ~60K tokens | ~$0.03 (Haiku) |
| **Post-session LLM summary** (1 call, ~8K tokens) | ~8K tokens | ~$0.01 |
| **Total (student-only STT)** | | **~$0.18** |
| **Total (both-participant STT)** | | **~$0.32** |

At 1,000 sessions/month (student-only): **~$180/month** incremental.

**Wire cost telemetry early:** per-session STT billed seconds, LLM tokens in/out,
call count. Alert on outliers.

### 9.2 New Environment Variables

```bash
# Transcription (AssemblyAI is default; set DEEPGRAM for alternative)
LSA_ENABLE_TRANSCRIPTION=true
LSA_TRANSCRIPTION_PROVIDER=assemblyai        # "assemblyai" | "deepgram" | "mock"
LSA_ASSEMBLYAI_API_KEY=<key>                 # https://www.assemblyai.com/
# LSA_DEEPGRAM_API_KEY=<key>                 # Alternative: Deepgram
# LSA_DEEPGRAM_ENDPOINTING_MS=800            # Deepgram-only: endpointing threshold

# AI Coaching (OpenRouter is default; gives access to Claude/GPT-4o/etc.)
LSA_ENABLE_AI_COACHING=true
LSA_AI_COACHING_PROVIDER=openrouter          # "openrouter" | "anthropic"
LSA_AI_COACHING_MODEL=anthropic/claude-3.5-haiku  # OpenRouter model ID
LSA_OPENROUTER_API_KEY=<key>                 # https://openrouter.ai/
# LSA_ANTHROPIC_API_KEY=<key>                # Alternative: direct Anthropic

# Uncertainty Detection
LSA_ENABLE_UNCERTAINTY_DETECTION=true
LSA_UNCERTAINTY_UI_THRESHOLD=0.6
LSA_UNCERTAINTY_PERSISTENCE_UTTERANCES=2
LSA_UNCERTAINTY_PERSISTENCE_WINDOW_SECONDS=45

# Post-session
LSA_ENABLE_TRANSCRIPT_STORAGE=true
LSA_ENABLE_AI_SESSION_SUMMARY=true
```

### 9.3 New Dependencies

```
# backend/requirements.txt additions
deepgram-sdk>=6.0.0,<7.0.0   # Pin to v6 (method names: keep_alive, finalize, finish)
praat-parselmouth>=0.4.3      # Pitch extraction for Tier 2 paralinguistic analysis
anthropic>=0.30.0             # Direct Anthropic SDK (fallback if not using OpenRouter)
openai>=1.0.0                 # Used by OpenRouterLLMClient (OpenAI-compatible API)
```

---

## 10. Privacy & Compliance

### 10.1 Feature Flags — Separate Toggles

Enforce **separate** toggles for each privacy-sensitive capability:

| Flag | What it controls | Default |
|------|-----------------|---------|
| `enable_transcription` | Live STT processing (no storage) | `false` |
| `enable_transcript_storage` | Persist transcripts after session | `false` |
| `enable_uncertainty_detection` | Tone/uncertainty analysis | `false` |
| `enable_ai_coaching` | LLM-based suggestions (sends transcript to LLM) | `false` |
| `enable_ai_session_summary` | Post-session LLM analysis | `false` |

### 10.2 Vendor Data Retention

| Provider | Opt-out mechanism | Default behavior |
|----------|------------------|------------------|
| **Deepgram** | `mip_opt_out=true` parameter | Opted-out data retained only to process request |
| **AssemblyAI** | Opt out of model training | Zero data retention for streaming (with opt-out) |
| **Anthropic (Claude)** | API calls not used for training | No retention beyond request processing |
| **OpenAI** | API calls not used for training (API ToS) | 30-day retention for abuse monitoring |

**Implementation:** Always send `mip_opt_out=true` for Deepgram. Document
opt-out status in DPA. Set `LSA_DEEPGRAM_MIP_OPT_OUT=true` as default.

### 10.3 PII Handling

Three layers of protection:

1. **Before LLM:** `PIIScrubber` regex-based redaction (§5.6)
2. **Before storage:** Same scrubber applied to stored transcripts
3. **Future upgrade:** Vendor redaction add-ons (Deepgram offers redaction as
   a paid STT feature)

### 10.4 Consent Modal Update

Update the existing consent modal in `session/[id]/page.tsx`:

```
Current:
  "webcam video and microphone audio will be analyzed for engagement metrics"

New:
  "webcam video and microphone audio will be analyzed for engagement metrics.
   Audio may be transcribed in real-time to provide AI-powered coaching
   suggestions. Transcripts are visible to the tutor during the session and
   included in post-session analytics. No raw audio is stored."
```

### 10.5 Deletion & Retention

- **Per-session delete endpoint:** `DELETE /api/sessions/{id}/transcript`
- **Retention TTL:** Follow existing `session_retention_days` (90 days)
- **S3/R2 lifecycle:** Set object expiration matching retention policy
- **Audit log:** Record transcript deletion actions with timestamp + user

---

## 11. Testing Strategy

### 11.1 Unit Tests

| Component | Tests | Key fixtures |
|-----------|-------|-------------|
| `TranscriptionStream` | Non-blocking send, queue overflow, keepalive, reconnect, **VAD edge states** | Mock STT provider |
| `DroppableAudioQueue` | FIFO ordering, audio-only drops, control/stop preserved, capacity | N/A |
| `TranscriptBuffer` | Rolling window, text formatting, word counts | Pre-built utterance lists |
| `SpeakerBaseline` | Warmup via median (not confidence-gated), EMA post-warmup, deviation clamping | Synthetic pitch sequences |
| `LinguisticUncertaintyDetector` | Hedging, fillers, questions, **per-speaker calibration** | Labeled text pairs |
| `UncertaintyDetector` | Fusion, **persistence gating**, topic extraction | Audio+text fixture pairs |
| `AICoachingCopilot` | Interval logic, budget exhaustion, dedupe, **pedagogy constraint** | Mock LLM responses |
| `PIIScrubber` | Email, phone, SSN redaction | PII-containing text |
| `SessionClock` | Time alignment, frame-count tracking, **initial silence**, **reconnect reset** | Synthetic timestamps |
| `DeepgramSTTClient` | SDK method existence (version-pinned), event → ProviderResponse mapping | SDK import check |

### 11.2 Critical Tier 1 Integration Tests

These tests exercise the edge cases most likely to cause production bugs.
Run with the mock STT provider against synthetic audio sequences.

#### Test 1: Initial silence → first speech (timestamp alignment)

```python
async def test_initial_silence_then_speech():
    """No tail injection during initial silence.
    First utterance timestamps align near real session time.
    """
    clock = SessionClock()
    stream = TranscriptionStream(
        "test", Role.STUDENT, student_index=0, clock=clock,
        provider=MockSTTProvider(),
    )
    await stream.start()

    # 30 seconds of silence (no speech)
    for _ in range(1000):  # 1000 frames × 30ms = 30s
        stream.try_send(SILENT_PCM, is_speech=False)
        await asyncio.sleep(0.001)  # Simulate real-time pacing

    # Assert: no tail injection was enqueued (no speech preceded it)
    assert stream.stats["tail_silence_chunks_sent"] == 0
    assert stream.stats["tail_injections_canceled"] == 0

    # First speech at ~30s
    for _ in range(100):  # 3 seconds of speech
        stream.try_send(SPEECH_PCM, is_speech=True)
        await asyncio.sleep(0.001)

    # Wait for provider to emit speech_final
    utterance = await wait_for_utterance(stream, timeout=5.0)

    # Timestamp should be near 30s session time, not near 0
    assert abs(utterance.start_time - 30.0) < 2.0
```

#### Test 2: VAD flicker (cancel tail, don't split utterance)

```python
async def test_vad_flicker_cancels_tail():
    """1-2 silence frames mid-speech should not inject tail or split."""
    stream = make_stream()
    await stream.start()

    # Speak for 2 seconds
    for _ in range(66):
        stream.try_send(SPEECH_PCM, is_speech=True)

    # VAD flicker: 2 silence frames (~60ms)
    stream.try_send(SILENT_PCM, is_speech=False)  # tail enqueued
    stream.try_send(SILENT_PCM, is_speech=False)  # continued silence

    # Speech resumes immediately — should cancel pending tail
    for _ in range(66):
        stream.try_send(SPEECH_PCM, is_speech=True)

    # Then actual silence
    for _ in range(100):
        stream.try_send(SILENT_PCM, is_speech=False)

    utterance = await wait_for_utterance(stream, timeout=5.0)

    # Should be ONE utterance (not split by the flicker)
    assert stream.stats["utterances_finalized"] == 1
    assert stream.stats["tail_injections_canceled"] >= 1
    assert stream.stats["tail_silence_chunks_sent"] > 0  # Only the real tail
```

#### Test 3: Queue backpressure with pending tail injection

```python
async def test_backpressure_preserves_tail():
    """Fill queue with audio, then enqueue tail. Audio drops, tail survives."""
    stream = make_stream(queue_max_size=10)
    await stream.start()

    # Fill queue with audio (sender is slow / not draining)
    stream._in_speech = True
    for _ in range(15):
        stream.try_send(SPEECH_PCM, is_speech=True)

    # Queue should have dropped some audio
    assert stream.stats["dropped_audio_chunks"] > 0

    # Now speech→silence — tail injection must succeed
    stream.try_send(SILENT_PCM, is_speech=False)

    # Verify tail is in queue (scan for control item)
    found_control = False
    for item in stream._queue._buf:
        if item.kind == "control":
            found_control = True
            break
    assert found_control, "Tail injection was dropped — queue violation"
```

#### Test 4: Reconnect mid-silence and mid-utterance

```python
async def test_reconnect_resets_timestamps():
    """After reconnect, provider timestamps restart from 0.
    Session time mapping must still be correct.
    """
    stream = make_stream()
    await stream.start()

    # Speak, get an utterance
    send_speech(stream, duration_s=3)
    send_silence(stream, duration_s=2)
    utt1 = await wait_for_utterance(stream, timeout=5.0)

    # Simulate reconnect at session time ~5s
    await stream.handle_reconnect()

    # More silence, then speech
    send_silence(stream, duration_s=10)
    send_speech(stream, duration_s=3)
    send_silence(stream, duration_s=2)
    utt2 = await wait_for_utterance(stream, timeout=5.0)

    # utt2 should be near session time 15-20s, not near 0
    assert utt2.start_time > 10.0
    assert utt2.start_time > utt1.end_time
```

#### Test 5: Tail pacing prevents drift across multiple utterances

```python
async def test_tail_pacing_prevents_drift():
    """Fast tail injection causes cumulative drift. Pacing prevents it.
    
    With 3 utterances and ~800ms tail each, unpaced injection would cause
    ~2.4s of drift. Paced injection keeps drift < 200ms.
    """
    stream = make_stream()
    await stream.start()

    utterances = []
    for i in range(3):
        # 2s speech → 5s silence
        send_speech(stream, duration_s=2.0)
        send_silence(stream, duration_s=5.0)
        utt = await wait_for_utterance(stream, timeout=8.0)
        utterances.append(utt)

    # Expected: utt[0] ~ 0s, utt[1] ~ 7s, utt[2] ~ 14s
    # With unpaced tail: utt[1] ~ 7.8s, utt[2] ~ 15.6s (drifting)
    assert abs(utterances[1].start_time - 7.0) < 0.5  # <500ms tolerance
    assert abs(utterances[2].start_time - 14.0) < 0.5
    # Drift between consecutive utterances should be < 200ms
    for i in range(1, len(utterances)):
        expected_gap = 7.0  # 2s speech + 5s silence
        actual_gap = utterances[i].start_time - utterances[i-1].start_time
        assert abs(actual_gap - expected_gap) < 0.2
```

#### Test 6: Speech resumes during injection cancels injection

```python
async def test_mid_injection_cancel():
    """Speech resuming partway through tail injection should abort it.
    
    Uses a mock provider with small delay per send_audio() so the
    sender is "in flight" when speech resumes.
    """
    # Mock provider: 5ms per send_audio (so 800ms tail takes ~133ms)
    mock = SlowMockProvider(send_delay_s=0.005)
    stream = make_stream(provider=mock)
    await stream.start()

    # 2s speech → 1 silence frame (tail enqueued)
    send_speech(stream, duration_s=2.0)
    stream.try_send(SILENT_PCM, is_speech=False)  # Tail enqueued

    # Wait ~60ms for sender to start injecting (will have sent ~4 chunks)
    await asyncio.sleep(0.06)

    # Speech resumes — should cancel mid-flight
    for _ in range(66):  # ~2s more speech
        stream.try_send(SPEECH_PCM, is_speech=True)

    # Then actual silence for endpointing
    send_silence(stream, duration_s=2.0)
    utt = await wait_for_utterance(stream, timeout=5.0)

    # Injection should have been cut short
    assert stream.stats["tail_injections_canceled"] >= 1
    assert stream.stats["tail_silence_chunks_sent"] < 27  # < full 800ms
    # Should be ONE utterance (not split by partial injection)
    assert stream.stats["utterances_finalized"] == 1
```

### 11.3 False Positive Suppression Tests

Build fixtures specifically for:
- Students who speak with lots of fillers but are correct/confident
- Students with monotone prosody (low pitch variance ≠ uncertain)
- Noisy environments (bad mic, background noise)
- Cultural speech patterns (heavy "like"/"you know" usage)
- Short but confident responses ("Yes", "2x + 3", "I know")

### 11.3 Eval Fixtures

```
backend/tests/evals/
  fixtures/
    transcription/
      clear_speech.wav         # Clean audio for accuracy validation
      noisy_environment.wav    # Background noise
      accented_speech.wav      # Non-native English
    uncertainty/
      confident_student.json   # Audio+text: student is confident
      hesitant_student.json    # Audio+text: student is uncertain
      filler_personality.json  # High fillers but confident
      monotone_correct.json    # Monotone but correct answers
    ai_coaching/
      should_suggest.json      # Scenarios where AI should suggest
      should_not_suggest.json  # Scenarios where silence is correct
      pedagogy_only.json       # Verify no domain answers in output
      session_types/           # Per-session-type expected behaviors
```

### 11.4 End-to-End Latency Tests

Define targets and test them:

| Metric | Target | Test method |
|--------|--------|-------------|
| Partial transcript p95 | < 700ms from audio send | Timed mock provider |
| Final transcript p95 | < 1.5s from utterance end | Timed mock provider |
| Uncertainty indicator p95 | < 2s after utterance final | Integration test |
| AI suggestion p95 | < 5s when triggered | Timed mock LLM |
| Audio pipeline regression | 0ms added latency | Existing latency assertions |

### 11.5 Tutor Feedback Eval Dataset

Over time, the `👍/👎` feedback from §5.9 builds a labeled dataset:
- `(suggestion + context + metrics_snapshot)` → helpful / not helpful
- Use for prompt iteration, model comparison, and regression testing

---

## 12. Rollout Plan

### Phase 1: Transcription Only (Weeks 1–3)
- Ship Tier 1 behind `LSA_ENABLE_TRANSCRIPTION=true`
- Student-only transcription for pilot
- VAD-gated, provider endpointing, non-blocking queue
- Transcripts visible in debug mode and traces only (no UI yet)
- Validate: accuracy, latency, cost per session

### Phase 2: Uncertainty Detection (Weeks 4–6)
- Ship Tier 2 behind `LSA_ENABLE_UNCERTAINTY_DETECTION=true`
- Pitch analysis + linguistic detection with per-speaker calibration
- Persistence-gated scoring
- Debug-mode display only
- Validate: false positive rate, calibration, persistence behavior

### Phase 3: AI Coaching (Weeks 7–9)
- Ship Tier 3 behind `LSA_ENABLE_AI_COACHING=true`
- Event-triggered + baseline interval
- Pedagogy-only constraint validated
- PII scrubbing validated
- AI nudges appear alongside rule-based nudges
- Validate: suggestion quality, budget adherence, tutor feedback

### Phase 4: Frontend UX (Weeks 9–11)
- Transcript panel, uncertainty indicator, suggestion cards
- Tutor-only visibility
- "Get suggestion" button
- 👍/👎 feedback collection

### Phase 5: Post-Session & Polish (Weeks 11–14)
- Transcript storage (Postgres compact + S3 full)
- AI session summaries
- Cross-session topic tracking
- Deletion + retention automation
- Performance optimization

---

## 13. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **STT latency spikes (>1s)** | Medium | Medium | Non-blocking queue; 5-level backpressure with feature degradation (§14.4); never blocks analytics |
| **STT accuracy (accents, jargon)** | Medium | Medium | Deepgram handles accents well; add vocabulary hints; student-only reduces noise |
| **LLM hallucinated suggestions** | Medium | High | Pedagogy-only prompt constraint + code-level `AIOutputValidator` rejects domain answers (§5.7) |
| **LLM latency spikes (>3s)** | Low | Low | Timeout + fallback to rule-based; runs on slow loop; not blocking |
| **Cost overruns** | Medium | Medium | VAD gating + tail silence (§3.5); student-only mode; per-session cost telemetry; hard call budget |
| **Tutor finds AI annoying** | Medium | High | Event-triggered (not constant); intensity setting; easy dismiss/disable; 👍/👎 feedback |
| **Privacy: PII in transcripts** | High | High | Regex PII scrubber (structured patterns, §5.6); vendor opt-out; separate storage flag; deletion endpoint |
| **VAD gating breaks endpointing** | ~~High~~ Resolved | ~~High~~ | Tail-silence injection on speech→silence edge (§3.5); provider sees real silence, endpointing fires |
| **Transcript timestamps drift** | ~~High~~ Resolved | ~~Medium~~ | `SessionClock` with accumulated pause offsets (§3.8); `pause()`/`resume()` on gating transitions |
| **Uncertainty false positives** | Medium | Medium | Per-speaker calibration; persistence (2+ utterances in 45s); fusion not single-signal |
| **F0 pitch fragile in wild** | High | Low | Confidence gating; median smoothing; voiced-only; graceful fallback to text-only |
| **Cross-talk (tutor mic picks up student)** | Medium | Medium | Student-only STT for pilot; separate tracks help; echo detection exists |
| **Provider WebSocket disconnects** | Medium | Low | Auto-reconnect in sender loop; track by identity not SID; metrics on reconnects |
| **Performance regression** | Low | High | Transcription in parallel async task; existing pipeline untouched; latency assertions |
| **Transcript-dependent features degrade on drops** | Medium | Medium | Backpressure L2 suspends AI auto-triggers + shows UI indicator (§14.4); on-demand still works |

---

## 14. Engineering Gotchas

### 14.1 Track Restarts / Reconnects

LiveKit track SIDs can change on reconnect. **Key transcription streams by
participant identity + role, not by track SID.** When a new track appears for
the same identity, reconnect the STT stream rather than creating a new one.

### 14.2 Sample Rate Mismatch

Lock to a single provider-supported encoding: **linear16 PCM, 16kHz mono.**
The existing `pcm_bytes_from_audio_frame()` in `livekit_worker.py` already
resamples to 16kHz — use that output directly.

### 14.3 Multi-Student Sessions

`TranscriptBuffer`, `UncertaintyDetector`, and `TranscriptionStream` must be
**per-student** instances, not global. The existing `student_index` parameter
in `_consume_audio_track()` already handles this routing — extend the pattern.

### 14.4 Backpressure Policy — Feature Degradation, Not Just Metrics

When the STT provider is slow or audio chunks are being dropped, downstream
features (transcript UI, uncertainty detection, AI coaching) become unreliable.
Dropping chunks and logging metrics is not enough — **actively disable features
that depend on complete transcript data** to maintain tutor trust.

```
Level 0 (normal):
  All voiced audio sent to provider.
  Full feature set active.

Level 1 (partials degraded):
  Provider latency > 1s sustained for 15s.
  → Disable partial transcript UI updates (less network chatter).
  → Finals still emitted. Uncertainty + coaching still active.

Level 2 (transcript degraded):
  drop_rate (dropped_audio_chunks / voiced_chunks_received) > 0.5% sustained over 30s.
  → Stop transcript UI updates entirely.
  → Show "Transcription degraded" indicator in tutor panel.
  → Suspend AI coaching AUTO-TRIGGERS (event-triggered + baseline).
  → On-demand "Get Suggestion" button remains available (tutor-initiated).
  → Uncertainty detection continues (it's partially audio-based).

Level 3 (transcript disabled):
  Provider WebSocket down OR drop rate > 5% sustained over 60s.
  → Disable transcription for this session entirely.
  → Hide transcript panel, show "Transcription unavailable" status.
  → AI coaching falls back to rule-based only (existing system).
  → Log error + record in trace artifact.

Level 4 (recovery):
  Conditions improve (drop rate returns to 0%, latency normalizes).
  → Re-enable features in reverse order (L3 → L2 → L1 → L0).
  → Hysteresis: require 30s of normal operation before upgrading level.
```

**Implementation:** Track `_backpressure_level` in `TranscriptionStream`.
Expose it via `stats` property. The coaching system checks this level before
running AI evaluations. The frontend checks it to show/hide the transcript
panel and degradation indicators.

**Never block the audio analytics loop at any level.**

### 14.5 Observability Checklist

Record per-session and expose in trace artifacts:

- [ ] STT partial latency p50, p95
- [ ] STT final latency p50, p95
- [ ] Provider WebSocket reconnect count
- [ ] Percent of audio chunks dropped (backpressure)
- [ ] Silence chunks skipped (VAD-gated savings)
- [ ] Estimated billed STT seconds
- [ ] LLM call count, token usage (in/out), latency
- [ ] Uncertainty score distribution (detect overfiring)
- [ ] Tutor feedback counts (helpful / not helpful)

---

## 15. Latency Budgets

| Pipeline step | Target p95 | Notes |
|--------------|-----------|-------|
| `try_send()` into queue | < 0.01ms | `put_nowait()` — must never block |
| Queue → provider WebSocket | < 50ms | Background task, bounded by network |
| Provider → partial transcript | < 700ms | From audio send to partial receipt |
| Provider → final transcript | < 1.5s | From utterance end to `speech_final` |
| Uncertainty signal | < 2s | After final utterance received |
| AI suggestion (when triggered) | < 5s | LLM call + parsing |
| Post-session LLM summary | < 30s | Acceptable, runs after session |
| **Existing analytics pipeline** | **0ms added** | **Must not regress** |

---

## Appendix A: File Map Summary

### New files to create
```
backend/app/
  transcription/
    __init__.py
    stream.py               # Non-blocking queue + background sender
    buffer.py               # Rolling window
    store.py                # Tiered storage (Postgres compact + S3 full)
    clock.py                # SessionClock for time alignment
    providers/__init__.py
    providers/deepgram.py   # With endpointing, keepalive, mip_opt_out
    providers/assemblyai.py
    providers/mock.py
  
  uncertainty/
    __init__.py
    detector.py             # Fusion + persistence + per-student
    paralinguistic.py       # Pitch + SpeakerBaseline (median warmup, EMA)
    linguistic.py           # Per-speaker filler calibration
    models.py
    topic_extractor.py      # TutorQuestionTopicExtractor
  
  ai_coaching/
    __init__.py
    copilot.py              # Event-triggered + budget + dedupe
    context.py
    prompts.py              # Pedagogy-only constraint
    llm_client.py           # Prompt caching support
    pii_scrubber.py         # Regex PII redaction (structured patterns, scoped claim)
    output_validator.py     # Code-level guardrail: reject domain answers
    on_demand.py
    feedback.py             # 👍/👎 collection

frontend/src/
  components/
    transcript/
      TranscriptPanel.tsx
      TranscriptMessage.tsx # Handles partial→final via utterance_id
      UncertaintyBadge.tsx
      PartialTranscript.tsx
    coaching/
      AISuggestionCard.tsx  # With copy, feedback buttons
      SuggestButton.tsx
      SuggestedPromptBlock.tsx
  
  hooks/
    useTranscript.ts        # Stable utterance ID management
    useUncertainty.ts
    useAISuggestion.ts      # Including feedback submission
```

### Existing files to modify
```
backend/app/
  config.py                    # New settings
  models.py                    # MetricsSnapshot + SessionSummary extensions
  livekit_worker.py            # Non-blocking try_send in audio track consumer
  session_runtime.py           # AI copilot in coaching evaluation loop
  session_manager.py           # TranscriptBuffer/Store on SessionRoom
  audio_processor/prosody.py   # Add pitch_hz, pitch_confidence
  coaching_system/coach.py     # Accept AI-generated nudges
  analytics/summary.py         # Include transcript data
  analytics/recommendations.py # AI-enhanced recommendations

frontend/src/
  lib/types.ts                 # New interfaces
  hooks/useNudges.ts           # Handle ai_coaching_suggestion nudge type
  hooks/useWebSocket.ts        # Handle transcript_* message types
  app/session/[id]/page.tsx    # Transcript panel, uncertainty indicator
  app/analytics/[id]/page.tsx  # Transcript tab, AI summary
```

---

## Appendix B: Quick-Start Prototype (3 Days)

**Day 1:** Wire Deepgram streaming into `_consume_audio_track()` with the
non-blocking queue + tail-silence injection pattern. Student-only. VAD-gated
with config-driven tail silence on speech→silence edge. Print `speech_final` utterances
(built from concatenated `is_final` segments) to server logs. Verify endpointing
fires correctly and confirm VAD gating reduces billed time.

**Day 2:** Add `TranscriptBuffer`. Send `transcript_final` messages to the
tutor via existing WebSocket. Add a basic `<pre>` block in the session page
to display them. Verify stable utterance IDs work.

**Day 3:** Add `LinguisticUncertaintyDetector` (hedging word detection only,
no pitch yet). Tag uncertain utterances. Show a 🔶 badge inline. Validate
against a few real conversations.

This gives you live transcription + basic uncertainty detection in the UI
within a week — and validates the entire architecture before building the
LLM copilot.

---

## Appendix C: Review Feedback Incorporated

### R1 — Architecture Review (2026-03-13)

1. ✅ **Non-blocking audio delivery** — `try_send()` with bounded queue + background `_sender_loop` (§3.2, §3.4). R4: queue is now `DroppableAudioQueue` (§3.4)
2. ✅ **VAD-gated STT** — only voiced frames sent to provider, keepalives during silence (§3.5)
3. ✅ **Provider endpointing** — use `speech_final` for boundaries (§3.6). R4: `UtteranceEnd` deferred, requires `vad_events=true`
4. ✅ **Student-only STT** — pilot mode halves cost and privacy exposure (§3.13)
5. ✅ **Event-triggered + baseline intervals** — 30-45s baseline, burst on uncertainty/nudge (§5.3, §5.4)
6. ✅ **Prompt caching** — 80-95% token reuse flagged for implementation (§5.3)
7. ✅ **Hard per-session budget** — max 60 calls/hour (§5.4)
8. ✅ **Time alignment** — `SessionClock` with frame-count-derived audio time (§3.8)
9. ✅ **Stable utterance IDs** — `utterance_id` + `revision` for partial updates (§3.7)
10. ✅ **TranscriptStore size control** — tiered storage, word timings only for key moments (§3.11)
11. ✅ **Sentiment gated behind language** — English-only, not hard-required (§3.14)
12. ✅ **Pitch robustness** — voiced-only, median smoothing, confidence gating (§4.2.2)
13. ✅ **Baseline bootstrapping without circularity** — unconditional median warmup (§4.2.3)
14. ✅ **Per-speaker filler calibration** — relative density vs own baseline (§4.3)
15. ✅ **Linguistic signals as features, not labels** — fusion handles calibration (§4.1)
16. ✅ **Persistence requirement** — 2+ utterances in 45s before surfacing (§4.4)
17. ✅ **Topic from tutor questions** — not TF-IDF on tiny windows (§4.5)
18. ✅ **Pedagogy-only constraint** — never provide domain answers (§5.5)
19. ✅ **Suggestion dedupe** — normalized hash + per-topic cooldown (§5.4)
20. ✅ **PII scrubbing before LLM** — regex-based redaction (§5.6)
21. ✅ **Vendor opt-out** — `mip_opt_out=true` default for Deepgram (§10.2)
22. ✅ **Separate privacy toggles** — 5 independent feature flags (§10.1)
23. ✅ **Deletion + retention** — per-session delete, TTL, audit log (§10.5)
24. ✅ **Cost telemetry** — per-session tracking, alert on outliers (§9.1)
25. ✅ **Track restart by identity** — key by participant identity, not SID (§14.1)
26. ✅ **Multi-student per-student instances** — buffer/detector per student_index (§14.3)
27. ✅ **Backpressure policy** — 4-level degradation, never blocks analytics (§14.4)
28. ✅ **Observability checklist** — latency, drops, reconnects, score distribution (§14.5)
29. ✅ **Tutor feedback for eval** — 👍/👎 endpoint + dataset building (§5.9)
30. ✅ **False positive suppression tests** — specific fixtures (§11.2)
31. ✅ **End-to-end latency budgets** — concrete targets per pipeline step (§15)
32. ✅ **Pricing treated as placeholders** — telemetry over assumptions (§9.1)

### R2 — Provider Semantics Review (2026-03-13)

33. ✅ **VAD gating vs endpointing conflict** — tail-silence injection so provider sees real silence and fires `speech_final`. Option A chosen over Option B (Finalize). (§3.5)
34. ✅ **`is_final` concatenation** — explicitly documented: accumulate `is_final:true` segments, emit FinalUtterance only on `speech_final:true`. (§3.6)
35. ✅ **Time alignment with audio gating** — `SessionClock` with pause offsets. (§3.8)
36. ✅ **Backpressure: feature-disable thresholds** — 5-level policy (L0-L4). (§14.4)
37. ✅ **PII scrubbing scope** — scoped to structured patterns, upgrade path documented. (§5.6)
38. ✅ **AI output validation in code** — `AIOutputValidator`. (§5.7)
39. ✅ **`CloseStream` for session end** — sender sends on shutdown. (§3.4)
40. ✅ **Fallback Finalize** — safety net if endpointing doesn't fire. (§3.6, §3.17)

### R3 — Implementation-Level Review (2026-03-13)

41. ✅ **Tail silence = endpointing config** — `tail_silence_ms = settings.deepgram_endpointing_ms` (config-driven, not hardcoded 600ms). Guarantees provider always sees enough silence. (§3.4, §3.5)
42. ✅ **Cancelable tail injection** — `_TailInjection(token=N)` command. If speech resumes before sender processes it, token increments and injection is skipped. Prevents VAD flicker from burying real speech under injected zeros. (§3.4, §3.5)
43. ✅ **Priority queue overflow** — queue items are typed `_QueueItem(kind=audio|control|stop)`. Overflow drops oldest audio only; control/stop items are never dropped. Protects tail injection and clean shutdown. (§3.4)
44. ✅ **SessionClock connection offset** — `TranscriptionStream` stores `_provider_time_zero` (session time when provider connection opened). Updated on `start()` and `handle_reconnect()`. Provider timestamps are converted as `connection_offset + provider_audio_time + pause_offset`. (§3.4, §3.8)
45. ✅ **SessionClock reconnect handling** — `clock.reset_pauses(role_key)` clears stale pause offsets on reconnect. `_provider_time_zero` reset to current session time. (§3.4, §3.8)
46. ✅ **Receiver task lifecycle** — `_receiver_task` stored and awaited in `stop()` with `RECEIVER_DRAIN_TIMEOUT` (5s). Shutdown order: enqueue stop → sender sends CloseStream → await receiver drain → close WebSocket. (§3.4)
47. ✅ **AIOutputValidator tightened** — removed over-broad patterns (`\bthe derivative (?:is|equals|of)\b`, `\b= \d+\b`) that would reject valid teaching questions. Split into `ANSWER_PATTERNS` (both fields) and `PROMPT_ONLY_PATTERNS` (suggested_prompt only). Expression-like patterns check for declarative form only. (§5.7)
48. ✅ **KeepAlive billing as hypothesis** — documented as "assumed not billed, verified via cost telemetry" rather than asserted. (§3.5)
49. ✅ **Partial revision managed locally** — `_partial_revision` counter incremented per partial, reset on utterance boundary. Not sourced from provider. (§3.4)
50. ✅ **monotonic() for all internal timing** — KeepAlive intervals, pause tracking, session clock all use `time.monotonic()` to avoid wall-clock jumps. (§3.4, §3.8)
51. ✅ **`mip_opt_out=true` applied consistently** — noted as implementation detail to enforce in provider client, not just config. (§10.2)

### R4 — Edge-State & Provider Review (2026-03-13)

52. ✅ **VAD edge logic — no tail at session start** — replaced implicit `_tail_pending` logic with explicit `_in_speech` state. Tail injection only fires on speech→silence edges, never during initial silence, reconnect silence, or before any speech has occurred. `_ever_spoken` flag added for observability. (§3.4)
53. ✅ **Initial silence timestamp alignment** — stream starts in "paused" state (`clock.pause()` in `start()`). Sender calls `clock.resume()` on first audio send. Initial silence contributes to `pause_offset`, so provider time 0 maps correctly even if speech doesn't start for 40s. Worked example added to §3.8. (§3.4, §3.8)
54. ✅ **`utterance_end_ms` / `UtteranceEnd` requires `vad_events=true`** — removed `utterance_end_ms` from Tier 1 Deepgram options. Noted it requires `vad_events=true` if enabled later. Tier 1 relies solely on `speech_final` from `endpointing`. (§3.6, §3.15)
55. ✅ **DroppableAudioQueue replaces asyncio.Queue internals** — purpose-built queue using `collections.deque` + `asyncio.Event`. No `._queue` or `._unfinished_tasks` mutation. Selective audio-only drops, controls maintain stream order (not promoted ahead of pending audio). (§3.4, §3.5)
56. ✅ **Tail silence math.ceil + chunk rounding** — `tail_samples = math.ceil(sr * ms / 1000)`, then `num_chunks = math.ceil(tail_samples / chunk_samples)`. Guarantees ≥ endpointing_ms of silence even for non-exact config values. (§3.4)
57. ✅ **Unique IDs across tracks** — `role_key = f"{role.value}:{student_index}"`, `utterance_id = f"{role_key}:utt-{N}"`. Prevents frontend partial-update collisions when rendering both speakers. (§3.4, §3.7)
58. ✅ **STTProviderClient abstraction** — Protocol-based interface (`connect`, `send_audio`, `send_keep_alive`, `send_finalize`, `send_close_stream`, `receive_results`, `close`). `DeepgramSTTClient` maps to SDK v6 methods. Version-pinned dependency with method-existence integration test. (§3.9)
59. ✅ **Reconnect resets VAD state** — `handle_reconnect()` clears `_in_speech` and `_tail_pending`, re-enters paused state, resets connection offset and pause tracking. (§3.4)
60. ✅ **4 critical integration tests** — initial silence → first speech, VAD flicker cancellation, backpressure with pending tail, reconnect mid-silence. Full test code in §11.2. (§11.2)
61. ✅ **mip_opt_out pricing as hypothesis** — documented as "verify any pricing/behavior impact via telemetry + invoice reconciliation," not asserted as free. (§3.15)
62. ✅ **Section renumbering** — §3.9 (STTProviderClient) inserted; §3.10-3.17 renumbered consistently. Cross-references updated. (§3.*)

### R5 — Timing Correctness & Implementation Polish (2026-03-13)

63. ✅ **Real-time tail injection pacing** — tail silence paced at 30ms/chunk using `time.monotonic()` scheduling. Without pacing, ~800ms of audio-time transmits in <1ms wall time, causing cumulative timestamp drift of ~tail_duration per utterance (~12s over a 60-min session). Pacing keeps provider and session clocks in lockstep. (§3.4, §3.5)
64. ✅ **Mid-injection cancellation** — token re-checked each chunk during injection (not just before start). Handles the common case where speech resumes during the ~800ms injection window. Previous code only checked token on dequeue, leaving an 800ms gap where injection could bury real speech. (§3.4, §3.5)
65. ✅ **`_tail_pending` lifecycle completed** — cleared on: injection completion, pre-start cancel, mid-flight cancel. Previously never cleared on successful completion, causing unnecessary token increments on next speech frame. Full lifecycle table in §3.5. (§3.4, §3.5)
66. ✅ **Provider-time-anchored pause segments** — `SessionClock.pause()` now takes `provider_audio_time` (from sample counter). `provider_to_session_time()` only applies pause offsets where `provider_t >= pause.provider_time_start`. Late-arriving STT results (timestamps before pause boundary) are no longer incorrectly shifted. Uses `_PauseSegment` list per role_key. (§3.8)
67. ✅ **DroppableAudioQueue stale control coalescing** — when buffer is full of controls (no audio to drop), `_coalesce_stale_controls()` removes older `_TailInjection` items that would be skipped by the sender anyway (token mismatch). Keeps at most 1. Stop items never removed. Bounds growth in pathological VAD flicker. (§3.4)
68. ✅ **KeepAlive interval config-driven** — `KEEPALIVE_INTERVAL` constant removed. Now uses `settings.transcription_keepalive_interval_seconds` via constructor parameter. (§3.4, §3.15)
69. ✅ **Deepgram SDK version pin fixed** — dependencies section updated from `>=3.0.0` to `>=6.0.0,<7.0.0` to match STTProviderClient method names (`keep_alive`, `finalize`, `finish`). (§9.3)
70. ✅ **Precise backpressure denominators** — `voiced_chunks_received` (VAD=true frames into try_send) is the denominator. `drop_rate = dropped_audio_chunks / voiced_chunks_received`. Tail silence chunks excluded from both numerator and denominator. `TranscriptionStats` updated with all metric names. (§3.16, §14.4)
71. ✅ **`_samples_sent_to_provider` counter** — tracks cumulative PCM samples sent (real audio + tail silence). Used to anchor pause boundaries at precise provider audio times. Exposed as `provider_audio_time_s` in stats. (§3.4)
72. ✅ **Test 5: tail pacing drift** — 3 utterances with silence gaps. Asserts <500ms total timestamp drift and <200ms per-utterance gap error. Fails immediately without pacing. (§11.2)
73. ✅ **Test 6: mid-injection cancel** — mock provider with delay so sender is in-flight when speech resumes. Asserts injection stops early, fewer chunks sent than expected, utterance not split. (§11.2)
