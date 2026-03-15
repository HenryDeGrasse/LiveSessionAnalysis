"""DroppableAudioQueue – bounded async queue with smart audio-drop policy.

Designed for the STT pipeline: audio chunks are droppable under back-pressure
while control and stop items are always preserved.  Uses ``collections.deque``
and ``asyncio.Event`` (not ``asyncio.Queue`` internals) for simplicity and
explicit overflow semantics.

Single-consumer pattern: only one coroutine should call ``get()`` at a time.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class _QueueItem:
    """Internal envelope stored in the deque."""

    kind: Literal["audio", "control", "stop"]
    payload: Any


@dataclass(frozen=True)
class _TailInjection:
    """Marker used to coalesce stale control items.

    When a newer control item supersedes an older one of the same token, the
    older one is removed so only the latest version is kept.
    """

    token: int


class DroppableAudioQueue:
    """Bounded async queue that drops oldest *audio* items on overflow.

    Parameters
    ----------
    maxsize:
        Maximum number of items (all kinds) the queue can hold.
    """

    def __init__(self, maxsize: int = 100) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._buf: deque[_QueueItem] = deque()
        self._not_empty = asyncio.Event()
        self._dropped_count = 0
        self._audio_dropped_count = 0

    # -- Public API -----------------------------------------------------------

    def put_nowait(self, payload: Any, *, kind: Literal["audio", "control", "stop"] = "audio") -> None:
        """Enqueue an item, making room first when the queue is full.

        Overflow handling is intentionally selective:
        1. Drop the oldest audio item, if any.
        2. Otherwise coalesce stale ``_TailInjection`` controls.
        3. Otherwise force-accept the item and temporarily exceed ``maxsize``.

        This preserves control and stop items while still bounding pathological
        control-only growth caused by repeated stale tail-injection commands.
        """
        item = _QueueItem(kind=kind, payload=payload)

        if len(self._buf) >= self._maxsize and not self._drop_oldest_audio():
            self._coalesce_stale_controls()

        self._buf.append(item)
        self._not_empty.set()

    async def get(self) -> _QueueItem:
        """Wait for and return the next item (FIFO).

        Intended for a single consumer – concurrent ``get()`` calls are not
        supported.
        """
        while not self._buf:
            self._not_empty.clear()
            await self._not_empty.wait()
        item = self._buf.popleft()
        if not self._buf:
            self._not_empty.clear()
        return item

    def qsize(self) -> int:
        """Return current number of items in the queue."""
        return len(self._buf)

    @property
    def dropped_count(self) -> int:
        """Total number of queue items removed due to overflow handling."""
        return self._dropped_count

    @property
    def audio_dropped_count(self) -> int:
        """Total number of *audio* items dropped since creation."""
        return self._audio_dropped_count

    # -- Internal helpers -----------------------------------------------------

    def _drop_oldest_audio(self) -> bool:
        """Remove the oldest audio item from the deque.

        Returns ``True`` when an audio item was removed, otherwise ``False``.
        """
        for i, item in enumerate(self._buf):
            if item.kind == "audio":
                del self._buf[i]
                self._dropped_count += 1
                self._audio_dropped_count += 1
                return True
        return False

    def _coalesce_stale_controls(self) -> None:
        """Remove older stale ``_TailInjection`` controls.

        Older tail-injection commands become redundant once newer ones exist;
        the sender would skip them anyway when their token is outdated.  Keep
        at most the newest queued ``_TailInjection`` and never remove stop
        items or non-tail control messages.
        """
        tail_indices = [
            i
            for i, item in enumerate(self._buf)
            if item.kind == "control" and isinstance(item.payload, _TailInjection)
        ]
        for i in reversed(tail_indices[:-1]):
            del self._buf[i]
            self._dropped_count += 1

    def put_control(self, payload: Any, *, coalesce_token: int | None = None) -> None:
        """Convenience: enqueue a control item.

        ``coalesce_token`` is accepted for forward compatibility with the
        planned stream integration, but stale tail-control coalescing is driven
        by queue overflow semantics rather than exact token matching.
        """
        _ = coalesce_token
        self.put_nowait(payload, kind="control")

    def put_stop(self) -> None:
        """Convenience: enqueue a stop sentinel."""
        self.put_nowait(None, kind="stop")
