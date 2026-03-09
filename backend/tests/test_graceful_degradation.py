"""Tests for graceful degradation when video quality is poor or processing is slow."""
from __future__ import annotations

import numpy as np
import cv2
import pytest

from app.video_processor.pipeline import VideoProcessor
from app.video_processor.frame_utils import decode_frame, resize_frame
from app.session_manager import SessionRoom
from app.metrics_engine.engine import MetricsEngine
from app.config import settings


def _make_jpeg(width: int = 320, height: int = 240, color=(128, 128, 128)) -> bytes:
    """Create a JPEG-encoded image of solid color."""
    img = np.full((height, width, 3), color, dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


class TestFrameDecodeGraceful:
    def test_invalid_bytes_returns_none(self):
        result = decode_frame(b"not a jpeg")
        assert result is None

    def test_empty_bytes_returns_none(self):
        result = decode_frame(b"")
        assert result is None

    def test_truncated_jpeg_returns_none(self):
        valid = _make_jpeg()
        result = decode_frame(valid[:10])
        assert result is None

    def test_valid_jpeg_decodes(self):
        result = decode_frame(_make_jpeg())
        assert result is not None
        assert result.shape[0] > 0


class TestVideoProcessorDegradation:
    def test_blank_frame_no_face(self):
        processor = VideoProcessor()
        result = processor.process_frame(_make_jpeg())
        assert not result.face_detected
        assert result.gaze is None
        assert result.expression is None
        processor.close()

    def test_skip_expression_still_works(self):
        processor = VideoProcessor()
        result = processor.process_frame(_make_jpeg(), skip_expression=True)
        assert result.expression is None
        assert result.total_ms >= 0
        processor.close()

    def test_skip_gaze_still_works(self):
        processor = VideoProcessor()
        result = processor.process_frame(_make_jpeg(), skip_gaze=True)
        assert result.gaze is None
        assert result.expression is None
        assert result.total_ms >= 0
        processor.close()

    def test_skip_both_gaze_and_expression(self):
        processor = VideoProcessor()
        result = processor.process_frame(
            _make_jpeg(), skip_expression=True, skip_gaze=True
        )
        assert result.gaze is None
        assert result.expression is None
        processor.close()


class TestDegradationLevels:
    def test_no_degradation_at_low_processing_time(self):
        room = SessionRoom(
            session_id="test", tutor_token="t", student_token="s"
        )
        for _ in range(5):
            room.record_processing_time(50.0)
        level = room.check_degradation()
        assert level == 0
        assert room.current_fps == settings.default_fps

    def test_level1_at_step1_threshold(self):
        room = SessionRoom(
            session_id="test", tutor_token="t", student_token="s"
        )
        for _ in range(5):
            room.record_processing_time(settings.degradation_step1_ms + 10)
        level = room.check_degradation()
        assert level == 1
        assert room.current_fps == 2

    def test_level2_at_step2_threshold(self):
        room = SessionRoom(
            session_id="test", tutor_token="t", student_token="s"
        )
        for _ in range(5):
            room.record_processing_time(settings.degradation_step2_ms + 10)
        level = room.check_degradation()
        assert level == 2
        assert room.current_fps == settings.min_fps

    def test_level3_at_step3_threshold(self):
        room = SessionRoom(
            session_id="test", tutor_token="t", student_token="s"
        )
        for _ in range(5):
            room.record_processing_time(settings.degradation_step3_ms + 10)
        level = room.check_degradation()
        assert level == 3
        assert room.current_fps == settings.min_fps

    def test_recovery_after_fast_processing(self):
        room = SessionRoom(
            session_id="test", tutor_token="t", student_token="s"
        )
        # Trigger degradation
        for _ in range(5):
            room.record_processing_time(400.0)
        room.check_degradation()
        assert room.degradation_level > 0

        # Recovery
        for _ in range(5):
            room.record_processing_time(50.0)
        level = room.check_degradation()
        assert level == 0
        assert room.current_fps == settings.default_fps

    def test_degradation_events_counted(self):
        room = SessionRoom(
            session_id="test", tutor_token="t", student_token="s"
        )
        # Go up
        for _ in range(5):
            room.record_processing_time(400.0)
        room.check_degradation()
        # Go down
        for _ in range(5):
            room.record_processing_time(50.0)
        room.check_degradation()
        assert room.degradation_events == 2  # up + down


class TestMetricsEngineWithMissingData:
    def test_snapshot_without_any_data(self):
        engine = MetricsEngine("test")
        snapshot = engine.compute_snapshot()
        assert snapshot.session_id == "test"
        assert snapshot.tutor.eye_contact_score == 0.0
        assert snapshot.student.eye_contact_score == 0.0

    def test_snapshot_with_only_audio(self):
        engine = MetricsEngine("test")
        from app.models import Role
        engine.update_audio(Role.TUTOR, 1.0, True, 0.5, 0.3)
        engine.update_audio(Role.STUDENT, 1.0, False, 0.1, 0.0)
        snapshot = engine.compute_snapshot()
        assert snapshot.tutor.is_speaking is True
        assert snapshot.student.is_speaking is False
        # Eye contact should be 0 since no gaze data
        assert snapshot.tutor.eye_contact_score == 0.0

    def test_degraded_flag_propagated(self):
        engine = MetricsEngine("test")
        snapshot = engine.compute_snapshot(degraded=True, gaze_unavailable=True)
        assert snapshot.degraded is True
        assert snapshot.gaze_unavailable is True

    def test_processing_ms_passthrough(self):
        engine = MetricsEngine("test")
        snapshot = engine.compute_snapshot(processing_ms=123.4)
        assert snapshot.server_processing_ms == 123.4
