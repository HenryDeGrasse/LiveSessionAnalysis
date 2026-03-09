import json
import time

import jwt
import numpy as np
from livekit import rtc

from app.config import settings
from app.livekit import build_livekit_worker_join_payload, livekit_worker_identity
from app.livekit_worker import (
    TOPIC_METRICS,
    TOPIC_NUDGE,
    bgr_frame_from_video_frame,
    get_active_worker,
    maybe_start_livekit_analytics_worker,
    pcm_bytes_from_audio_frame,
    reset_livekit_analytics_workers,
    stop_livekit_analytics_worker,
)
from app.models import MediaProvider, Role
from app.session_manager import session_manager


class DummyTask:
    def __init__(self):
        self._callbacks = []

    def done(self):
        return False

    def add_done_callback(self, callback):
        self._callbacks.append(callback)


class DummyWorker:
    def __init__(self, session):
        self.session = session
        self.task = DummyTask()

    def start(self):
        return self.task

    def request_stop(self):
        pass


def _enable_livekit(monkeypatch):
    monkeypatch.setattr(settings, "enable_livekit", True)
    monkeypatch.setattr(settings, "enable_livekit_analytics_worker", True)
    monkeypatch.setattr(settings, "livekit_url", "ws://127.0.0.1:7880")
    monkeypatch.setattr(settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(settings, "livekit_api_secret", "secret")


def test_build_livekit_worker_join_payload_marks_hidden_worker(monkeypatch):
    _enable_livekit(monkeypatch)

    response = session_manager.create_session(media_provider=MediaProvider.LIVEKIT)
    room = session_manager.get_session(response.session_id)
    assert room is not None

    payload = build_livekit_worker_join_payload(room)
    claims = jwt.decode(
        payload["token"],
        settings.livekit_api_secret,
        algorithms=["HS256"],
        options={"verify_exp": False, "verify_nbf": False},
    )

    assert payload["url"] == settings.livekit_url
    assert payload["room_name"] == room.livekit_room_name
    assert payload["identity"] == livekit_worker_identity(room.session_id)
    assert claims["sub"] == payload["identity"]
    assert claims["video"]["room"] == room.livekit_room_name
    assert claims["video"]["canPublish"] is False
    assert claims["video"]["canSubscribe"] is True
    assert claims["video"]["canPublishData"] is True
    assert claims["video"]["hidden"] is True
    assert claims["video"]["agent"] is True


def test_maybe_start_livekit_analytics_worker_starts_once(monkeypatch):
    _enable_livekit(monkeypatch)

    import app.livekit_worker as livekit_worker_module

    monkeypatch.setattr(livekit_worker_module, "LiveKitAnalyticsWorker", DummyWorker)

    response = session_manager.create_session(media_provider=MediaProvider.LIVEKIT)
    room = session_manager.get_session(response.session_id)
    assert room is not None

    room.started_at = time.time()
    room.participants[Role.TUTOR].livekit_connected = True
    room.participants[Role.STUDENT].livekit_connected = True

    assert maybe_start_livekit_analytics_worker(room) is True
    assert room.livekit_worker_started_at is not None
    assert maybe_start_livekit_analytics_worker(room) is False

    stop_livekit_analytics_worker(room.session_id)
    reset_livekit_analytics_workers()


def test_pcm_bytes_from_audio_frame_resamples_to_16khz_mono():
    samples_per_channel = 1440  # 30ms at 48kHz
    channel = np.linspace(-3000, 3000, num=samples_per_channel, dtype=np.int16)
    stereo = np.stack([channel, channel], axis=1)
    frame = rtc.AudioFrame(
        data=stereo.tobytes(),
        sample_rate=48000,
        num_channels=2,
        samples_per_channel=samples_per_channel,
    )

    pcm = pcm_bytes_from_audio_frame(frame)
    samples = np.frombuffer(pcm, dtype=np.int16)

    assert len(pcm) == 960  # 30ms at 16kHz mono PCM16
    assert samples.shape == (480,)
    assert samples[0] == channel[0]
    assert abs(int(samples[-1]) - int(channel[-1])) < 32


def test_bgr_frame_from_video_frame_converts_rgb24():
    frame = rtc.VideoFrame(
        2,
        1,
        rtc.VideoBufferType.RGB24,
        bytes([255, 0, 0, 0, 255, 0]),
    )

    bgr = bgr_frame_from_video_frame(frame)

    assert bgr.shape == (1, 2, 3)
    assert bgr[0, 0].tolist() == [0, 0, 255]
    assert bgr[0, 1].tolist() == [0, 255, 0]


def test_topic_constants():
    assert TOPIC_METRICS == "lsa.metrics.v1"
    assert TOPIC_NUDGE == "lsa.nudge.v1"


def test_get_active_worker_returns_none_when_no_worker():
    assert get_active_worker("nonexistent-session") is None


def test_get_active_worker_returns_none_when_worker_has_no_room(monkeypatch):
    _enable_livekit(monkeypatch)
    import app.livekit_worker as lw

    response = session_manager.create_session(media_provider=MediaProvider.LIVEKIT)
    room = session_manager.get_session(response.session_id)
    assert room is not None

    worker = lw.LiveKitAnalyticsWorker(session=room)
    worker.task = DummyTask()
    worker.room = None
    lw._workers[room.session_id] = worker

    assert get_active_worker(room.session_id) is None

    lw._workers.pop(room.session_id, None)


def test_get_active_worker_returns_worker_when_connected(monkeypatch):
    _enable_livekit(monkeypatch)
    import app.livekit_worker as lw

    response = session_manager.create_session(media_provider=MediaProvider.LIVEKIT)
    room = session_manager.get_session(response.session_id)
    assert room is not None

    worker = lw.LiveKitAnalyticsWorker(session=room)
    worker.task = DummyTask()

    class FakeRoom:
        local_participant = None
    worker.room = FakeRoom()
    lw._workers[room.session_id] = worker

    result = get_active_worker(room.session_id)
    assert result is worker

    lw._workers.pop(room.session_id, None)


def test_data_packet_payload_encoding():
    """Verify the JSON encoding used for data packets matches expected format."""
    metrics_data = {"student": {"attention_state": "focused"}, "target_fps": 3}
    payload = json.dumps({"type": "metrics", "data": metrics_data}).encode()
    decoded = json.loads(payload)
    assert decoded["type"] == "metrics"
    assert decoded["data"]["student"]["attention_state"] == "focused"

    nudge_data = {"nudge_type": "engagement_drop", "message": "Check in with student"}
    payload = json.dumps({"type": "nudge", "data": nudge_data}).encode()
    decoded = json.loads(payload)
    assert decoded["type"] == "nudge"
    assert decoded["data"]["nudge_type"] == "engagement_drop"
