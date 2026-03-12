from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

from ..config import settings

AttentionState = Literal[
    "FACE_MISSING",
    "LOW_CONFIDENCE",
    "CAMERA_FACING",
    "SCREEN_ENGAGED",
    "DOWN_ENGAGED",
    "OFF_TASK_AWAY",
]


@dataclass
class VisualObservation:
    timestamp: float
    face_detected: bool
    on_camera: bool | None = None
    horizontal_angle_deg: float | None = None
    vertical_angle_deg: float | None = None


class AttentionStateTracker:
    """Classify recent visual attention into tutoring-friendly states.

    The goal is not perfect gaze semantics; it is a more useful live categorization
    than a raw eye-contact percentage:
    - FACE_MISSING: no usable face in most recent frames
    - LOW_CONFIDENCE: face is present but we lack enough gaze evidence
    - CAMERA_FACING: directly engaged with the camera
    - SCREEN_ENGAGED: looking near the screen/camera region
    - DOWN_ENGAGED: likely looking down at notes/work while still present
    - OFF_TASK_AWAY: looking noticeably away from the work/camera area
    """

    def __init__(
        self,
        window_seconds: float | None = None,
        min_samples: int | None = None,
    ):
        self._window = window_seconds or settings.attention_state_window_seconds
        self._min_samples = min_samples or settings.attention_state_min_samples
        self._observations: deque[VisualObservation] = deque()
        # Time-in-state tracking
        self._current_state: AttentionState = "LOW_CONFIDENCE"
        self._state_entered_at: float | None = None

    def update(
        self,
        timestamp: float,
        *,
        face_detected: bool,
        on_camera: bool | None = None,
        horizontal_angle_deg: float | None = None,
        vertical_angle_deg: float | None = None,
    ):
        self._observations.append(
            VisualObservation(
                timestamp=timestamp,
                face_detected=face_detected,
                on_camera=on_camera,
                horizontal_angle_deg=horizontal_angle_deg,
                vertical_angle_deg=vertical_angle_deg,
            )
        )
        self._prune(timestamp)

    def _prune(self, now: float):
        cutoff = now - self._window
        while self._observations and self._observations[0].timestamp < cutoff:
            self._observations.popleft()

    def face_presence_score(self, now: float | None = None) -> float:
        _, _, face_presence, _ = self._classify(now)
        return face_presence

    def confidence(self, now: float | None = None) -> float:
        _, confidence, _, _ = self._classify(now)
        return confidence

    def state(self, now: float | None = None) -> AttentionState:
        state, _, _, _ = self._classify(now)
        self._track_state_transition(state, now)
        return state

    def time_in_current_state(self, now: float | None = None) -> float:
        """Seconds the tracker has been in its current classified state."""
        state = self.state(now)  # also updates tracking
        if self._state_entered_at is None:
            return 0.0
        effective_now = now if now is not None else (
            self._observations[-1].timestamp if self._observations else 0.0
        )
        return max(0.0, effective_now - self._state_entered_at)

    def _track_state_transition(self, new_state: AttentionState, now: float | None):
        if new_state != self._current_state or self._state_entered_at is None:
            if new_state != self._current_state:
                self._current_state = new_state
            if now is not None:
                self._state_entered_at = now
            elif self._observations:
                self._state_entered_at = self._observations[-1].timestamp
            else:
                self._state_entered_at = None

    def visual_attention_score(self, now: float | None = None) -> float:
        _, _, _, score = self._classify(now)
        return score

    def instant_state(self, now: float | None = None) -> AttentionState:
        state, _, _, _ = self._classify_instant(now)
        return state

    def instant_confidence(self, now: float | None = None) -> float:
        _, confidence, _, _ = self._classify_instant(now)
        return confidence

    def instant_visual_attention_score(self, now: float | None = None) -> float:
        _, _, _, score = self._classify_instant(now)
        return score

    def _latest_observation(self, now: float | None = None) -> VisualObservation | None:
        if not self._observations:
            return None
        effective_now = now if now is not None else self._observations[-1].timestamp
        self._prune(effective_now)
        if not self._observations:
            return None
        return self._observations[-1]

    def _classify_instant(
        self, now: float | None = None
    ) -> tuple[AttentionState, float, float, float]:
        latest = self._latest_observation(now)
        if latest is None:
            return "LOW_CONFIDENCE", 0.0, 0.0, 0.5
        if not latest.face_detected:
            return "FACE_MISSING", 1.0, 0.0, 0.1
        if (
            latest.on_camera is None
            or latest.horizontal_angle_deg is None
            or latest.vertical_angle_deg is None
        ):
            return "LOW_CONFIDENCE", 0.35, 1.0, 0.5

        return _classify_angles(
            on_camera=latest.on_camera,
            horizontal_angle_deg=latest.horizontal_angle_deg,
            vertical_angle_deg=latest.vertical_angle_deg,
            face_presence=1.0,
        )

    def _classify(
        self, now: float | None = None
    ) -> tuple[AttentionState, float, float, float]:
        if not self._observations:
            return "LOW_CONFIDENCE", 0.0, 0.0, 0.5

        if now is None:
            now = self._observations[-1].timestamp
        self._prune(now)

        observations = list(self._observations)
        if not observations:
            return "LOW_CONFIDENCE", 0.0, 0.0, 0.5

        total = len(observations)
        face_present = [obs for obs in observations if obs.face_detected]
        face_presence = len(face_present) / total if total else 0.0

        if total < self._min_samples:
            confidence = min(0.49, total / max(1, self._min_samples))
            return "LOW_CONFIDENCE", confidence, face_presence, 0.5

        if face_presence < settings.attention_state_face_missing_ratio_threshold:
            confidence = min(1.0, 0.6 + (1.0 - face_presence) * 0.4)
            return "FACE_MISSING", confidence, face_presence, 0.1

        gaze_present = [
            obs
            for obs in face_present
            if obs.on_camera is not None
            and obs.horizontal_angle_deg is not None
            and obs.vertical_angle_deg is not None
        ]
        gaze_coverage = len(gaze_present) / len(face_present) if face_present else 0.0

        if (
            len(gaze_present) < settings.attention_state_min_gaze_samples
            or gaze_coverage < settings.attention_state_min_gaze_coverage
        ):
            confidence = max(0.25, min(0.7, gaze_coverage))
            return "LOW_CONFIDENCE", confidence, face_presence, 0.5

        # Exponential recency weights: more recent observations within the window
        # carry more weight, making state transitions ~1-2s faster.
        _RECENCY_ALPHA = 2.0
        if len(gaze_present) > 1:
            t_oldest = gaze_present[0].timestamp
            t_newest = gaze_present[-1].timestamp
            span = t_newest - t_oldest
            if span > 0.0:
                weights = [
                    math.exp(_RECENCY_ALPHA * (obs.timestamp - t_oldest) / span)
                    for obs in gaze_present
                ]
            else:
                weights = [1.0] * len(gaze_present)
        else:
            weights = [1.0] * len(gaze_present)
        total_weight = sum(weights)

        on_camera_ratio = (
            sum(w for obs, w in zip(gaze_present, weights) if obs.on_camera)
            / total_weight
        )
        avg_h = (
            sum((obs.horizontal_angle_deg or 0.0) * w for obs, w in zip(gaze_present, weights))
            / total_weight
        )
        avg_v = (
            sum((obs.vertical_angle_deg or 0.0) * w for obs, w in zip(gaze_present, weights))
            / total_weight
        )
        abs_h = abs(avg_h)
        abs_v = abs(avg_v)

        return _classify_angles(
            on_camera=(
                on_camera_ratio >= settings.attention_state_camera_facing_ratio_threshold
            ),
            horizontal_angle_deg=avg_h,
            vertical_angle_deg=avg_v,
            face_presence=face_presence,
        )


def _classify_angles(
    *,
    on_camera: bool,
    horizontal_angle_deg: float,
    vertical_angle_deg: float,
    face_presence: float,
) -> tuple[AttentionState, float, float, float]:
    abs_h = abs(horizontal_angle_deg)
    abs_v = abs(vertical_angle_deg)

    if on_camera:
        confidence = min(1.0, 0.55 + 0.45 * face_presence)
        return "CAMERA_FACING", confidence, face_presence, 1.0

    if (
        vertical_angle_deg >= settings.attention_state_down_vertical_min_deg
        and vertical_angle_deg <= settings.attention_state_down_vertical_max_deg
        and abs_h <= settings.attention_state_screen_horizontal_max_deg
    ):
        depth = (
            vertical_angle_deg - settings.attention_state_down_vertical_min_deg
        ) / max(
            1.0,
            settings.attention_state_down_vertical_max_deg
            - settings.attention_state_down_vertical_min_deg,
        )
        confidence = min(1.0, 0.55 + 0.25 * face_presence + 0.2 * min(1.0, depth))
        return "DOWN_ENGAGED", confidence, face_presence, 0.72

    if (
        abs_h <= settings.attention_state_screen_horizontal_max_deg
        and abs_v <= settings.attention_state_screen_vertical_max_deg
    ):
        horizontal_fit = 1.0 - (
            abs_h / max(1.0, settings.attention_state_screen_horizontal_max_deg)
        )
        vertical_fit = 1.0 - (
            abs_v / max(1.0, settings.attention_state_screen_vertical_max_deg)
        )
        confidence = min(
            1.0,
            0.45 + 0.25 * face_presence + 0.15 * horizontal_fit + 0.15 * vertical_fit,
        )
        return "SCREEN_ENGAGED", confidence, face_presence, 0.85

    away_strength = max(
        abs_h / max(1.0, settings.attention_state_off_task_horizontal_min_deg),
        (-vertical_angle_deg) / max(1.0, settings.attention_state_off_task_up_vertical_min_deg),
        vertical_angle_deg / max(1.0, settings.attention_state_off_task_down_vertical_min_deg),
    )
    confidence = min(1.0, 0.55 + 0.2 * face_presence + 0.25 * min(1.0, away_strength))
    return "OFF_TASK_AWAY", confidence, face_presence, 0.2
