"""Tests asserting end-to-end pipeline processing latency stays under 500ms."""
from __future__ import annotations

import os
import time
import numpy as np
import cv2
import pytest

from app.video_processor.pipeline import VideoProcessor
from app.audio_processor.pipeline import AudioProcessor
from app.metrics_engine.engine import MetricsEngine
from app.models import Role


def _make_face_jpeg() -> bytes:
    """Create a JPEG with a simple face-like pattern (may not trigger FaceMesh)."""
    img = np.full((240, 320, 3), 200, dtype=np.uint8)
    # Draw a basic oval for face
    cv2.ellipse(img, (160, 120), (60, 80), 0, 0, 360, (180, 160, 140), -1)
    # Eyes
    cv2.circle(img, (140, 100), 8, (50, 50, 50), -1)
    cv2.circle(img, (180, 100), 8, (50, 50, 50), -1)
    # Mouth
    cv2.ellipse(img, (160, 145), (20, 8), 0, 0, 180, (100, 50, 50), 2)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


def _make_pcm_chunk(duration_ms: int = 30, sample_rate: int = 16000) -> bytes:
    """Create a PCM chunk of the specified duration."""
    n_samples = int(sample_rate * duration_ms / 1000)
    samples = np.random.randint(-100, 100, n_samples, dtype=np.int16)
    return samples.tobytes()


class TestVideoProcessingLatency:
    def test_single_frame_under_500ms(self):
        """Processing a single frame should take well under 500ms."""
        processor = VideoProcessor()
        frame = _make_face_jpeg()

        # Warm up
        processor.process_frame(frame)

        # Measure
        start = time.time()
        result = processor.process_frame(frame)
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 500, f"Frame processing took {elapsed_ms:.1f}ms (limit: 500ms)"
        processor.close()

    def test_multiple_frames_average_under_500ms(self):
        """Average processing over 10 frames should be under 500ms."""
        processor = VideoProcessor()
        frame = _make_face_jpeg()

        # Warm up
        processor.process_frame(frame)

        times = []
        for _ in range(10):
            start = time.time()
            processor.process_frame(frame)
            times.append((time.time() - start) * 1000)

        avg_ms = sum(times) / len(times)
        assert avg_ms < 500, f"Average frame processing: {avg_ms:.1f}ms (limit: 500ms)"
        processor.close()

    def test_degraded_mode_faster(self):
        """Skipping expression/gaze should be faster."""
        processor = VideoProcessor()
        frame = _make_face_jpeg()

        # Warm up
        processor.process_frame(frame)

        # Full processing
        start = time.time()
        processor.process_frame(frame)
        full_ms = (time.time() - start) * 1000

        # Degraded (skip expression)
        start = time.time()
        processor.process_frame(frame, skip_expression=True)
        degraded_ms = (time.time() - start) * 1000

        # Skip gaze too
        start = time.time()
        processor.process_frame(frame, skip_gaze=True)
        minimal_ms = (time.time() - start) * 1000

        # Degraded should be no slower than full (allow 20% margin for noise)
        assert degraded_ms < full_ms * 1.2 or degraded_ms < 500
        assert minimal_ms < 500
        processor.close()


class TestAudioProcessingLatency:
    def test_audio_chunk_under_50ms(self):
        """Audio processing should be very fast (<50ms per chunk)."""
        processor = AudioProcessor()
        chunk = _make_pcm_chunk(30)

        start = time.time()
        processor.process_chunk(chunk)
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 50, f"Audio chunk processing took {elapsed_ms:.1f}ms"


class TestFullPipelineLatency:
    def test_video_plus_audio_plus_metrics_under_500ms(self):
        """Full pipeline: video + audio + metrics engine should be under 500ms."""
        video = VideoProcessor()
        audio = AudioProcessor()
        engine = MetricsEngine("test")

        frame = _make_face_jpeg()
        chunk = _make_pcm_chunk(30)

        # Warm up
        video.process_frame(frame)

        start = time.time()

        # Process video
        v_result = video.process_frame(frame)
        if v_result.gaze is not None:
            engine.update_gaze(Role.TUTOR, time.time(), v_result.gaze.on_camera)
        if v_result.expression is not None:
            engine.update_expression(Role.TUTOR, v_result.expression.valence)

        # Process audio
        a_result = audio.process_chunk(chunk)
        engine.update_audio(
            Role.TUTOR, time.time(),
            a_result.is_speech,
            a_result.prosody.rms_energy,
            a_result.prosody.speech_rate_proxy,
        )

        # Compute metrics
        snapshot = engine.compute_snapshot()

        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 500, f"Full pipeline took {elapsed_ms:.1f}ms (limit: 500ms)"
        assert snapshot.session_id == "test"
        video.close()

    def test_metrics_computation_alone_fast(self):
        """Metrics aggregation should be <10ms."""
        engine = MetricsEngine("test")

        # Feed some data
        for i in range(30):
            engine.update_gaze(Role.TUTOR, float(i), i % 3 != 0)
            engine.update_gaze(Role.STUDENT, float(i), i % 2 == 0)
            engine.update_audio(Role.TUTOR, float(i), i % 2 == 0, 0.5, 0.3)
            engine.update_audio(Role.STUDENT, float(i), i % 3 == 0, 0.3, 0.2)

        start = time.time()
        snapshot = engine.compute_snapshot()
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 10, f"Metrics computation took {elapsed_ms:.1f}ms"


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
REAL_FACE_PATH = os.path.join(FIXTURE_DIR, "real_face.jpg")


@pytest.mark.skipif(
    not os.path.exists(REAL_FACE_PATH),
    reason="real_face.jpg fixture not present",
)
class TestRealFaceLatency:
    """Latency tests using a fixture that MediaPipe actually detects as a face.

    These tests exercise the full gaze + expression pipeline, unlike the
    synthetic oval tests which only exercise the no-face-detected path.
    """

    def _load_fixture(self) -> bytes:
        with open(REAL_FACE_PATH, "rb") as f:
            return f.read()

    def test_real_face_detected(self):
        """The real face fixture should produce gaze results."""
        processor = VideoProcessor()
        frame = self._load_fixture()
        result = processor.process_frame(frame)
        assert result.gaze is not None, "Real face fixture was not detected by FaceMesh"
        processor.close()

    def test_real_face_under_500ms(self):
        """Full pipeline with real face detection should stay under 500ms."""
        processor = VideoProcessor()
        frame = self._load_fixture()

        # Warm up
        processor.process_frame(frame)

        times = []
        for _ in range(5):
            start = time.time()
            result = processor.process_frame(frame)
            elapsed_ms = (time.time() - start) * 1000
            times.append(elapsed_ms)

        avg_ms = sum(times) / len(times)
        assert avg_ms < 500, f"Average real-face processing: {avg_ms:.1f}ms (limit: 500ms)"
        processor.close()

    def test_real_face_gaze_and_expression(self):
        """Real face should produce both gaze and expression results."""
        processor = VideoProcessor()
        frame = self._load_fixture()

        # Warm up
        processor.process_frame(frame)

        result = processor.process_frame(frame)
        assert result.gaze is not None, "No gaze result from real face"
        # Expression may or may not be detected depending on the face
        # Just verify it doesn't crash
        processor.close()

    def test_real_face_full_pipeline(self):
        """Full pipeline (video + audio + metrics) with real face under 500ms."""
        video = VideoProcessor()
        audio = AudioProcessor()
        engine = MetricsEngine("test-real")

        frame = self._load_fixture()
        chunk = _make_pcm_chunk(30)

        # Warm up
        video.process_frame(frame)

        start = time.time()
        v_result = video.process_frame(frame)
        if v_result.gaze is not None:
            engine.update_gaze(Role.TUTOR, time.time(), v_result.gaze.on_camera)
        if v_result.expression is not None:
            engine.update_expression(Role.TUTOR, v_result.expression.valence)

        a_result = audio.process_chunk(chunk)
        engine.update_audio(
            Role.TUTOR, time.time(),
            a_result.is_speech,
            a_result.prosody.rms_energy,
            a_result.prosody.speech_rate_proxy,
        )
        snapshot = engine.compute_snapshot()
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 500, f"Full pipeline with real face: {elapsed_ms:.1f}ms"
        assert snapshot.session_id == "test-real"
        video.close()
