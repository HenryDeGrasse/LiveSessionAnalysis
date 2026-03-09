from __future__ import annotations

import mediapipe as mp
import numpy as np
from dataclasses import dataclass


@dataclass
class FaceDetectionResult:
    """Result from face detection with landmarks."""
    landmarks: list[tuple[float, float, float]]  # (x, y, z) normalized coords
    detected: bool = True


class FaceDetector:
    """Wrapper around MediaPipe Face Mesh for per-participant face detection."""

    def __init__(self, max_num_faces: int = 1, refine_landmarks: bool = True):
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=max_num_faces,
            refine_landmarks=refine_landmarks,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def detect(self, rgb_frame: np.ndarray) -> FaceDetectionResult | None:
        """Detect face and return landmarks.

        Args:
            rgb_frame: RGB image as numpy array.

        Returns:
            FaceDetectionResult with landmarks, or None if no face detected.
        """
        results = self._face_mesh.process(rgb_frame)

        if not results.multi_face_landmarks:
            return None

        face = results.multi_face_landmarks[0]
        landmarks = [
            (lm.x, lm.y, lm.z) for lm in face.landmark
        ]

        return FaceDetectionResult(landmarks=landmarks)

    def close(self):
        self._face_mesh.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
