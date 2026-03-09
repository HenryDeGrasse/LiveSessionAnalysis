from __future__ import annotations

import cv2
import numpy as np

from ..config import settings


def decode_frame(frame_bytes: bytes) -> np.ndarray | None:
    """Decode JPEG bytes to a BGR numpy array."""
    if not frame_bytes:
        return None
    try:
        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame
    except Exception:
        return None


def resize_frame(frame: np.ndarray) -> np.ndarray:
    """Resize frame to configured dimensions for processing."""
    return cv2.resize(
        frame,
        (settings.frame_resize_width, settings.frame_resize_height),
        interpolation=cv2.INTER_AREA,
    )


def to_rgb(frame: np.ndarray) -> np.ndarray:
    """Convert BGR frame to RGB for MediaPipe."""
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
