from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from ..config import settings
from .gaze_estimator import GazeResult
from .head_pose import HeadPoseResult


@dataclass
class NeutralGazeBaseline:
    horizontal_deg: float
    vertical_deg: float


class LiveGazeFilter:
    """Stateful per-participant filter for live gaze signals.

    Responsibilities:
    - smooth noisy solvePnP head-pose angles with an EMA
    - learn an initial neutral/screen-engaged baseline for each participant
    - apply asymmetric hysteresis so "attention lost" appears immediately while
      recovery requires a little confirmation to avoid flicker
    """

    def __init__(self):
        self._smoothed_head_pose: HeadPoseResult | None = None
        self._baseline: NeutralGazeBaseline | None = None
        self._calibration_h_samples: list[float] = []
        self._calibration_v_samples: list[float] = []
        self._calibration_frames_seen = 0
        self._on_camera_state = False
        self._recovery_streak = 0

    def mark_face_missing(self):
        """Reset short-term gaze state when the face disappears."""
        self._on_camera_state = False
        self._recovery_streak = 0

    @property
    def baseline(self) -> NeutralGazeBaseline | None:
        return self._baseline

    def smooth_head_pose(
        self,
        head_pose: HeadPoseResult | None,
    ) -> HeadPoseResult | None:
        """Apply EMA smoothing to noisy head pose measurements."""
        if head_pose is None:
            return None

        previous = self._smoothed_head_pose
        if previous is None:
            self._smoothed_head_pose = head_pose
            return head_pose

        alpha = settings.gaze_head_pose_ema_alpha
        smoothed = HeadPoseResult(
            yaw_deg=(1.0 - alpha) * previous.yaw_deg + alpha * head_pose.yaw_deg,
            pitch_deg=(1.0 - alpha) * previous.pitch_deg + alpha * head_pose.pitch_deg,
            roll_deg=(1.0 - alpha) * previous.roll_deg + alpha * head_pose.roll_deg,
        )
        self._smoothed_head_pose = smoothed
        return smoothed

    def apply(
        self,
        gaze: GazeResult,
        *,
        threshold_degrees: float | None = None,
    ) -> GazeResult:
        """Apply baseline calibration and asymmetric hysteresis to gaze output."""
        threshold = (
            settings.gaze_threshold_degrees
            if threshold_degrees is None
            else threshold_degrees
        )

        calibrated_h = gaze.horizontal_angle_deg
        calibrated_v = gaze.vertical_angle_deg

        self._maybe_set_baseline(calibrated_h, calibrated_v)
        if self._baseline is not None:
            calibrated_h -= self._baseline.horizontal_deg
            calibrated_v -= self._baseline.vertical_deg

        on_camera = self._apply_hysteresis(
            calibrated_h,
            calibrated_v,
            threshold_degrees=threshold,
        )

        return GazeResult(
            on_camera=on_camera,
            left_eye_ratio=gaze.left_eye_ratio,
            right_eye_ratio=gaze.right_eye_ratio,
            horizontal_angle_deg=calibrated_h,
            vertical_angle_deg=calibrated_v,
        )

    def _maybe_set_baseline(self, horizontal_deg: float, vertical_deg: float):
        if self._baseline is not None:
            return

        self._calibration_frames_seen += 1
        if self._calibration_frames_seen > settings.gaze_baseline_max_calibration_frames:
            return

        if (
            abs(horizontal_deg) > settings.gaze_baseline_max_abs_horizontal_deg
            or abs(vertical_deg) > settings.gaze_baseline_max_abs_vertical_deg
        ):
            return

        self._calibration_h_samples.append(horizontal_deg)
        self._calibration_v_samples.append(vertical_deg)

        if len(self._calibration_h_samples) < settings.gaze_baseline_min_samples:
            return

        self._baseline = NeutralGazeBaseline(
            horizontal_deg=float(median(self._calibration_h_samples)),
            vertical_deg=float(median(self._calibration_v_samples)),
        )

    def _apply_hysteresis(
        self,
        horizontal_deg: float,
        vertical_deg: float,
        *,
        threshold_degrees: float,
    ) -> bool:
        within_exit = (
            abs(horizontal_deg) <= threshold_degrees
            and abs(vertical_deg) <= threshold_degrees
        )

        # Loss should be visible immediately in the demo.
        if self._on_camera_state and not within_exit:
            self._on_camera_state = False
            self._recovery_streak = 0
            return False

        if self._on_camera_state:
            self._recovery_streak = 0
            return True

        enter_threshold = max(
            1.0,
            threshold_degrees - settings.gaze_recovery_threshold_margin_deg,
        )
        within_enter = (
            abs(horizontal_deg) <= enter_threshold
            and abs(vertical_deg) <= enter_threshold
        )
        if not within_enter:
            self._recovery_streak = 0
            return False

        self._recovery_streak += 1
        if self._recovery_streak < settings.gaze_recovery_min_consecutive_frames:
            return False

        self._on_camera_state = True
        self._recovery_streak = 0
        return True
