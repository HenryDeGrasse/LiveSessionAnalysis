"""Deepgram STT provider client.

Wraps the Deepgram Python SDK v6 streaming (live) API and adapts it into
the async-iterator interface expected by :class:`STTProviderClient`.

SDK v6 API mapping
------------------
- ``send_audio``        → ``connection.send_media(data)``
- ``send_keep_alive``   → ``connection.send_keep_alive()``
- ``send_finalize``     → ``connection.send_finalize()``
- ``send_close_stream`` → ``connection.send_close_stream()``
- Results are polled via ``connection.recv()`` in a background thread
  and placed on an ``asyncio.Queue`` for ``receive_results()``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

from app.config import settings
from app.transcription.models import ProviderResponse, SentimentLabel, WordTiming

logger = logging.getLogger(__name__)

# Languages for which Deepgram supports sentiment analysis.
_SENTIMENT_SUPPORTED_LANGUAGES = frozenset({"en", "es", "fr", "de"})


class DeepgramSTTClient:
    """Streaming STT client backed by the Deepgram SDK v6.

    Implements the :class:`STTProviderClient` protocol so it can be used
    interchangeably with :class:`MockSTTProvider`.

    SDK v6 uses a synchronous context-manager approach for live connections.
    We bridge into asyncio via a background thread that calls ``recv()`` in a
    loop and enqueues results onto an ``asyncio.Queue``.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        sample_rate: int = 16_000,
        channels: int = 1,
        encoding: str = "linear16",
        endpointing_ms: Optional[int] = None,
        interim_results: bool = True,
        smart_format: bool = True,
        punctuate: bool = True,
        enable_sentiment: Optional[bool] = None,
        mip_opt_out: Optional[bool] = None,
    ) -> None:
        self._api_key = api_key or settings.deepgram_api_key
        self._model = model or settings.transcription_model
        self._language = language or settings.transcription_language
        self._sample_rate = sample_rate
        self._channels = channels
        self._encoding = encoding
        self._endpointing_ms = (
            endpointing_ms if endpointing_ms is not None else settings.deepgram_endpointing_ms
        )
        self._interim_results = interim_results
        self._smart_format = smart_format
        self._punctuate = punctuate
        self._enable_sentiment = (
            enable_sentiment
            if enable_sentiment is not None
            else settings.transcription_enable_sentiment
        )
        self._mip_opt_out = (
            mip_opt_out if mip_opt_out is not None else settings.deepgram_mip_opt_out
        )

        # Runtime state – populated by ``connect()``.
        self._client: Any = None
        self._connection: Any = None
        self._ctx_manager: Any = None
        self._result_queue: asyncio.Queue[Optional[ProviderResponse]] = asyncio.Queue()
        self._connected = False
        self._recv_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -- Configuration builder ------------------------------------------------

    def build_connect_kwargs(self) -> Dict[str, str]:
        """Return keyword arguments for ``client.listen.v1.connect(...)``.

        SDK v6 ``connect()`` accepts all options as string keyword args.
        """
        kwargs: Dict[str, str] = {
            "model": self._model,
            "language": self._language,
            "sample_rate": str(self._sample_rate),
            "channels": str(self._channels),
            "encoding": self._encoding,
            "punctuate": str(self._punctuate).lower(),
            "interim_results": str(self._interim_results).lower(),
            "smart_format": str(self._smart_format).lower(),
            "endpointing": str(self._endpointing_ms),
        }

        if self._mip_opt_out:
            kwargs["mip_opt_out"] = "true"

        # Deepgram's live websocket ``listen.v1.connect(...)`` in SDK v6.0.x does
        # not expose a ``sentiment`` parameter, even though other Deepgram APIs do.
        # We still gate the feature flag here so callers can reason about whether
        # sentiment would be eligible for the chosen language, but we avoid sending
        # unsupported kwargs to the SDK.
        if self._enable_sentiment and self._language not in _SENTIMENT_SUPPORTED_LANGUAGES:
            logger.info(
                "Deepgram live sentiment disabled for unsupported language '%s'",
                self._language,
            )

        return kwargs

    # -- Protocol methods -----------------------------------------------------

    async def connect(self) -> None:
        """Open a live streaming connection to Deepgram."""
        if self._connected:
            raise RuntimeError("DeepgramSTTClient is already connected")

        # Late-import so the rest of the codebase is not gated on deepgram-sdk.
        from deepgram import DeepgramClient

        self._client = DeepgramClient(api_key=self._api_key)

        connect_kwargs = self.build_connect_kwargs()
        self._ctx_manager = self._client.listen.v1.connect(**connect_kwargs)
        self._connection = self._ctx_manager.__enter__()

        self._connected = True
        self._loop = asyncio.get_running_loop()

        # Start background recv thread
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True, name="deepgram-recv"
        )
        self._recv_thread.start()

        logger.info("Deepgram live connection established (model=%s)", self._model)

    async def send_audio(self, pcm_chunk: bytes) -> None:
        self._ensure_connected()
        self._connection.send_media(pcm_chunk)

    async def send_keep_alive(self) -> None:
        self._ensure_connected()
        self._connection.send_keep_alive()

    async def send_finalize(self) -> None:
        self._ensure_connected()
        self._connection.send_finalize()

    async def send_close_stream(self) -> None:
        self._ensure_connected()
        self._connection.send_close_stream()

    async def receive_results(self) -> AsyncIterator[ProviderResponse]:  # type: ignore[override]
        """Yield normalised :class:`ProviderResponse` objects until closed."""
        while True:
            item = await self._result_queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        """Tear down the connection and release resources."""
        self._connected = False
        if self._ctx_manager is not None:
            try:
                self._ctx_manager.__exit__(None, None, None)
            except Exception:
                pass
            self._ctx_manager = None
        self._connection = None
        self._client = None
        # Signal receive_results to exit
        await self._result_queue.put(None)

    # -- Internal helpers ------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self._connected or self._connection is None:
            raise RuntimeError("DeepgramSTTClient is not connected")

    def _recv_loop(self) -> None:
        """Background thread: poll ``recv()`` and enqueue mapped results."""
        assert self._loop is not None
        try:
            while self._connected and self._connection is not None:
                try:
                    result = self._connection.recv()
                    resp = self._map_result(result)
                    if resp is not None:
                        self._loop.call_soon_threadsafe(
                            self._result_queue.put_nowait, resp
                        )
                except Exception as exc:
                    if not self._connected:
                        break
                    logger.error("Deepgram recv error: %s", exc)
                    break
        finally:
            # Ensure sentinel is pushed so receive_results exits
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(
                    self._result_queue.put_nowait, None
                )

    @staticmethod
    def _map_result(result: object) -> Optional[ProviderResponse]:
        """Convert a Deepgram SDK ``ListenV1Results`` to our model.

        Also handles ``ListenV1Metadata``, ``ListenV1UtteranceEnd``, etc.
        by returning ``None`` for non-transcript messages.
        """
        # Only process Results-type messages
        result_type = getattr(result, "type", None)
        if result_type != "Results":
            return None

        channel = getattr(result, "channel", None)
        if channel is None:
            return None
        alternatives = getattr(channel, "alternatives", None)
        if not alternatives:
            return None

        alt = alternatives[0]
        text: str = getattr(alt, "transcript", "") or ""
        if not text.strip():
            return None

        confidence: float = getattr(alt, "confidence", 1.0)

        # Word timings
        raw_words = getattr(alt, "words", []) or []
        words: List[WordTiming] = []
        for w in raw_words:
            words.append(
                WordTiming(
                    word=getattr(w, "punctuated_word", None) or getattr(w, "word", ""),
                    start=float(getattr(w, "start", 0.0)),
                    end=float(getattr(w, "end", 0.0)),
                    confidence=float(getattr(w, "confidence", 1.0)),
                )
            )

        start = words[0].start if words else getattr(result, "start", 0.0)
        end = words[-1].end if words else start

        # is_final / speech_final flags
        is_final: bool = bool(getattr(result, "is_final", False))
        speech_final: bool = bool(getattr(result, "speech_final", False))

        # Channel index
        channel_index = getattr(result, "channel_index", [0])
        channel_idx = int(channel_index[0]) if channel_index else 0

        # Language from first word or alternatives
        language = "en"
        languages = getattr(alt, "languages", None)
        if languages:
            language = languages[0]

        return ProviderResponse(
            is_final=is_final,
            speech_final=speech_final,
            text=text,
            start=start,
            end=end,
            words=words,
            confidence=confidence,
            sentiment=None,
            sentiment_score=0.0,
            channel=channel_idx,
            language=language,
        )


__all__ = [
    "DeepgramSTTClient",
]
