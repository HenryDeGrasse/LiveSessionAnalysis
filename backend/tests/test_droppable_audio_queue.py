"""Tests for DroppableAudioQueue."""

from __future__ import annotations

import asyncio

import pytest

from app.transcription.queue import DroppableAudioQueue, _QueueItem, _TailInjection


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_maxsize(self):
        q = DroppableAudioQueue()
        assert q.qsize() == 0
        assert q.dropped_count == 0
        assert q.audio_dropped_count == 0

    def test_custom_maxsize(self):
        q = DroppableAudioQueue(maxsize=5)
        assert q.qsize() == 0

    def test_invalid_maxsize(self):
        with pytest.raises(ValueError, match="maxsize must be >= 1"):
            DroppableAudioQueue(maxsize=0)
        with pytest.raises(ValueError, match="maxsize must be >= 1"):
            DroppableAudioQueue(maxsize=-1)


# ---------------------------------------------------------------------------
# FIFO ordering
# ---------------------------------------------------------------------------


class TestFIFO:
    @pytest.mark.asyncio
    async def test_fifo_order(self):
        q = DroppableAudioQueue(maxsize=10)
        for i in range(5):
            q.put_nowait(f"audio-{i}")
        items = [await q.get() for _ in range(5)]
        assert [it.payload for it in items] == [f"audio-{i}" for i in range(5)]
        assert all(it.kind == "audio" for it in items)

    @pytest.mark.asyncio
    async def test_mixed_fifo_order(self):
        q = DroppableAudioQueue(maxsize=10)
        q.put_nowait(b"a1")
        q.put_nowait("ctrl-1", kind="control")
        q.put_nowait(b"a2")
        q.put_nowait(None, kind="stop")

        items = [await q.get() for _ in range(4)]
        assert items[0] == _QueueItem(kind="audio", payload=b"a1")
        assert items[1] == _QueueItem(kind="control", payload="ctrl-1")
        assert items[2] == _QueueItem(kind="audio", payload=b"a2")
        assert items[3] == _QueueItem(kind="stop", payload=None)


# ---------------------------------------------------------------------------
# Audio-only drops on overflow
# ---------------------------------------------------------------------------


class TestAudioDropsOnOverflow:
    @pytest.mark.asyncio
    async def test_oldest_audio_dropped(self):
        q = DroppableAudioQueue(maxsize=3)
        q.put_nowait(b"a1")
        q.put_nowait(b"a2")
        q.put_nowait(b"a3")
        # Queue is full (3/3). Next put should drop oldest audio (a1).
        q.put_nowait(b"a4")
        assert q.qsize() == 3
        assert q.dropped_count == 1
        assert q.audio_dropped_count == 1

        items = [await q.get() for _ in range(3)]
        assert [it.payload for it in items] == [b"a2", b"a3", b"a4"]

    @pytest.mark.asyncio
    async def test_multiple_drops(self):
        q = DroppableAudioQueue(maxsize=2)
        q.put_nowait(b"a1")
        q.put_nowait(b"a2")
        q.put_nowait(b"a3")  # drops a1
        q.put_nowait(b"a4")  # drops a2
        assert q.dropped_count == 2
        assert q.audio_dropped_count == 2
        assert q.qsize() == 2

        items = [await q.get() for _ in range(2)]
        assert [it.payload for it in items] == [b"a3", b"a4"]

    @pytest.mark.asyncio
    async def test_drop_skips_control_items(self):
        """When the queue is full and all older items are control/stop,
        audio items at the tail are still the ones dropped (oldest audio)."""
        q = DroppableAudioQueue(maxsize=3)
        q.put_nowait("ctrl", kind="control")
        q.put_nowait(b"a1")
        q.put_nowait(b"a2")
        # Full. Next audio should drop a1 (oldest audio), not ctrl.
        q.put_nowait(b"a3")
        assert q.qsize() == 3
        assert q.dropped_count == 1
        assert q.audio_dropped_count == 1

        items = [await q.get() for _ in range(3)]
        assert items[0] == _QueueItem(kind="control", payload="ctrl")
        assert items[1].payload == b"a2"
        assert items[2].payload == b"a3"


# ---------------------------------------------------------------------------
# Control items never dropped
# ---------------------------------------------------------------------------


class TestControlItemsNeverDropped:
    @pytest.mark.asyncio
    async def test_controls_preserved_under_pressure(self):
        q = DroppableAudioQueue(maxsize=3)
        q.put_nowait("c1", kind="control")
        q.put_nowait("c2", kind="control")
        q.put_nowait("c3", kind="control")
        # Queue full with only controls. Adding more should NOT drop any.
        q.put_nowait("c4", kind="control")
        # Temporarily over capacity by 1
        assert q.qsize() == 4
        assert q.dropped_count == 0

        items = [await q.get() for _ in range(4)]
        assert [it.payload for it in items] == ["c1", "c2", "c3", "c4"]


# ---------------------------------------------------------------------------
# Stop items never dropped
# ---------------------------------------------------------------------------


class TestStopItemsNeverDropped:
    @pytest.mark.asyncio
    async def test_stop_preserved(self):
        q = DroppableAudioQueue(maxsize=2)
        q.put_nowait(None, kind="stop")
        q.put_nowait(None, kind="stop")
        # Full. Adding audio should not drop stop items.
        q.put_nowait(b"audio")
        # Over capacity (no audio to drop among the first 2)
        assert q.qsize() == 3
        assert q.dropped_count == 0


# ---------------------------------------------------------------------------
# Stale control coalescing
# ---------------------------------------------------------------------------


class TestStaleControlCoalescing:
    def test_coalesce_keeps_only_newest_tail_injection_when_invoked(self):
        q = DroppableAudioQueue(maxsize=10)
        q.put_nowait(_TailInjection(token=1), kind="control")
        q.put_nowait("plain-control", kind="control")
        q.put_nowait(_TailInjection(token=2), kind="control")
        q.put_nowait(_TailInjection(token=3), kind="control")

        q._coalesce_stale_controls()

        assert q.qsize() == 2
        assert q.dropped_count == 2
        assert q.audio_dropped_count == 0
        assert list(q._buf) == [
            _QueueItem(kind="control", payload="plain-control"),
            _QueueItem(kind="control", payload=_TailInjection(token=3)),
        ]

    @pytest.mark.asyncio
    async def test_overflow_coalesces_stale_tail_controls_before_append(self):
        q = DroppableAudioQueue(maxsize=3)
        q.put_nowait(_TailInjection(token=1), kind="control")
        q.put_nowait(_TailInjection(token=2), kind="control")
        q.put_nowait(_TailInjection(token=3), kind="control")

        q.put_nowait(_TailInjection(token=4), kind="control")

        assert q.qsize() == 2
        assert q.dropped_count == 2
        assert q.audio_dropped_count == 0

        items = [await q.get() for _ in range(2)]
        assert items == [
            _QueueItem(kind="control", payload=_TailInjection(token=3)),
            _QueueItem(kind="control", payload=_TailInjection(token=4)),
        ]

    def test_coalesce_does_not_touch_non_tail_controls(self):
        q = DroppableAudioQueue(maxsize=10)
        q.put_control("plain-ctrl")
        q.put_control("plain-ctrl-2")

        q._coalesce_stale_controls()

        assert q.qsize() == 2
        assert q.dropped_count == 0
        assert q.audio_dropped_count == 0


# ---------------------------------------------------------------------------
# Capacity bounds
# ---------------------------------------------------------------------------


class TestCapacityBounds:
    def test_within_capacity(self):
        q = DroppableAudioQueue(maxsize=5)
        for i in range(5):
            q.put_nowait(i)
        assert q.qsize() == 5
        assert q.dropped_count == 0
        assert q.audio_dropped_count == 0

    def test_over_capacity_audio_dropped(self):
        q = DroppableAudioQueue(maxsize=3)
        for i in range(10):
            q.put_nowait(i)
        assert q.qsize() == 3
        assert q.dropped_count == 7
        assert q.audio_dropped_count == 7

    def test_maxsize_one(self):
        q = DroppableAudioQueue(maxsize=1)
        q.put_nowait(b"a")
        q.put_nowait(b"b")
        assert q.qsize() == 1
        assert q.dropped_count == 1
        assert q.audio_dropped_count == 1


# ---------------------------------------------------------------------------
# Empty queue awaiting
# ---------------------------------------------------------------------------


class TestEmptyQueueAwaiting:
    @pytest.mark.asyncio
    async def test_get_blocks_until_put(self):
        q = DroppableAudioQueue(maxsize=10)
        result: list[_QueueItem] = []

        async def consumer():
            result.append(await q.get())

        task = asyncio.create_task(consumer())
        # Give consumer a chance to block
        await asyncio.sleep(0.01)
        assert not task.done()

        q.put_nowait(b"hello")
        await asyncio.wait_for(task, timeout=1.0)
        assert result[0].payload == b"hello"

    @pytest.mark.asyncio
    async def test_get_returns_immediately_when_non_empty(self):
        q = DroppableAudioQueue(maxsize=10)
        q.put_nowait(b"data")
        item = await asyncio.wait_for(q.get(), timeout=0.1)
        assert item.payload == b"data"

    @pytest.mark.asyncio
    async def test_multiple_puts_wake_consumer(self):
        q = DroppableAudioQueue(maxsize=10)
        items: list[_QueueItem] = []

        async def consumer():
            for _ in range(3):
                items.append(await q.get())

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)

        q.put_nowait(b"1")
        q.put_nowait(b"2")
        q.put_nowait(b"3")

        await asyncio.wait_for(task, timeout=1.0)
        assert [it.payload for it in items] == [b"1", b"2", b"3"]


# ---------------------------------------------------------------------------
# Convenience methods
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    @pytest.mark.asyncio
    async def test_put_stop(self):
        q = DroppableAudioQueue(maxsize=10)
        q.put_stop()
        item = await q.get()
        assert item.kind == "stop"
        assert item.payload is None

    @pytest.mark.asyncio
    async def test_put_control(self):
        q = DroppableAudioQueue(maxsize=10)
        q.put_control({"type": "config_change"})
        item = await q.get()
        assert item.kind == "control"
        assert item.payload == {"type": "config_change"}


# ---------------------------------------------------------------------------
# QueueItem frozen
# ---------------------------------------------------------------------------


class TestQueueItemFrozen:
    def test_immutable(self):
        item = _QueueItem(kind="audio", payload=b"data")
        with pytest.raises(AttributeError):
            item.kind = "control"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            item.payload = None  # type: ignore[misc]


class TestTailInjectionFrozen:
    def test_immutable(self):
        ti = _TailInjection(token=42)
        with pytest.raises(AttributeError):
            ti.token = 99  # type: ignore[misc]
