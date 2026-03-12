from app.video_processor.gaze_estimator import GazeResult
from app.video_processor.head_pose import HeadPoseResult
from app.video_processor.live_gaze_filter import LiveGazeFilter


def _gaze(horizontal_deg: float, vertical_deg: float = 0.0) -> GazeResult:
    return GazeResult(
        on_camera=False,
        left_eye_ratio=0.5,
        right_eye_ratio=0.5,
        horizontal_angle_deg=horizontal_deg,
        vertical_angle_deg=vertical_deg,
    )


def test_head_pose_smoothing_reduces_jump():
    filt = LiveGazeFilter()
    first = filt.smooth_head_pose(HeadPoseResult(yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0))
    second = filt.smooth_head_pose(HeadPoseResult(yaw_deg=30.0, pitch_deg=20.0, roll_deg=0.0))

    assert first is not None
    assert second is not None
    assert 0.0 < second.yaw_deg < 30.0
    assert 0.0 < second.pitch_deg < 20.0


def test_baseline_calibration_recenters_neutral_pose():
    filt = LiveGazeFilter()

    calibrated = None
    for _ in range(8):
        calibrated = filt.apply(_gaze(horizontal_deg=18.0, vertical_deg=-6.0), threshold_degrees=25.0)

    assert calibrated is not None
    assert abs(calibrated.horizontal_angle_deg) < 0.01
    assert abs(calibrated.vertical_angle_deg) < 0.01


def test_baseline_is_not_set_from_large_away_angles():
    filt = LiveGazeFilter()

    for _ in range(12):
        filt.apply(_gaze(horizontal_deg=42.0, vertical_deg=-24.0), threshold_degrees=25.0)

    assert filt.baseline is None


def test_asymmetric_hysteresis_requires_confirmation_to_recover():
    filt = LiveGazeFilter()

    # Establish a baseline and an initial on-camera state.
    for _ in range(8):
        filt.apply(_gaze(horizontal_deg=0.0, vertical_deg=0.0), threshold_degrees=25.0)
    filt.apply(_gaze(horizontal_deg=0.0, vertical_deg=0.0), threshold_degrees=25.0)
    result = filt.apply(_gaze(horizontal_deg=0.0, vertical_deg=0.0), threshold_degrees=25.0)
    assert result.on_camera is True

    # One bad frame drops immediately.
    result = filt.apply(_gaze(horizontal_deg=30.0, vertical_deg=0.0), threshold_degrees=25.0)
    assert result.on_camera is False

    # First recovery frame stays false.
    result = filt.apply(_gaze(horizontal_deg=0.0, vertical_deg=0.0), threshold_degrees=25.0)
    assert result.on_camera is False

    # Second consecutive good frame flips back to on-camera.
    result = filt.apply(_gaze(horizontal_deg=0.0, vertical_deg=0.0), threshold_degrees=25.0)
    assert result.on_camera is True
