#!/usr/bin/env python3
"""Per-frame gaze & attention debug harness.

Processes test videos frame-by-frame through the full VideoProcessor pipeline
and prints detailed per-frame diagnostics: raw iris ratios, head-pose angles,
fused gaze angles, on_camera decisions, and attention-state transitions.

Designed for rapid iteration: change thresholds, re-run, compare.

Usage:
    cd backend && uv run --python 3.11 --with-requirements requirements.txt \
        python ../scripts/gaze_debug_harness.py

    # Single video:
    cd backend && uv run --python 3.11 --with-requirements requirements.txt \
        python ../scripts/gaze_debug_harness.py --video tests/test_looking_at_screen.mp4.mp4

    # With threshold overrides:
    cd backend && uv run --python 3.11 --with-requirements requirements.txt \
        python ../scripts/gaze_debug_harness.py --gaze-threshold 25 --attn-window 3.0

    # Export CSV for spreadsheet analysis:
    cd backend && uv run --python 3.11 --with-requirements requirements.txt \
        python ../scripts/gaze_debug_harness.py --csv results.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Ensure backend is importable
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.video_processor.face_detector import FaceDetector
from app.video_processor.gaze_estimator import (
    estimate_gaze,
    LEFT_IRIS_CENTER,
    LEFT_EYE_INNER,
    LEFT_EYE_OUTER,
    RIGHT_IRIS_CENTER,
    RIGHT_EYE_INNER,
    RIGHT_EYE_OUTER,
    _distance_2d,
)
from app.video_processor.head_pose import estimate_head_pose
from app.video_processor.frame_utils import resize_frame, to_rgb
from app.video_processor.expression_analyzer import analyze_expression
from app.video_processor.live_gaze_filter import LiveGazeFilter
from app.metrics_engine.attention_state import AttentionStateTracker
from app.config import settings

# ── Default test videos ──────────────────────────────────────

DEFAULT_VIDEOS_DIR = Path(__file__).resolve().parent.parent / "backend" / "tests"
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

# Expected behavior labels for display
VIDEO_EXPECTATIONS = {
    "test_looking_at_screen": "SHOULD BE: on_camera / CAMERA_FACING or SCREEN_ENGAGED",
    "test_looking_at_screen.mp4": "SHOULD BE: on_camera / CAMERA_FACING or SCREEN_ENGAGED",
    "test_looking_away": "SHOULD BE: off_camera / OFF_TASK_AWAY or FACE_MISSING",
    "test_mixed": "SHOULD BE: alternating on/off camera",
    "test_natural_tutoring": "SHOULD BE: mostly SCREEN_ENGAGED with brief look-aways",
}

SAMPLE_FPS = 5  # Higher than production (3) for finer granularity


# ── Data structures ──────────────────────────────────────────

@dataclass
class FrameDiagnostic:
    """Full diagnostic for a single processed frame."""
    frame_idx: int
    timestamp_s: float
    face_detected: bool
    # Raw iris ratios (before angle conversion)
    left_iris_ratio: float = 0.0
    right_iris_ratio: float = 0.0
    avg_iris_h_ratio: float = 0.0
    avg_iris_v_ratio: float = 0.0
    # Iris-only angles (before head-pose fusion)
    iris_h_angle_deg: float = 0.0
    iris_v_angle_deg: float = 0.0
    # Head pose
    head_yaw_deg: float = 0.0
    head_pitch_deg: float = 0.0
    head_roll_deg: float = 0.0
    head_pose_available: bool = False
    # Fused gaze output
    fused_h_angle_deg: float = 0.0
    fused_v_angle_deg: float = 0.0
    on_camera: bool = False
    # Attention state
    attention_state: str = ""
    attention_confidence: float = 0.0
    face_presence_score: float = 0.0
    visual_attention_score: float = 0.0
    # Timing
    processing_ms: float = 0.0


@dataclass
class VideoResult:
    """Aggregated result for one video."""
    video_name: str
    expectation: str
    total_frames: int
    face_detected_count: int
    on_camera_count: int
    face_detected_pct: float
    on_camera_pct: float
    attention_state_counts: dict[str, int] = field(default_factory=dict)
    frames: list[FrameDiagnostic] = field(default_factory=list)
    avg_processing_ms: float = 0.0


# ── Core processing ──────────────────────────────────────────

def compute_iris_ratios(
    landmarks: list[tuple[float, float, float]],
) -> tuple[float, float, float, float, float, float]:
    """Extract raw iris ratios from landmarks (same logic as gaze_estimator but exposed).

    Returns:
        (left_ratio, right_ratio, avg_h, avg_v, iris_h_angle, iris_v_angle)
    """
    if len(landmarks) < 478:
        return 0.5, 0.5, 0.5, 0.5, 0.0, 0.0

    # Horizontal
    left_iris = landmarks[LEFT_IRIS_CENTER]
    left_inner = landmarks[LEFT_EYE_INNER]
    left_outer = landmarks[LEFT_EYE_OUTER]
    left_eye_width = _distance_2d(left_inner, left_outer)
    left_ratio = (_distance_2d(left_iris, left_outer) / left_eye_width) if left_eye_width > 1e-6 else 0.5

    right_iris = landmarks[RIGHT_IRIS_CENTER]
    right_inner = landmarks[RIGHT_EYE_INNER]
    right_outer = landmarks[RIGHT_EYE_OUTER]
    right_eye_width = _distance_2d(right_inner, right_outer)
    right_ratio = (_distance_2d(right_iris, right_outer) / right_eye_width) if right_eye_width > 1e-6 else 0.5

    avg_h = (left_ratio + right_ratio) / 2.0

    # Vertical
    left_upper = landmarks[159]
    left_lower = landmarks[145]
    right_upper = landmarks[386]
    right_lower = landmarks[374]
    left_eye_height = abs(left_upper[1] - left_lower[1])
    right_eye_height = abs(right_upper[1] - right_lower[1])
    left_v = ((left_iris[1] - left_upper[1]) / left_eye_height) if left_eye_height > 1e-6 else 0.5
    right_v = ((right_iris[1] - right_upper[1]) / right_eye_height) if right_eye_height > 1e-6 else 0.5
    avg_v = (left_v + right_v) / 2.0

    iris_h_angle = (avg_h - 0.5) * 150.0
    iris_v_angle = (avg_v - 0.5) * 150.0

    return left_ratio, right_ratio, avg_h, avg_v, iris_h_angle, iris_v_angle


def process_video(
    video_path: Path,
    *,
    sample_fps: int = SAMPLE_FPS,
    gaze_threshold: Optional[float] = None,
    attn_window: Optional[float] = None,
    attn_min_samples: Optional[int] = None,
) -> VideoResult:
    """Process a video file and return per-frame diagnostics."""
    stem = video_path.stem
    # Handle double extension like test_looking_at_screen.mp4.mp4
    if stem.endswith(".mp4"):
        stem = stem[:-4]
    expectation = VIDEO_EXPECTATIONS.get(stem, "No expectation defined")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if video_fps <= 0:
        video_fps = 30.0
    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_s = total_video_frames / video_fps if video_fps > 0 else 0

    frame_interval = max(1, int(round(video_fps / sample_fps)))

    detector = FaceDetector(max_num_faces=1, refine_landmarks=True)
    gaze_filter = LiveGazeFilter()
    attn_tracker = AttentionStateTracker(
        window_seconds=attn_window,
        min_samples=attn_min_samples,
    )

    frames: list[FrameDiagnostic] = []
    frame_idx = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval != 0:
                frame_idx += 1
                continue

            timestamp_s = frame_idx / video_fps
            start_t = time.time()

            # Resize and detect
            resized = resize_frame(frame)
            rgb = to_rgb(resized)
            detection = detector.detect(rgb)

            diag = FrameDiagnostic(
                frame_idx=frame_idx,
                timestamp_s=timestamp_s,
                face_detected=detection is not None,
            )

            if detection is not None:
                landmarks = detection.landmarks

                # Raw iris ratios
                (lr, rr, avg_h, avg_v,
                 iris_h, iris_v) = compute_iris_ratios(landmarks)
                diag.left_iris_ratio = lr
                diag.right_iris_ratio = rr
                diag.avg_iris_h_ratio = avg_h
                diag.avg_iris_v_ratio = avg_v
                diag.iris_h_angle_deg = iris_h
                diag.iris_v_angle_deg = iris_v

                # Head pose (raw for diagnostics, smoothed for fusion)
                h, w = resized.shape[:2]
                raw_head_pose = estimate_head_pose(landmarks, w, h)
                if raw_head_pose is not None:
                    diag.head_pose_available = True
                    diag.head_yaw_deg = raw_head_pose.yaw_deg
                    diag.head_pitch_deg = raw_head_pose.pitch_deg
                    diag.head_roll_deg = raw_head_pose.roll_deg
                smoothed_head_pose = gaze_filter.smooth_head_pose(raw_head_pose)

                # Fused + filtered gaze (matches production pipeline)
                raw_gaze = estimate_gaze(
                    landmarks,
                    threshold_degrees=gaze_threshold,
                    head_pose=smoothed_head_pose,
                )
                gaze = gaze_filter.apply(raw_gaze, threshold_degrees=gaze_threshold)
                diag.fused_h_angle_deg = gaze.horizontal_angle_deg
                diag.fused_v_angle_deg = gaze.vertical_angle_deg
                diag.on_camera = gaze.on_camera

                # Update attention state tracker
                attn_tracker.update(
                    timestamp_s,
                    face_detected=True,
                    on_camera=gaze.on_camera,
                    horizontal_angle_deg=gaze.horizontal_angle_deg,
                    vertical_angle_deg=gaze.vertical_angle_deg,
                )
            else:
                gaze_filter.mark_face_missing()
                attn_tracker.update(
                    timestamp_s,
                    face_detected=False,
                )

            state = attn_tracker.state(timestamp_s)
            diag.attention_state = state
            diag.attention_confidence = attn_tracker.confidence(timestamp_s)
            diag.face_presence_score = attn_tracker.face_presence_score(timestamp_s)
            diag.visual_attention_score = attn_tracker.visual_attention_score(timestamp_s)
            diag.processing_ms = (time.time() - start_t) * 1000

            frames.append(diag)
            frame_idx += 1

    finally:
        cap.release()
        detector.close()

    total = len(frames)
    face_count = sum(1 for f in frames if f.face_detected)
    on_cam_count = sum(1 for f in frames if f.on_camera)

    state_counts: dict[str, int] = {}
    for f in frames:
        state_counts[f.attention_state] = state_counts.get(f.attention_state, 0) + 1

    avg_ms = (sum(f.processing_ms for f in frames) / total) if total > 0 else 0.0

    return VideoResult(
        video_name=video_path.name,
        expectation=expectation,
        total_frames=total,
        face_detected_count=face_count,
        on_camera_count=on_cam_count,
        face_detected_pct=(face_count / total * 100) if total > 0 else 0,
        on_camera_pct=(on_cam_count / total * 100) if total > 0 else 0,
        attention_state_counts=state_counts,
        frames=frames,
        avg_processing_ms=avg_ms,
    )


# ── Display helpers ──────────────────────────────────────────

# ANSI colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

STATE_COLORS = {
    "CAMERA_FACING": GREEN,
    "SCREEN_ENGAGED": CYAN,
    "DOWN_ENGAGED": YELLOW,
    "OFF_TASK_AWAY": RED,
    "FACE_MISSING": RED,
    "LOW_CONFIDENCE": DIM,
}


def color_state(state: str) -> str:
    c = STATE_COLORS.get(state, "")
    return f"{c}{state}{RESET}"


def color_bool(val: bool, true_color=GREEN, false_color=RED) -> str:
    if val:
        return f"{true_color}True{RESET}"
    return f"{false_color}False{RESET}"


def print_frame_table(frames: list[FrameDiagnostic], compact: bool = False):
    """Print a per-frame diagnostic table to stdout."""
    if compact:
        print(f"  {'Time':>6s}  {'Face':>5s}  {'OnCam':>5s}  "
              f"{'IrisH':>7s}  {'IrisV':>7s}  "
              f"{'HeadY':>7s}  {'HeadP':>7s}  "
              f"{'FuseH':>7s}  {'FuseV':>7s}  "
              f"{'Attention State':>20s}  {'Conf':>5s}")
        print(f"  {'─'*6}  {'─'*5}  {'─'*5}  "
              f"{'─'*7}  {'─'*7}  "
              f"{'─'*7}  {'─'*7}  "
              f"{'─'*7}  {'─'*7}  "
              f"{'─'*20}  {'─'*5}")
    else:
        print(f"  {'Frame':>6s}  {'Time':>6s}  {'Face':>5s}  {'OnCam':>5s}  "
              f"{'L_Iris':>7s}  {'R_Iris':>7s}  {'AvgH':>7s}  {'AvgV':>7s}  "
              f"{'IrisH°':>7s}  {'IrisV°':>7s}  "
              f"{'HeadY°':>7s}  {'HeadP°':>7s}  {'HeadR°':>7s}  "
              f"{'FuseH°':>7s}  {'FuseV°':>7s}  "
              f"{'Attention State':>20s}  {'Conf':>5s}  {'VisAttn':>7s}  {'ms':>6s}")
        print(f"  {'─'*6}  {'─'*6}  {'─'*5}  {'─'*5}  "
              f"{'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  "
              f"{'─'*7}  {'─'*7}  "
              f"{'─'*7}  {'─'*7}  {'─'*7}  "
              f"{'─'*7}  {'─'*7}  "
              f"{'─'*20}  {'─'*5}  {'─'*7}  {'─'*6}")

    for f in frames:
        state_str = color_state(f.attention_state)
        on_cam_str = color_bool(f.on_camera)
        face_str = color_bool(f.face_detected)

        if compact:
            print(f"  {f.timestamp_s:6.2f}  {face_str:>14s}  {on_cam_str:>14s}  "
                  f"{f.iris_h_angle_deg:+7.1f}  {f.iris_v_angle_deg:+7.1f}  "
                  f"{f.head_yaw_deg:+7.1f}  {f.head_pitch_deg:+7.1f}  "
                  f"{f.fused_h_angle_deg:+7.1f}  {f.fused_v_angle_deg:+7.1f}  "
                  f"{state_str:>29s}  {f.attention_confidence:5.2f}")
        else:
            print(f"  {f.frame_idx:6d}  {f.timestamp_s:6.2f}  {face_str:>14s}  {on_cam_str:>14s}  "
                  f"{f.left_iris_ratio:7.3f}  {f.right_iris_ratio:7.3f}  "
                  f"{f.avg_iris_h_ratio:7.3f}  {f.avg_iris_v_ratio:7.3f}  "
                  f"{f.iris_h_angle_deg:+7.1f}  {f.iris_v_angle_deg:+7.1f}  "
                  f"{f.head_yaw_deg:+7.1f}  {f.head_pitch_deg:+7.1f}  {f.head_roll_deg:+7.1f}  "
                  f"{f.fused_h_angle_deg:+7.1f}  {f.fused_v_angle_deg:+7.1f}  "
                  f"{state_str:>29s}  {f.attention_confidence:5.2f}  "
                  f"{f.visual_attention_score:7.2f}  {f.processing_ms:6.1f}")


def print_summary(result: VideoResult, threshold_degrees: float):
    """Print a summary block for one video."""
    print()
    print(f"{BOLD}{'═' * 90}{RESET}")
    print(f"{BOLD}  {result.video_name}{RESET}")
    print(f"  {YELLOW}{result.expectation}{RESET}")
    print(f"{'─' * 90}")
    print(f"  Frames processed:     {result.total_frames}")
    print(f"  Face detected:        {result.face_detected_count}/{result.total_frames} "
          f"({result.face_detected_pct:.1f}%)")
    print(f"  On camera (gaze):     {result.on_camera_count}/{result.total_frames} "
          f"({result.on_camera_pct:.1f}%)")
    print(f"  Gaze threshold:       ±{threshold_degrees:.1f}°")
    print(f"  Avg processing:       {result.avg_processing_ms:.1f} ms/frame")
    print()
    print(f"  Attention state distribution:")
    for state, count in sorted(result.attention_state_counts.items()):
        pct = count / result.total_frames * 100 if result.total_frames > 0 else 0
        bar_len = int(pct / 2)
        bar = "█" * bar_len
        c = STATE_COLORS.get(state, "")
        print(f"    {c}{state:<20s}{RESET}  {count:4d}  ({pct:5.1f}%)  {c}{bar}{RESET}")
    print()


def print_angle_histogram(frames: list[FrameDiagnostic], threshold_degrees: float):
    """Print a text histogram of fused horizontal angles to visualize distribution."""
    angles = [f.fused_h_angle_deg for f in frames if f.face_detected]
    if not angles:
        return

    print(f"  Fused horizontal angle distribution (threshold ±{threshold_degrees:.0f}°):")
    bucket_size = 5
    min_a = int(min(angles) // bucket_size * bucket_size) - bucket_size
    max_a = int(max(angles) // bucket_size * bucket_size) + bucket_size * 2

    for bucket_start in range(min_a, max_a, bucket_size):
        bucket_end = bucket_start + bucket_size
        count = sum(1 for a in angles if bucket_start <= a < bucket_end)
        if count == 0:
            continue
        bar_len = min(60, count)
        bar = "█" * bar_len
        in_threshold = abs(bucket_start + bucket_size / 2) <= threshold_degrees
        c = GREEN if in_threshold else RED
        marker = " ◄ threshold" if abs(abs(bucket_start + bucket_size / 2) - threshold_degrees) < bucket_size else ""
        print(f"    {bucket_start:+4d}° to {bucket_end:+4d}°: {c}{bar}{RESET} {count}{marker}")
    print()

    # Also show vertical
    v_angles = [f.fused_v_angle_deg for f in frames if f.face_detected]
    if v_angles:
        print(f"  Fused vertical angle distribution:")
        min_v = int(min(v_angles) // bucket_size * bucket_size) - bucket_size
        max_v = int(max(v_angles) // bucket_size * bucket_size) + bucket_size * 2
        for bucket_start in range(min_v, max_v, bucket_size):
            bucket_end = bucket_start + bucket_size
            count = sum(1 for a in v_angles if bucket_start <= a < bucket_end)
            if count == 0:
                continue
            bar_len = min(60, count)
            bar = "█" * bar_len
            in_threshold = abs(bucket_start + bucket_size / 2) <= threshold_degrees
            c = GREEN if in_threshold else RED
            print(f"    {bucket_start:+4d}° to {bucket_end:+4d}°: {c}{bar}{RESET} {count}")
        print()


def export_csv(results: list[VideoResult], csv_path: Path):
    """Export all frame diagnostics to a CSV file."""
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "video", "frame_idx", "timestamp_s", "face_detected", "on_camera",
            "left_iris_ratio", "right_iris_ratio", "avg_iris_h_ratio", "avg_iris_v_ratio",
            "iris_h_angle_deg", "iris_v_angle_deg",
            "head_yaw_deg", "head_pitch_deg", "head_roll_deg", "head_pose_available",
            "fused_h_angle_deg", "fused_v_angle_deg",
            "attention_state", "attention_confidence",
            "face_presence_score", "visual_attention_score",
            "processing_ms",
        ])
        for result in results:
            for f in result.frames:
                writer.writerow([
                    result.video_name, f.frame_idx, f"{f.timestamp_s:.3f}",
                    f.face_detected, f.on_camera,
                    f"{f.left_iris_ratio:.4f}", f"{f.right_iris_ratio:.4f}",
                    f"{f.avg_iris_h_ratio:.4f}", f"{f.avg_iris_v_ratio:.4f}",
                    f"{f.iris_h_angle_deg:.2f}", f"{f.iris_v_angle_deg:.2f}",
                    f"{f.head_yaw_deg:.2f}", f"{f.head_pitch_deg:.2f}",
                    f"{f.head_roll_deg:.2f}", f.head_pose_available,
                    f"{f.fused_h_angle_deg:.2f}", f"{f.fused_v_angle_deg:.2f}",
                    f.attention_state, f"{f.attention_confidence:.3f}",
                    f"{f.face_presence_score:.3f}", f"{f.visual_attention_score:.3f}",
                    f"{f.processing_ms:.1f}",
                ])
    print(f"\n✓ CSV exported to {csv_path}")


# ── Main ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Per-frame gaze & attention debug harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all test videos with default settings:
  python ../scripts/gaze_debug_harness.py

  # Test a wider gaze threshold:
  python ../scripts/gaze_debug_harness.py --gaze-threshold 25

  # Shorter attention window for faster state transitions:
  python ../scripts/gaze_debug_harness.py --attn-window 3.0 --attn-min-samples 2

  # Compact output (fewer columns):
  python ../scripts/gaze_debug_harness.py --compact

  # Export to CSV:
  python ../scripts/gaze_debug_harness.py --csv debug_output.csv
        """,
    )
    parser.add_argument(
        "--video", type=Path, default=None,
        help="Single video to process (default: all test_*.mp4 in backend/tests/)",
    )
    parser.add_argument(
        "--videos-dir", type=Path, default=DEFAULT_VIDEOS_DIR,
        help="Directory containing test videos",
    )
    parser.add_argument(
        "--fps", type=int, default=SAMPLE_FPS,
        help=f"Frame sampling rate (default: {SAMPLE_FPS})",
    )
    parser.add_argument(
        "--gaze-threshold", type=float, default=None,
        help=f"Override gaze_threshold_degrees (current: {settings.gaze_threshold_degrees}°)",
    )
    parser.add_argument(
        "--attn-window", type=float, default=None,
        help=f"Override attention_state_window_seconds (current: {settings.attention_state_window_seconds}s)",
    )
    parser.add_argument(
        "--attn-min-samples", type=int, default=None,
        help=f"Override attention_state_min_samples (current: {settings.attention_state_min_samples})",
    )
    parser.add_argument(
        "--compact", action="store_true",
        help="Compact per-frame output (fewer columns)",
    )
    parser.add_argument(
        "--no-frames", action="store_true",
        help="Skip per-frame table, only show summaries and histograms",
    )
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="Export all frame diagnostics to a CSV file",
    )
    args = parser.parse_args()

    gaze_threshold = args.gaze_threshold if args.gaze_threshold is not None else settings.gaze_threshold_degrees
    attn_window = args.attn_window if args.attn_window is not None else settings.attention_state_window_seconds
    attn_min_samples = args.attn_min_samples if args.attn_min_samples is not None else settings.attention_state_min_samples

    # Print active settings
    print(f"\n{BOLD}Gaze & Attention Debug Harness{RESET}")
    print(f"{'─' * 50}")
    print(f"  Gaze threshold:            ±{gaze_threshold:.1f}°", end="")
    if args.gaze_threshold is not None:
        print(f"  {YELLOW}(overridden, default: {settings.gaze_threshold_degrees}°){RESET}")
    else:
        print()
    print(f"  Attention window:          {attn_window:.1f}s", end="")
    if args.attn_window is not None:
        print(f"  {YELLOW}(overridden, default: {settings.attention_state_window_seconds}s){RESET}")
    else:
        print()
    print(f"  Attention min samples:     {attn_min_samples}", end="")
    if args.attn_min_samples is not None:
        print(f"  {YELLOW}(overridden, default: {settings.attention_state_min_samples}){RESET}")
    else:
        print()
    print(f"  Camera-facing ratio:       {settings.attention_state_camera_facing_ratio_threshold}")
    print(f"  Screen horiz max:          ±{settings.attention_state_screen_horizontal_max_deg}°")
    print(f"  Screen vert max:           ±{settings.attention_state_screen_vertical_max_deg}°")
    print(f"  Iris→angle multiplier:     150.0  (hardcoded in gaze_estimator.py)")
    print(
        f"  Head-pose fusion weights:  {settings.gaze_iris_weight:.2f} iris / {settings.gaze_head_pose_weight:.2f} head-pose"
    )
    print(f"  Head-pose EMA alpha:       {settings.gaze_head_pose_ema_alpha:.2f}")
    print(
        f"  Recovery hysteresis:       {settings.gaze_recovery_min_consecutive_frames} frame(s) within ±{max(1.0, gaze_threshold - settings.gaze_recovery_threshold_margin_deg):.1f}°"
    )
    print(f"  Sample FPS:                {args.fps}")
    print()

    # Find videos
    if args.video:
        video_files = [args.video]
    else:
        videos_dir = args.videos_dir
        video_files = sorted(
            p for p in videos_dir.iterdir()
            if p.suffix.lower() in VIDEO_EXTENSIONS
            and p.stem.startswith("test_")
        )
        if not video_files:
            print(f"❌ No test_*.mp4 videos found in {videos_dir}")
            return 1

    print(f"Found {len(video_files)} video(s):")
    for v in video_files:
        print(f"  • {v.name}")
    print()

    # Process each video
    results: list[VideoResult] = []
    for video_path in video_files:
        print(f"Processing {video_path.name} ...", flush=True)
        try:
            result = process_video(
                video_path,
                sample_fps=args.fps,
                gaze_threshold=gaze_threshold,
                attn_window=attn_window,
                attn_min_samples=attn_min_samples,
            )
            results.append(result)

            print_summary(result, gaze_threshold)
            print_angle_histogram(result.frames, gaze_threshold)
            if not args.no_frames:
                print_frame_table(result.frames, compact=args.compact)
            print()

        except Exception as e:
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            continue

    if not results:
        print("❌ No videos were processed successfully")
        return 1

    # Overall summary
    print(f"\n{BOLD}{'═' * 90}{RESET}")
    print(f"{BOLD}  OVERALL SUMMARY{RESET}")
    print(f"{'═' * 90}")
    for r in results:
        on_cam_color = GREEN if r.on_camera_pct > 50 else RED
        face_color = GREEN if r.face_detected_pct > 80 else RED
        print(f"  {r.video_name:<45s}  "
              f"Face: {face_color}{r.face_detected_pct:5.1f}%{RESET}  "
              f"OnCam: {on_cam_color}{r.on_camera_pct:5.1f}%{RESET}  "
              f"Top state: ", end="")
        if r.attention_state_counts:
            top_state = max(r.attention_state_counts, key=r.attention_state_counts.get)
            top_pct = r.attention_state_counts[top_state] / r.total_frames * 100
            print(f"{color_state(top_state)} ({top_pct:.0f}%)")
        else:
            print("—")
    print()

    # Export CSV if requested
    if args.csv:
        export_csv(results, args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
