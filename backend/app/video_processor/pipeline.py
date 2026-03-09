from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .face_detector import FaceDetector, FaceDetectionResult
from .gaze_estimator import estimate_gaze, GazeResult
from .expression_analyzer import analyze_expression, ExpressionResult
from .frame_utils import decode_frame, resize_frame, to_rgb


@dataclass
class FrameProcessingResult:
    """Result from processing a single video frame."""
    face_detected: bool
    gaze: GazeResult | None
    expression: ExpressionResult | None
    decode_ms: float
    facemesh_ms: float
    gaze_ms: float
    expression_ms: float
    total_ms: float


class VideoProcessor:
    """Per-participant video processing pipeline."""

    def __init__(self):
        self._detector = FaceDetector(max_num_faces=1, refine_landmarks=True)

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

        # Decode
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
                gaze_ms=0,
                expression_ms=0,
                total_ms=(time.time() - total_start) * 1000,
            )

        # Resize and convert
        frame = resize_frame(frame)
        rgb = to_rgb(frame)

        # Face detection
        facemesh_start = time.time()
        detection = self._detector.detect(rgb)
        facemesh_ms = (time.time() - facemesh_start) * 1000

        if detection is None:
            return FrameProcessingResult(
                face_detected=False,
                gaze=None,
                expression=None,
                decode_ms=decode_ms,
                facemesh_ms=facemesh_ms,
                gaze_ms=0,
                expression_ms=0,
                total_ms=(time.time() - total_start) * 1000,
            )

        # Gaze estimation
        gaze = None
        gaze_ms = 0.0
        if not skip_gaze:
            gaze_start = time.time()
            gaze = estimate_gaze(detection.landmarks)
            gaze_ms = (time.time() - gaze_start) * 1000

        # Expression analysis
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
            gaze_ms=gaze_ms,
            expression_ms=expression_ms,
            total_ms=(time.time() - total_start) * 1000,
        )

    def close(self):
        self._detector.close()
