from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple


# MediaPipe Face Mesh landmark indices
# Mouth corners
MOUTH_LEFT = 61
MOUTH_RIGHT = 291
# Upper/lower lip
UPPER_LIP = 13
LOWER_LIP = 14
# Eyebrow inner points
LEFT_EYEBROW_INNER = 107
RIGHT_EYEBROW_INNER = 336
# Eye reference (for eyebrow distance normalization)
LEFT_EYE_TOP = 159
RIGHT_EYE_TOP = 386
# Nose tip for face height reference
NOSE_TIP = 1
FOREHEAD = 10


@dataclass
class ExpressionResult:
    """Result of facial expression analysis."""
    valence: float  # 0.0 (negative) to 1.0 (positive)
    smile_ratio: float  # mouth width / height ratio
    eyebrow_raise: float  # normalized eyebrow height


def analyze_expression(
    landmarks: list[tuple[float, float, float]],
) -> ExpressionResult:
    """Analyze facial expression from landmarks for valence proxy.

    This is a simple heuristic based on:
    - Smile ratio: wider mouth with less height = more smile-like
    - Eyebrow raise: higher eyebrows relative to eyes = more engaged/surprised

    Note: This is documented as a weak secondary signal. Audio energy is
    the primary energy metric.

    Args:
        landmarks: List of (x, y, z) normalized landmarks from FaceMesh.

    Returns:
        ExpressionResult with valence score and component metrics.
    """
    if len(landmarks) < 468:
        return ExpressionResult(valence=0.5, smile_ratio=0.0, eyebrow_raise=0.0)

    # Smile ratio: mouth width / mouth height
    mouth_width = _distance_2d(landmarks[MOUTH_LEFT], landmarks[MOUTH_RIGHT])
    mouth_height = _distance_2d(landmarks[UPPER_LIP], landmarks[LOWER_LIP])

    if mouth_height > 1e-6:
        smile_ratio = mouth_width / mouth_height
    else:
        smile_ratio = 0.0

    # Normalize smile ratio: typical range is 2-6
    # Below 2.5 = neutral/frown, above 4 = clear smile
    smile_score = max(0.0, min(1.0, (smile_ratio - 2.5) / 3.0))

    # Eyebrow raise: distance from eyebrow to eye, normalized by face height
    face_height = _distance_2d(landmarks[FOREHEAD], landmarks[NOSE_TIP])
    if face_height < 1e-6:
        eyebrow_raise = 0.0
    else:
        left_brow_dist = abs(landmarks[LEFT_EYEBROW_INNER][1] - landmarks[LEFT_EYE_TOP][1])
        right_brow_dist = abs(landmarks[RIGHT_EYEBROW_INNER][1] - landmarks[RIGHT_EYE_TOP][1])
        avg_brow_dist = (left_brow_dist + right_brow_dist) / 2.0
        eyebrow_raise = avg_brow_dist / face_height

    # Normalize eyebrow raise: typical range is 0.02-0.08
    brow_score = max(0.0, min(1.0, (eyebrow_raise - 0.02) / 0.06))

    # Composite valence: weighted combination
    valence = 0.6 * smile_score + 0.4 * brow_score

    return ExpressionResult(
        valence=valence,
        smile_ratio=smile_ratio,
        eyebrow_raise=eyebrow_raise,
    )


def _distance_2d(
    p1: tuple[float, float, float],
    p2: tuple[float, float, float],
) -> float:
    """2D Euclidean distance between two landmarks."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
