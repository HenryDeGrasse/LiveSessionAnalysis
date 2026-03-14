"""AssemblyAI STT provider client — Universal Streaming v3.

Drop-in replacement for Deepgram. Uses AssemblyAI's Universal Streaming
WebSocket API (``wss://streaming.assemblyai.com/v3/ws``).

AssemblyAI v3 streaming semantics
----------------------------------
- Audio: send raw PCM bytes directly over the WebSocket (binary frames).
- Responses are JSON with ``type``:
  - ``"Begin"``: session opened (contains session ``id`` and ``expires_at``).
  - ``"Turn"``:  transcript update.  Has ``end_of_turn: bool`` to indicate
    whether the segment is interim (partial) or committed (final).
    Words carry ``word_is_final`` for per-word commitment.
  - ``"SpeechStarted"``: VAD detected speech start.
  - ``"Termination"``: session ended.
- End-of-turn detection is built-in (configurable via ``min_turn_silence``
  and ``max_turn_silence`` parameters).
- Finalize: send ``{"type": "Terminate"}`` JSON to flush buffered audio.
- ForceEndpoint: send ``{"type": "ForceEndpoint"}`` to force utterance boundary.

Mapping to ``ProviderResponse``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- ``end_of_turn=False`` → ``is_final=False, speech_final=False`` (partial)
- ``end_of_turn=True``  → ``is_final=True,  speech_final=True``  (final)

API docs: https://www.assemblyai.com/docs/universal-streaming
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, List, Optional

from app.config import settings
from app.transcription.models import ProviderResponse, WordTiming

logger = logging.getLogger(__name__)

# AssemblyAI API version required for v3 streaming
_API_VERSION = "2025-05-12"


class AssemblyAISTTClient:
    """Streaming STT client using AssemblyAI Universal Streaming v3.

    Implements the :class:`STTProviderClient` protocol.

    Uses the ``websockets`` library directly (async) rather than the
    AssemblyAI SDK (which is sync/threaded) to stay consistent with
    the project's asyncio architecture.
    """

    STREAMING_HOST = "streaming.assemblyai.com"
    STREAMING_URL = f"wss://{STREAMING_HOST}/v3/ws"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        sample_rate: int = 16_000,
        speech_model: str = "u3-rt-pro",
        encoding: str = "pcm_s16le",
        min_turn_silence: Optional[int] = None,
        max_turn_silence: Optional[int] = None,
    ) -> None:
        self._api_key = api_key or settings.assemblyai_api_key
        self._sample_rate = sample_rate
        self._speech_model = speech_model
        self._encoding = encoding
        self._min_turn_silence = min_turn_silence
        self._max_turn_silence = max_turn_silence

        self._ws: Any = None
        self._connected = False
        self._result_queue: asyncio.Queue[Optional[ProviderResponse]] = asyncio.Queue()
        self._recv_task: Optional[asyncio.Task[None]] = None

    # -- Protocol methods -----------------------------------------------------

    async def connect(self) -> None:
        """Open a v3 streaming WebSocket to AssemblyAI."""
        if self._connected:
            raise RuntimeError("AssemblyAISTTClient is already connected")

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets package required for AssemblyAI streaming. "
                "Install with: pip install websockets"
            )

        # Build query params
        params: dict[str, str] = {
            "sample_rate": str(self._sample_rate),
            "speech_model": self._speech_model,
        }
        if self._encoding:
            params["encoding"] = self._encoding
        if self._min_turn_silence is not None:
            params["min_turn_silence"] = str(self._min_turn_silence)
        if self._max_turn_silence is not None:
            params["max_turn_silence"] = str(self._max_turn_silence)

        from urllib.parse import urlencode
        url = f"{self.STREAMING_URL}?{urlencode(params)}"

        headers = {
            "Authorization": self._api_key,
            "AssemblyAI-Version": _API_VERSION,
        }

        self._ws = await websockets.connect(
            url,
            extra_headers=headers,
            open_timeout=15,
        )
        self._connected = True

        # Start background receiver
        self._recv_task = asyncio.create_task(
            self._recv_loop(), name="assemblyai-v3-recv"
        )

        logger.info(
            "AssemblyAI v3 streaming connection established (model=%s)",
            self._speech_model,
        )

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Send a raw PCM audio chunk as a binary WebSocket frame.

        AssemblyAI v3 accepts raw bytes directly (no base64 wrapping).
        """
        if not self._connected or self._ws is None:
            raise RuntimeError("AssemblyAISTTClient is not connected")

        await self._ws.send(pcm_chunk)

    async def send_keep_alive(self) -> None:
        """Not needed for AssemblyAI (no keepalive protocol).

        We send a small silent frame to prevent inactivity timeout.
        """
        if not self._connected or self._ws is None:
            return
        # 10ms of silence at 16kHz 16-bit mono = 320 bytes
        try:
            await self._ws.send(bytes(320))
        except Exception:
            pass

    async def send_finalize(self) -> None:
        """Force an endpoint (flush any buffered partial into a final)."""
        if not self._connected or self._ws is None:
            return
        msg = json.dumps({"type": "ForceEndpoint"})
        await self._ws.send(msg)

    async def send_close_stream(self) -> None:
        """Terminate the streaming session gracefully."""
        if not self._connected or self._ws is None:
            return
        msg = json.dumps({"type": "Terminate"})
        await self._ws.send(msg)

    async def receive_results(self) -> AsyncIterator[ProviderResponse]:  # type: ignore[override]
        """Yield normalized ProviderResponse objects until closed."""
        while True:
            item = await self._result_queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        """Tear down the WebSocket connection."""
        self._connected = False
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        # Signal receive_results to exit
        await self._result_queue.put(None)

    # -- Internal helpers -----------------------------------------------------

    async def _recv_loop(self) -> None:
        """Read messages from AssemblyAI v3 WebSocket and map to ProviderResponse."""
        try:
            async for raw_msg in self._ws:
                # Binary frames are echoed audio — ignore
                if isinstance(raw_msg, bytes):
                    continue

                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "Begin":
                    session_id = msg.get("id", "")
                    logger.info("AssemblyAI v3 session started: %s", session_id)
                    continue

                if msg_type == "Termination":
                    dur = msg.get("audio_duration_seconds", "?")
                    logger.info("AssemblyAI v3 session terminated (audio=%ss)", dur)
                    break

                if msg_type == "Turn":
                    resp = self._map_turn_event(msg)
                    if resp is not None:
                        await self._result_queue.put(resp)
                    continue

                if msg_type == "SpeechStarted":
                    # Could be used for VAD, but we have our own
                    continue

                if "error" in msg:
                    error = msg.get("error", "Unknown error")
                    logger.error("AssemblyAI v3 error: %s", error)
                    continue

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._connected:
                logger.error("AssemblyAI v3 recv loop error: %s", exc)
        finally:
            await self._result_queue.put(None)

    @staticmethod
    def _map_turn_event(msg: dict) -> Optional[ProviderResponse]:
        """Map an AssemblyAI v3 ``Turn`` event to ProviderResponse."""
        text = msg.get("transcript", "").strip()
        if not text:
            return None

        end_of_turn = msg.get("end_of_turn", False)
        # end_of_turn=True → committed utterance (is_final + speech_final)
        # end_of_turn=False → interim partial
        is_final = end_of_turn
        speech_final = end_of_turn

        # Word-level timings
        raw_words = msg.get("words", [])
        words: List[WordTiming] = []
        for w in raw_words:
            words.append(
                WordTiming(
                    word=w.get("text", ""),
                    start=w.get("start", 0) / 1000.0,  # ms → seconds
                    end=w.get("end", 0) / 1000.0,
                    confidence=w.get("confidence", 1.0),
                )
            )

        # Compute utterance time span from words
        audio_start = words[0].start if words else 0.0
        audio_end = words[-1].end if words else 0.0

        confidence = msg.get("end_of_turn_confidence", 0.95) if end_of_turn else 0.0

        return ProviderResponse(
            is_final=is_final,
            speech_final=speech_final,
            text=text,
            start=audio_start,
            end=audio_end,
            words=words,
            confidence=confidence,
            sentiment=None,
            sentiment_score=0.0,
            channel=0,
            language=msg.get("language_code", "en") or "en",
        )


__all__ = ["AssemblyAISTTClient"]
