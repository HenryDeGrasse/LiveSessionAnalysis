from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ..config import settings
from .face_detector import FaceDetector, FaceDetectionResult
from .gaze_estimator import estimate_gaze, GazeResult
from .head_pose import estimate_head_pose, HeadPoseResult
from .expression_analyzer import analyze_expression, ExpressionResult
from .frame_utils import decode_frame, resize_frame, to_rgb
from .live_gaze_filter import LiveGazeFilter


@dataclass
class FrameProcessingResult:
    """Result from processing a single video frame."""
    face_detected: bool
    gaze: GazeResult | None
    expression: ExpressionResult | None
    decode_ms: float
    facemesh_ms: float
    head_pose_ms: float
    gaze_ms: float
    expression_ms: float
    total_ms: float


class VideoProcessor:
    """Per-participant video processing pipeline."""

    def __init__(self):
        self._detector = FaceDetector(max_num_faces=1, refine_landmarks=True)
        self._gaze_filter = LiveGazeFilter()

    def process_frame(
        self,
        frame_bytes: bytes,
        skip_expression: bool = False,
        skip_gaze: bool = False,
    ) -> FrameProcessingResult:
        """Process a single JPEG frame through the full pipeline.

        Args:
            frame_bytes: JPEG-encoded frame bytes.
            skip_expression: If True, skip expression analysis (degradation level 2).
            skip_gaze: If True, skip gaze estimation too (degradation level 3).

        Returns:
            FrameProcessingResult with all analysis results and timing.
        """
        total_start = time.time()

        decode_start = time.time()
        frame = decode_frame(frame_bytes)
        decode_ms = (time.time() - decode_start) * 1000

        if frame is None:
            return FrameProcessingResult(
                face_detected=False,
                gaze=None,
                expression=None,
                decode_ms=decode_ms,
                facemesh_ms=0,
                head_pose_ms=0,
                gaze_ms=0,
                expression_ms=0,
                total_ms=(time.time() - total_start) * 1000,
            )

        return self._process_decoded_frame(
            frame,
            total_start=total_start,
            decode_ms=decode_ms,
            skip_expression=skip_expression,
            skip_gaze=skip_gaze,
        )

    def process_frame_array(
        self,
        frame: np.ndarray,
        skip_expression: bool = False,
        skip_gaze: bool = False,
    ) -> FrameProcessingResult:
        """Process an already-decoded BGR frame through the full pipeline."""
        total_start = time.time()
        return self._process_decoded_frame(
            frame,
            total_start=total_start,
            decode_ms=0.0,
            skip_expression=skip_expression,
            skip_gaze=skip_gaze,
        )

    def _process_decoded_frame(
        self,
        frame: np.ndarray,
        *,
        total_start: float,
        decode_ms: float,
        skip_expression: bool,
        skip_gaze: bool,
    ) -> FrameProcessingResult:
        frame = resize_frame(frame)
        rgb = to_rgb(frame)

        facemesh_start = time.time()
        detection = self._detector.detect(rgb)
        facemesh_ms = (time.time() - facemesh_start) * 1000

        if detection is None:
            self._gaze_filter.mark_face_missing()
            return FrameProcessingResult(
                face_detected=False,
                gaze=None,
                expression=None,
                decode_ms=decode_ms,
                facemesh_ms=facemesh_ms,
                head_pose_ms=0,
                gaze_ms=0,
                expression_ms=0,
                total_ms=(time.time() - total_start) * 1000,
            )

        head_pose: HeadPoseResult | None = None
        head_pose_ms = 0.0
        gaze: GazeResult | None = None
        gaze_ms = 0.0

        if not skip_gaze:
            # Estimate head pose first so gaze can fuse it
            head_pose_start = time.time()
            frame_height, frame_width = frame.shape[:2]
            raw_head_pose = estimate_head_pose(
                detection.landmarks,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            head_pose = self._gaze_filter.smooth_head_pose(raw_head_pose)
            head_pose_ms = (time.time() - head_pose_start) * 1000

            gaze_start = time.time()
            raw_gaze = estimate_gaze(
                detection.landmarks,
                threshold_degrees=settings.gaze_threshold_degrees,
                head_pose=head_pose,
            )
            gaze = self._gaze_filter.apply(
                raw_gaze,
                threshold_degrees=settings.gaze_threshold_degrees,
            )
            gaze_ms = (time.time() - gaze_start) * 1000

        expression = None
        expression_ms = 0.0
        if not skip_expression and not skip_gaze:
            expr_start = time.time()
            expression = analyze_expression(detection.landmarks)
            expression_ms = (time.time() - expr_start) * 1000

        return FrameProcessingResult(
            face_detected=True,
            gaze=gaze,
            expression=expression,
            decode_ms=decode_ms,
            facemesh_ms=facemesh_ms,
            head_pose_ms=head_pose_ms,
            gaze_ms=gaze_ms,
            expression_ms=expression_ms,
            total_ms=(time.time() - total_start) * 1000,
        )

    def close(self):
        self._detector.close()
