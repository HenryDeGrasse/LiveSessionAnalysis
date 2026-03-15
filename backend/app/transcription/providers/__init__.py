"""STT provider abstractions for the transcription pipeline.

All STT backends (Deepgram, AssemblyAI, mock) implement the
:class:`STTProviderClient` protocol so that :class:`TranscriptionStream`
can treat them interchangeably.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from app.transcription.models import ProviderResponse


@runtime_checkable
class STTProviderClient(Protocol):
    """Protocol that every STT provider must satisfy.

    Lifecycle
    ---------
    1. ``connect()``        – open the streaming connection.
    2. ``send_audio()``     – push PCM chunks.
    3. ``send_keep_alive()``– heartbeat during silence.
    4. ``send_finalize()``  – request server-side flush of buffered audio.
    5. ``send_close_stream()`` – signal end of audio stream gracefully.
    6. ``receive_results()``– async-iterate over provider responses.
    7. ``close()``          – tear down the connection.
    """

    async def connect(self) -> None:
        """Open the streaming connection to the STT service."""
        ...

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Send a chunk of raw PCM audio to the provider."""
        ...

    async def send_keep_alive(self) -> None:
        """Send a keep-alive / heartbeat message."""
        ...

    async def send_finalize(self) -> None:
        """Request that the provider flush and finalize buffered audio."""
        ...

    async def send_close_stream(self) -> None:
        """Signal to the provider that no more audio will be sent."""
        ...

    def receive_results(self) -> AsyncIterator[ProviderResponse]:
        """Yield :class:`ProviderResponse` objects as they arrive."""
        ...

    async def close(self) -> None:
        """Tear down the connection and release resources."""
        ...


__all__ = [
    "STTProviderClient",
]
