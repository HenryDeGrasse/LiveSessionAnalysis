from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..config import settings


# MediaPipe Face Mesh landmark indices for iris and eye corners
# Left eye (from subject's perspective)
LEFT_IRIS_CENTER = 468
LEFT_EYE_INNER = 133
LEFT_EYE_OUTER = 33

# Right eye
RIGHT_IRIS_CENTER = 473
RIGHT_EYE_INNER = 362
RIGHT_EYE_OUTER = 263


@dataclass
class GazeResult:
    """Result of gaze estimation."""
    on_camera: bool
    left_eye_ratio: float  # 0=outer corner, 0.5=center, 1=inner corner
    right_eye_ratio: float
    horizontal_angle_deg: float
    vertical_angle_deg: float


def estimate_gaze(
    landmarks: list[tuple[float, float, float]],
    threshold_degrees: float | None = None,
) -> GazeResult:
    """Estimate gaze direction from iris landmarks.

    Uses the position of the iris center relative to the eye corners
    to determine gaze direction. When the iris is centered, the person
    is looking approximately at the camera.

    Args:
        landmarks: List of (x, y, z) normalized landmarks from FaceMesh.
        threshold_degrees: Max angle from center to count as "on camera".
            Defaults to settings.gaze_threshold_degrees.

    Returns:
        GazeResult with on_camera flag and angle information.
    """
    if threshold_degrees is None:
        threshold_degrees = settings.gaze_threshold_degrees

    if len(landmarks) < 478:
        # Not enough landmarks (need refined iris landmarks)
        return GazeResult(
            on_camera=False,
            left_eye_ratio=0.5,
            right_eye_ratio=0.5,
            horizontal_angle_deg=0.0,
            vertical_angle_deg=0.0,
        )

    # Left eye iris position relative to eye corners
    left_iris = landmarks[LEFT_IRIS_CENTER]
    left_inner = landmarks[LEFT_EYE_INNER]
    left_outer = landmarks[LEFT_EYE_OUTER]

    left_eye_width = _distance_2d(left_inner, left_outer)
    if left_eye_width < 1e-6:
        left_ratio = 0.5
    else:
        left_iris_from_outer = _distance_2d(left_iris, left_outer)
        left_ratio = left_iris_from_outer / left_eye_width

    # Right eye iris position relative to eye corners
    right_iris = landmarks[RIGHT_IRIS_CENTER]
    right_inner = landmarks[RIGHT_EYE_INNER]
    right_outer = landmarks[RIGHT_EYE_OUTER]

    right_eye_width = _distance_2d(right_inner, right_outer)
    if right_eye_width < 1e-6:
        right_ratio = 0.5
    else:
        right_iris_from_outer = _distance_2d(right_iris, right_outer)
        right_ratio = right_iris_from_outer / right_eye_width

    # Average ratio across both eyes
    avg_horizontal = (left_ratio + right_ratio) / 2.0

    # Vertical: use iris Y relative to upper/lower eyelid landmarks
    # Upper eyelid: 159 (left), 386 (right)
    # Lower eyelid: 145 (left), 374 (right)
    left_upper = landmarks[159]
    left_lower = landmarks[145]
    right_upper = landmarks[386]
    right_lower = landmarks[374]

    left_eye_height = abs(left_upper[1] - left_lower[1])
    right_eye_height = abs(right_upper[1] - right_lower[1])

    if left_eye_height > 1e-6:
        left_v_ratio = (left_iris[1] - left_upper[1]) / left_eye_height
    else:
        left_v_ratio = 0.5

    if right_eye_height > 1e-6:
        right_v_ratio = (right_iris[1] - right_upper[1]) / right_eye_height
    else:
        right_v_ratio = 0.5

    avg_vertical = (left_v_ratio + right_v_ratio) / 2.0

    # Convert ratio deviation from center (0.5) to approximate angle
    # Rough mapping: 0.1 ratio deviation ≈ 15 degrees
    horizontal_angle = (avg_horizontal - 0.5) * 150.0  # degrees
    vertical_angle = (avg_vertical - 0.5) * 150.0

    # Check if within threshold
    on_camera = (
        abs(horizontal_angle) <= threshold_degrees
        and abs(vertical_angle) <= threshold_degrees
    )

    return GazeResult(
        on_camera=on_camera,
        left_eye_ratio=left_ratio,
        right_eye_ratio=right_ratio,
        horizontal_angle_deg=horizontal_angle,
        vertical_angle_deg=vertical_angle,
    )


def _distance_2d(
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
) -> float:
    """2D Euclidean distance between two landmark points (ignoring z)."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
