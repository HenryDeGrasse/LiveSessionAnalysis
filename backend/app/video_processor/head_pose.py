"""Head pose estimation using cv2.solvePnP with MediaPipe FaceMesh landmarks.

Uses 6 key landmarks and a canonical 3D face model to estimate yaw, pitch,
and roll angles, providing much more robust gaze direction than iris ratios
alone (particularly for head turns that move the whole face).

Reference 3D model points adapted from:
  Ghoddoosian et al. and common solvePnP tutorials for MediaPipe FaceMesh.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


# MediaPipe FaceMesh landmark indices used for head pose
HEAD_POSE_LANDMARK_INDICES = [
    1,    # Nose tip
    199,  # Chin
    33,   # Left eye outer corner (subject's left)
    263,  # Right eye outer corner (subject's right)
    61,   # Mouth left corner
    291,  # Mouth right corner
]

# Canonical 3D model points (in mm) for the above landmarks.
# Coordinate system: X = right, Y = up, Z = toward camera.
# These values come from established head-pose estimation literature
# (see e.g. Kazemi & Sullivan 2014 and MediaPipe solvePnP examples).
_MODEL_POINTS_3D = np.array(
    [
        (0.0, 0.0, 0.0),        # Nose tip
        (0.0, -330.0, -65.0),   # Chin
        (-225.0, 170.0, -135.0),  # Left eye outer corner
        (225.0, 170.0, -135.0),   # Right eye outer corner
        (-150.0, -150.0, -125.0), # Mouth left corner
        (150.0, -150.0, -125.0),  # Mouth right corner
    ],
    dtype=np.float64,
)


@dataclass
class HeadPoseResult:
    """Estimated head pose angles in degrees.

    The values are derived from the rotation matrix returned by ``solvePnP``
    using OpenCV's camera coordinate system:
      yaw_deg   = rotation around the vertical Y axis
      pitch_deg = rotation around the horizontal X axis
      roll_deg  = rotation around the forward Z axis

    With the image-space conventions used by this pipeline, positive pitch is
    downward on screen, which matches the sign used by the existing vertical
    iris-ratio heuristic.
    """
    yaw_deg: float
    pitch_deg: float
    roll_deg: float


def estimate_head_pose(
    landmarks: list[tuple[float, float, float]],
    frame_width: int,
    frame_height: int,
) -> Optional[HeadPoseResult]:
    """Estimate head pose (yaw/pitch/roll) from MediaPipe FaceMesh landmarks.

    Args:
        landmarks: List of at least 292 (x, y, z) normalised FaceMesh landmarks.
        frame_width: Pixel width of the frame used when running FaceMesh.
        frame_height: Pixel height of the frame used when running FaceMesh.

    Returns:
        HeadPoseResult with yaw/pitch/roll in degrees, or None if estimation
        fails (e.g. insufficient landmarks, non-finite points, or a degenerate
        ``solvePnP`` solution).
    """
    required = max(HEAD_POSE_LANDMARK_INDICES) + 1  # 292
    if len(landmarks) < required or frame_width <= 0 or frame_height <= 0:
        return None

    image_points = []
    for idx in HEAD_POSE_LANDMARK_INDICES:
        x, y, _z = landmarks[idx]
        if not np.isfinite(x) or not np.isfinite(y):
            return None
        image_points.append((x * frame_width, y * frame_height))

    image_points_2d = np.array(image_points, dtype=np.float64)

    # Simple pinhole camera matrix (no lens distortion assumed)
    focal_length = float(frame_width)
    cx, cy = frame_width / 2.0, frame_height / 2.0
    camera_matrix = np.array(
        [
            [focal_length, 0.0, cx],
            [0.0, focal_length, cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    try:
        success, rotation_vec, _translation_vec = cv2.solvePnP(
            _MODEL_POINTS_3D,
            image_points_2d,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
    except cv2.error:
        # solvePnP can raise for degenerate / coplanar point configurations
        return None

    if not success:
        return None

    rotation_matrix, _ = cv2.Rodrigues(rotation_vec)
    yaw_deg, pitch_deg, roll_deg = _rotation_matrix_to_euler_degrees(rotation_matrix)

    return HeadPoseResult(yaw_deg=yaw_deg, pitch_deg=pitch_deg, roll_deg=roll_deg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rotation_matrix_to_euler_degrees(R: np.ndarray) -> tuple[float, float, float]:
    """Convert a rotation matrix into head-pose angles.

    OpenCV's ``RQDecomp3x3`` returns Euler angles in degrees ordered as
    rotations around X, Y, Z. For this module we expose them as the more common
    head-pose tuple ``(yaw, pitch, roll)`` by mapping:
      yaw   = Y-axis rotation
      pitch = X-axis rotation
      roll  = Z-axis rotation

    The canonical 3D model uses a Y-up coordinate system while OpenCV's camera
    frame is Y-down.  When the face is frontal, ``solvePnP`` must include a
    ~180° rotation around the X-axis to bridge this convention gap.
    ``RQDecomp3x3`` decomposes that as pitch ≈ ±180° instead of the expected
    ≈ 0°.  We normalise the pitch into the [-90, +90] range so that a frontal
    face yields pitch ≈ 0° and the sign convention (positive = looking down)
    is preserved.
    """
    angles_deg, *_ = cv2.RQDecomp3x3(R)
    pitch_deg, yaw_deg, roll_deg = angles_deg

    # Normalise pitch: unwrap the 180° offset caused by Y-up → Y-down mismatch.
    # A visible face can never truly pitch beyond ±90°, so this is always safe.
    if pitch_deg < -90.0:
        pitch_deg += 180.0
    elif pitch_deg > 90.0:
        pitch_deg -= 180.0

    return float(yaw_deg), float(pitch_deg), float(roll_deg)
