import pytest
from app.config import settings
from app.video_processor.gaze_estimator import estimate_gaze, GazeResult
from app.video_processor.head_pose import HeadPoseResult


def _make_landmarks(count=478, default=(0.5, 0.5, 0.0)):
    """Create a list of landmarks with default positions."""
    return [default] * count


def _set_eye_landmarks(landmarks, left_iris_x, right_iris_x, iris_y=0.5):
    """Set key eye landmarks for testing gaze.

    Positions iris at specific x positions relative to eye corners.
    Eye corners are at 0.3 (outer) and 0.5 (inner) for left eye,
    and 0.5 (inner) and 0.7 (outer) for right eye.
    """
    # Left eye corners
    landmarks[33] = (0.3, 0.5, 0.0)   # LEFT_EYE_OUTER
    landmarks[133] = (0.5, 0.5, 0.0)  # LEFT_EYE_INNER
    # Left iris
    landmarks[468] = (left_iris_x, iris_y, 0.0)

    # Right eye corners
    landmarks[263] = (0.7, 0.5, 0.0)  # RIGHT_EYE_OUTER
    landmarks[362] = (0.5, 0.5, 0.0)  # RIGHT_EYE_INNER
    # Right iris
    landmarks[473] = (right_iris_x, iris_y, 0.0)

    # Upper/lower eyelids (for vertical gaze)
    landmarks[159] = (0.4, 0.47, 0.0)  # LEFT_EYE_TOP
    landmarks[145] = (0.4, 0.53, 0.0)  # LEFT_LOWER
    landmarks[386] = (0.6, 0.47, 0.0)  # RIGHT_EYE_TOP
    landmarks[374] = (0.6, 0.53, 0.0)  # RIGHT_LOWER

    return landmarks


def test_centered_gaze_is_on_camera():
    """When iris is centered between eye corners, gaze should be on camera."""
    landmarks = _make_landmarks()
    # Center iris: left at 0.4 (midpoint of 0.3-0.5), right at 0.6 (midpoint of 0.5-0.7)
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.4, right_iris_x=0.6)
    result = estimate_gaze(landmarks, threshold_degrees=15.0)
    assert result.on_camera is True
    assert abs(result.horizontal_angle_deg) < 15.0


def test_looking_left_is_off_camera():
    """When both irises are shifted left (low ratio), gaze should be off camera.

    Looking left = both irises near their respective outer corners:
    - Left iris near left outer (0.3): ratio ≈ 0
    - Right iris near right outer (0.7): ratio ≈ 0
    Average ratio ≈ 0, angle = (0 - 0.5) * 150 = -75°, clearly off camera.
    """
    landmarks = _make_landmarks()
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.31, right_iris_x=0.69)
    result = estimate_gaze(landmarks, threshold_degrees=15.0)
    assert result.on_camera is False


def test_looking_right_is_off_camera():
    """When both irises are shifted right (high ratio), gaze should be off camera.

    Looking right = both irises near their respective inner corners:
    - Left iris near left inner (0.5): ratio ≈ 1
    - Right iris near right inner (0.5): ratio ≈ 1
    Average ratio ≈ 1, angle = (1 - 0.5) * 150 = 75°, clearly off camera.
    """
    landmarks = _make_landmarks()
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.49, right_iris_x=0.51)
    result = estimate_gaze(landmarks, threshold_degrees=15.0)
    assert result.on_camera is False


def test_insufficient_landmarks_returns_off_camera():
    """With fewer than 478 landmarks, should return off camera."""
    landmarks = _make_landmarks(count=400)
    result = estimate_gaze(landmarks)
    assert result.on_camera is False


def test_wider_threshold_allows_more():
    """A wider threshold should accept more gaze deviation."""
    landmarks = _make_landmarks()
    # Slightly off-center
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.35, right_iris_x=0.55)
    result_strict = estimate_gaze(landmarks, threshold_degrees=5.0)
    result_wide = estimate_gaze(landmarks, threshold_degrees=45.0)
    # Wide threshold should be more permissive
    assert result_wide.on_camera is True


# ---------------------------------------------------------------------------
# Head-pose fusion tests
# ---------------------------------------------------------------------------

def test_fused_centered_gaze_with_zero_head_pose():
    """Centered iris + zero head pose should remain on camera."""
    landmarks = _make_landmarks()
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.4, right_iris_x=0.6)
    head_pose = HeadPoseResult(yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0)
    result = estimate_gaze(landmarks, threshold_degrees=15.0, head_pose=head_pose)
    assert result.on_camera is True
    assert abs(result.horizontal_angle_deg) < 15.0


def test_large_head_yaw_still_pushes_fusion_off_camera():
    """A large head yaw should still push the fused angle off camera."""
    landmarks = _make_landmarks()
    # Centered iris — iris-only would be on-camera
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.4, right_iris_x=0.6)
    # But head is turned 60° to the right
    head_pose = HeadPoseResult(yaw_deg=60.0, pitch_deg=0.0, roll_deg=0.0)
    result = estimate_gaze(landmarks, threshold_degrees=15.0, head_pose=head_pose)
    assert result.on_camera is False
    expected_h = settings.gaze_head_pose_weight * 60.0 / (
        settings.gaze_iris_weight + settings.gaze_head_pose_weight
    )
    assert result.horizontal_angle_deg == pytest.approx(expected_h, abs=0.01)
    assert result.horizontal_angle_deg > 15.0


def test_head_pose_fusion_blending_math():
    """Verify the numeric blending formula uses the configured weights."""
    landmarks = _make_landmarks()
    # Force iris angle to exactly 0 (perfect centre)
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.4, right_iris_x=0.6)
    iris_result = estimate_gaze(landmarks, threshold_degrees=90.0)
    iris_h = iris_result.horizontal_angle_deg
    iris_v = iris_result.vertical_angle_deg

    head_pose = HeadPoseResult(yaw_deg=30.0, pitch_deg=20.0, roll_deg=0.0)
    fused = estimate_gaze(landmarks, threshold_degrees=90.0, head_pose=head_pose)

    total_weight = settings.gaze_iris_weight + settings.gaze_head_pose_weight
    expected_h = (
        settings.gaze_iris_weight * iris_h + settings.gaze_head_pose_weight * 30.0
    ) / total_weight
    expected_v = (
        settings.gaze_iris_weight * iris_v + settings.gaze_head_pose_weight * 20.0
    ) / total_weight

    assert abs(fused.horizontal_angle_deg - expected_h) < 0.01
    assert abs(fused.vertical_angle_deg - expected_v) < 0.01


def test_no_head_pose_falls_back_to_iris_only():
    """Without head_pose, the result should match the iris-only baseline."""
    landmarks = _make_landmarks()
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.4, right_iris_x=0.6)
    iris_only = estimate_gaze(landmarks, threshold_degrees=15.0)
    with_none = estimate_gaze(landmarks, threshold_degrees=15.0, head_pose=None)
    assert iris_only.horizontal_angle_deg == with_none.horizontal_angle_deg
    assert iris_only.vertical_angle_deg == with_none.vertical_angle_deg
    assert iris_only.on_camera == with_none.on_camera


def test_head_pose_pitch_vertical_fusion():
    """A large downward head pitch (positive) should push vertical angle off camera."""
    landmarks = _make_landmarks()
    landmarks = _set_eye_landmarks(landmarks, left_iris_x=0.4, right_iris_x=0.6)
    head_pose = HeadPoseResult(yaw_deg=0.0, pitch_deg=45.0, roll_deg=0.0)
    result = estimate_gaze(landmarks, threshold_degrees=15.0, head_pose=head_pose)
    assert result.on_camera is False
    assert result.vertical_angle_deg > 15.0
