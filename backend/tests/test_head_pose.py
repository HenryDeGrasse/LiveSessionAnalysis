"""Tests for head_pose.py — head pose estimation via cv2.solvePnP."""
from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from app.video_processor.head_pose import (
    HEAD_POSE_LANDMARK_INDICES,
    HeadPoseResult,
    _MODEL_POINTS_3D,
    _rotation_matrix_to_euler_degrees,
    estimate_head_pose,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_landmarks(count: int = 478, default: tuple = (0.5, 0.5, 0.0)):
    """Return a landmark list of *count* points all at *default*."""
    return [default] * count


def _projected_landmarks(
    *,
    pitch_deg: float = 0.0,
    yaw_deg: float = 0.0,
    roll_deg: float = 0.0,
    frame_w: int = 320,
    frame_h: int = 240,
    translation_z: float = 1000.0,
):
    """Project the canonical 3D face model into 2D normalized landmarks."""
    pitch_rad = math.radians(pitch_deg)
    yaw_rad = math.radians(yaw_deg)
    roll_rad = math.radians(roll_deg)

    rot_x = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(pitch_rad), -math.sin(pitch_rad)],
            [0.0, math.sin(pitch_rad), math.cos(pitch_rad)],
        ],
        dtype=np.float64,
    )
    rot_y = np.array(
        [
            [math.cos(yaw_rad), 0.0, math.sin(yaw_rad)],
            [0.0, 1.0, 0.0],
            [-math.sin(yaw_rad), 0.0, math.cos(yaw_rad)],
        ],
        dtype=np.float64,
    )
    rot_z = np.array(
        [
            [math.cos(roll_rad), -math.sin(roll_rad), 0.0],
            [math.sin(roll_rad), math.cos(roll_rad), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    rotation_matrix = rot_z @ rot_y @ rot_x
    rotation_vec, _ = cv2.Rodrigues(rotation_matrix)

    camera_matrix = np.array(
        [
            [float(frame_w), 0.0, frame_w / 2.0],
            [0.0, float(frame_w), frame_h / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)
    translation_vec = np.array([[0.0], [0.0], [translation_z]], dtype=np.float64)

    projected, _ = cv2.projectPoints(
        _MODEL_POINTS_3D,
        rotation_vec,
        translation_vec,
        camera_matrix,
        dist_coeffs,
    )

    landmarks = _make_landmarks()
    for idx, pt in zip(HEAD_POSE_LANDMARK_INDICES, projected.reshape(-1, 2)):
        landmarks[idx] = (float(pt[0] / frame_w), float(pt[1] / frame_h), 0.0)
    return landmarks


# ---------------------------------------------------------------------------
# Unit tests for _rotation_matrix_to_euler_degrees
# ---------------------------------------------------------------------------

def test_identity_rotation_gives_zero_angles():
    R = np.eye(3)
    yaw, pitch, roll = _rotation_matrix_to_euler_degrees(R)
    assert abs(yaw) < 1e-6
    assert abs(pitch) < 1e-6
    assert abs(roll) < 1e-6


def test_y_axis_rotation_maps_to_yaw():
    theta = math.radians(45)
    R = np.array([
        [math.cos(theta), 0.0, math.sin(theta)],
        [0.0, 1.0, 0.0],
        [-math.sin(theta), 0.0, math.cos(theta)],
    ])
    yaw, pitch, roll = _rotation_matrix_to_euler_degrees(R)
    assert abs(yaw - 45.0) < 1.0
    assert abs(pitch) < 1.0
    assert abs(roll) < 1.0


def test_x_axis_rotation_maps_to_pitch():
    theta = math.radians(30)
    R = np.array([
        [1.0, 0.0, 0.0],
        [0.0, math.cos(theta), -math.sin(theta)],
        [0.0, math.sin(theta), math.cos(theta)],
    ])
    yaw, pitch, roll = _rotation_matrix_to_euler_degrees(R)
    assert abs(pitch - 30.0) < 1.0
    assert abs(yaw) < 1.0
    assert abs(roll) < 1.0


def test_z_axis_rotation_maps_to_roll():
    theta = math.radians(20)
    R = np.array([
        [math.cos(theta), -math.sin(theta), 0.0],
        [math.sin(theta), math.cos(theta), 0.0],
        [0.0, 0.0, 1.0],
    ])
    yaw, pitch, roll = _rotation_matrix_to_euler_degrees(R)
    assert abs(roll - 20.0) < 1.0
    assert abs(yaw) < 1.0
    assert abs(pitch) < 1.0


# ---------------------------------------------------------------------------
# Unit tests for estimate_head_pose
# ---------------------------------------------------------------------------

def test_insufficient_landmarks_returns_none():
    """Fewer landmarks than the highest index + 1 should return None."""
    short = _make_landmarks(count=100)
    result = estimate_head_pose(short, frame_width=320, frame_height=240)
    assert result is None


def test_returns_head_pose_result_type():
    """With valid projected landmarks, head pose should be recovered."""
    landmarks = _projected_landmarks()
    result = estimate_head_pose(landmarks, frame_width=320, frame_height=240)
    assert isinstance(result, HeadPoseResult)
    assert isinstance(result.yaw_deg, float)
    assert isinstance(result.pitch_deg, float)
    assert isinstance(result.roll_deg, float)


def test_degenerate_landmarks_does_not_raise():
    """All-same-point landmarks should not raise; may return None."""
    landmarks = _make_landmarks(count=478, default=(0.5, 0.5, 0.0))
    try:
        result = estimate_head_pose(landmarks, frame_width=320, frame_height=240)
        # None is acceptable for degenerate input
        assert result is None or isinstance(result, HeadPoseResult)
    except Exception as exc:
        pytest.fail(f"estimate_head_pose raised unexpectedly: {exc}")


def test_frontal_face_recovers_small_angles():
    landmarks = _projected_landmarks()
    result = estimate_head_pose(landmarks, frame_width=320, frame_height=240)
    assert result is not None
    assert abs(result.yaw_deg) < 0.5
    assert abs(result.pitch_deg) < 0.5
    assert abs(result.roll_deg) < 0.5


def test_known_pose_is_recovered_from_projected_landmarks():
    landmarks = _projected_landmarks(pitch_deg=10.0, yaw_deg=20.0, roll_deg=5.0)
    result = estimate_head_pose(landmarks, frame_width=320, frame_height=240)
    assert result is not None
    assert abs(result.yaw_deg - 20.0) < 1.0
    assert abs(result.pitch_deg - 10.0) < 1.0
    assert abs(result.roll_deg - 5.0) < 1.0


def test_landmark_indices_are_correct():
    """Verify the documented landmark indices are what the module exposes."""
    expected = [1, 199, 33, 263, 61, 291]
    assert HEAD_POSE_LANDMARK_INDICES == expected


def test_non_finite_landmarks_return_none():
    landmarks = _projected_landmarks()
    landmarks[1] = (float("nan"), 0.5, 0.0)
    result = estimate_head_pose(landmarks, frame_width=320, frame_height=240)
    assert result is None


def test_head_pose_result_fields():
    """HeadPoseResult dataclass should expose yaw_deg, pitch_deg, roll_deg."""
    hp = HeadPoseResult(yaw_deg=10.0, pitch_deg=-5.0, roll_deg=2.0)
    assert hp.yaw_deg == 10.0
    assert hp.pitch_deg == -5.0
    assert hp.roll_deg == 2.0
