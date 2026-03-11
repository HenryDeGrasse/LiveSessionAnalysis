#!/usr/bin/env python3
"""Validate gaze/face detection accuracy against real video clips.

Processes real video files through the VideoProcessor pipeline and compares
gaze/face detection results against labeled ground truth. This addresses
the synthetic-trace limitation: real-world accuracy depends on MediaPipe
FaceMesh + webrtcvad performance on actual camera/microphone input.

Usage:
    cd backend && uv run --python 3.11 --with-requirements requirements.txt \
        python ../scripts/real_media_accuracy.py --clips-dir ../data/real-media-clips

Or from root:
    make real-media-accuracy

Label format:
    Each video clip (e.g. ``gaze-test-01.mp4``) must have a companion
    ``gaze-test-01.labels.json`` with per-bin ground truth::

        {
            "description": "Participant looks at camera for 10s, then away for 10s",
            "bin_duration_seconds": 5,
            "bins": [
                {"start_s": 0,  "end_s": 5,  "gaze": "on_camera",  "face_present": true},
                {"start_s": 5,  "end_s": 10, "gaze": "on_camera",  "face_present": true},
                {"start_s": 10, "end_s": 15, "gaze": "off_camera", "face_present": true},
                {"start_s": 15, "end_s": 20, "gaze": "off_camera", "face_present": true}
            ]
        }
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Ensure backend is importable
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.video_processor.pipeline import VideoProcessor

# ── Constants ────────────────────────────────────────────────

DEFAULT_CLIPS_DIR = Path(__file__).resolve().parent.parent / "data" / "real-media-clips"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "real-media-accuracy-report.md"
SAMPLE_FPS = 3  # Match production default
ACCURACY_TARGET = 0.85  # Rubric: ≥85% eye-contact accuracy
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


# ── Data models ──────────────────────────────────────────────


@dataclass
class LabelBin:
    start_s: float
    end_s: float
    gaze: str  # "on_camera" | "off_camera" | "ignore"
    face_present: bool = True


@dataclass
class ClipLabels:
    description: str
    bin_duration_seconds: float
    bins: list[LabelBin]


@dataclass
class BinResult:
    """Result of evaluating one time bin."""
    start_s: float
    end_s: float
    expected_gaze: str
    expected_face: bool
    frame_count: int
    face_detected_count: int
    gaze_on_camera_count: int
    predicted_gaze: str  # majority vote
    predicted_face: bool  # majority vote
    gaze_correct: bool
    face_correct: bool


@dataclass
class ClipResult:
    """Result of evaluating one video clip."""
    clip_name: str
    description: str
    total_bins: int
    evaluated_bins: int  # bins where gaze != "ignore"
    gaze_correct_bins: int
    face_correct_bins: int
    gaze_accuracy: float
    face_accuracy: float
    # Precision/recall for "on_camera" class (positive = on_camera)
    gaze_precision: float  # TP / (TP + FP); of predicted on_camera, how many correct?
    gaze_recall: float     # TP / (TP + FN); of actual on_camera, how many detected?
    total_frames: int
    processing_time_s: float
    avg_frame_ms: float
    bin_results: list[BinResult] = field(default_factory=list)


# ── Label loading ────────────────────────────────────────────


def load_labels(label_path: Path) -> ClipLabels:
    """Load and validate a ``.labels.json`` file.

    Raises ``ValueError`` with a descriptive message when the file is
    malformed so callers always get a clean error instead of an opaque
    ``KeyError`` / ``TypeError``.
    """
    try:
        raw = label_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read label file {label_path.name}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Label file {label_path.name} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Label file {label_path.name}: expected a JSON object at top level, "
            f"got {type(data).__name__}"
        )

    if "bins" not in data:
        raise ValueError(
            f"Label file {label_path.name}: missing required key 'bins'. "
            f"Top-level keys found: {sorted(data.keys())}"
        )

    raw_bins = data["bins"]
    if not isinstance(raw_bins, list):
        raise ValueError(
            f"Label file {label_path.name}: 'bins' must be a list, "
            f"got {type(raw_bins).__name__}"
        )

    bins: list[LabelBin] = []
    for idx, b in enumerate(raw_bins):
        if not isinstance(b, dict):
            raise ValueError(
                f"Label file {label_path.name}: bins[{idx}] must be an object, "
                f"got {type(b).__name__}"
            )
        for required_key in ("start_s", "end_s"):
            if required_key not in b:
                raise ValueError(
                    f"Label file {label_path.name}: bins[{idx}] missing "
                    f"required key '{required_key}'"
                )
        bins.append(LabelBin(
            start_s=b["start_s"],
            end_s=b["end_s"],
            gaze=b.get("gaze", "ignore"),
            face_present=b.get("face_present", True),
        ))

    return ClipLabels(
        description=data.get("description", ""),
        bin_duration_seconds=data.get("bin_duration_seconds", 5),
        bins=bins,
    )


# ── Video processing ─────────────────────────────────────────


def process_clip(
    video_path: Path,
    labels: ClipLabels,
    processor: VideoProcessor,
    sample_fps: int = SAMPLE_FPS,
) -> ClipResult:
    """Process a video clip and evaluate against labels."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if video_fps <= 0:
        video_fps = 30.0  # fallback

    # Calculate frame sampling interval
    frame_interval = max(1, int(round(video_fps / sample_fps)))

    # Collect per-frame predictions
    frame_predictions: list[dict] = []
    frame_idx = 0
    total_processing_ms = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            timestamp_s = frame_idx / video_fps
            start_t = time.time()
            result = processor.process_frame_array(frame)
            elapsed_ms = (time.time() - start_t) * 1000
            total_processing_ms += elapsed_ms

            frame_predictions.append({
                "timestamp_s": timestamp_s,
                "face_detected": result.face_detected,
                "gaze_on_camera": result.gaze.on_camera if result.gaze else False,
                "processing_ms": elapsed_ms,
            })

        frame_idx += 1

    cap.release()

    total_frames = len(frame_predictions)
    processing_time_s = total_processing_ms / 1000
    avg_frame_ms = (total_processing_ms / total_frames) if total_frames > 0 else 0.0

    # Evaluate each labeled bin
    bin_results: list[BinResult] = []
    for label_bin in labels.bins:
        # Gather frames that fall within this bin
        bin_frames = [
            f for f in frame_predictions
            if label_bin.start_s <= f["timestamp_s"] < label_bin.end_s
        ]

        frame_count = len(bin_frames)
        face_detected_count = sum(1 for f in bin_frames if f["face_detected"])
        gaze_on_camera_count = sum(1 for f in bin_frames if f["gaze_on_camera"])

        # Majority vote for bin prediction
        if frame_count == 0:
            predicted_face = False
            predicted_gaze = "off_camera"
        else:
            predicted_face = face_detected_count > frame_count / 2
            predicted_gaze = (
                "on_camera" if gaze_on_camera_count > frame_count / 2
                else "off_camera"
            )

        gaze_correct = (
            label_bin.gaze == "ignore"
            or predicted_gaze == label_bin.gaze
        )
        face_correct = predicted_face == label_bin.face_present

        bin_results.append(BinResult(
            start_s=label_bin.start_s,
            end_s=label_bin.end_s,
            expected_gaze=label_bin.gaze,
            expected_face=label_bin.face_present,
            frame_count=frame_count,
            face_detected_count=face_detected_count,
            gaze_on_camera_count=gaze_on_camera_count,
            predicted_gaze=predicted_gaze,
            predicted_face=predicted_face,
            gaze_correct=gaze_correct,
            face_correct=face_correct,
        ))

    # Calculate accuracy (only on non-ignored bins)
    evaluated = [b for b in bin_results if b.expected_gaze != "ignore"]
    evaluated_count = len(evaluated)
    gaze_correct_count = sum(1 for b in evaluated if b.gaze_correct)
    face_correct_count = sum(1 for b in bin_results if b.face_correct)

    gaze_accuracy = (gaze_correct_count / evaluated_count) if evaluated_count > 0 else 0.0
    face_accuracy = (face_correct_count / len(bin_results)) if bin_results else 0.0

    # Precision/recall for "on_camera" class (positive = on_camera)
    # TP = predicted on_camera AND expected on_camera
    # FP = predicted on_camera AND expected off_camera
    # FN = predicted off_camera AND expected on_camera
    tp = sum(1 for b in evaluated if b.predicted_gaze == "on_camera" and b.expected_gaze == "on_camera")
    fp = sum(1 for b in evaluated if b.predicted_gaze == "on_camera" and b.expected_gaze == "off_camera")
    fn = sum(1 for b in evaluated if b.predicted_gaze == "off_camera" and b.expected_gaze == "on_camera")

    gaze_precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    gaze_recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0.0

    return ClipResult(
        clip_name=video_path.stem,
        description=labels.description,
        total_bins=len(bin_results),
        evaluated_bins=evaluated_count,
        gaze_correct_bins=gaze_correct_count,
        face_correct_bins=face_correct_count,
        gaze_accuracy=gaze_accuracy,
        face_accuracy=face_accuracy,
        gaze_precision=gaze_precision,
        gaze_recall=gaze_recall,
        total_frames=total_frames,
        processing_time_s=processing_time_s,
        avg_frame_ms=avg_frame_ms,
        bin_results=bin_results,
    )


# ── Report generation ────────────────────────────────────────


def generate_report(
    results: list[ClipResult],
    *,
    sample_fps: int = SAMPLE_FPS,
    failed_clips: Optional[list[tuple[str, str]]] = None,
) -> str:
    """Generate a markdown accuracy report from clip results."""
    if failed_clips is None:
        failed_clips = []

    lines: list[str] = []
    lines.append("# Real Media Accuracy Report")
    lines.append("")
    lines.append(f"*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*")
    lines.append("")
    lines.append("This report validates the video processing pipeline (MediaPipe FaceMesh +")
    lines.append("gaze estimation) against real webcam video clips with labeled ground truth.")
    lines.append("It complements the synthetic-trace accuracy report by exercising the full")
    lines.append("upstream signal extraction pipeline.")
    lines.append("")

    # Summary
    total_evaluated = sum(r.evaluated_bins for r in results)
    total_gaze_correct = sum(r.gaze_correct_bins for r in results)
    total_face_bins = sum(r.total_bins for r in results)
    total_face_correct = sum(r.face_correct_bins for r in results)
    total_frames = sum(r.total_frames for r in results)

    overall_gaze_acc = (total_gaze_correct / total_evaluated) if total_evaluated > 0 else 0.0
    overall_face_acc = (total_face_correct / total_face_bins) if total_face_bins > 0 else 0.0

    # Overall precision/recall (aggregate across all clips)
    all_evaluated = [
        b for r in results for b in r.bin_results if b.expected_gaze != "ignore"
    ]
    overall_tp = sum(1 for b in all_evaluated if b.predicted_gaze == "on_camera" and b.expected_gaze == "on_camera")
    overall_fp = sum(1 for b in all_evaluated if b.predicted_gaze == "on_camera" and b.expected_gaze == "off_camera")
    overall_fn = sum(1 for b in all_evaluated if b.predicted_gaze == "off_camera" and b.expected_gaze == "on_camera")
    overall_precision = (overall_tp / (overall_tp + overall_fp)) if (overall_tp + overall_fp) > 0 else 0.0
    overall_recall = (overall_tp / (overall_tp + overall_fn)) if (overall_tp + overall_fn) > 0 else 0.0

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Clips processed**: {len(results)}")
    lines.append(f"- **Total frames analyzed**: {total_frames}")
    lines.append(f"- **Gaze bins evaluated**: {total_evaluated}")
    lines.append(f"- **Overall gaze accuracy**: {overall_gaze_acc:.1%} "
                 f"({'✅ PASS' if overall_gaze_acc >= ACCURACY_TARGET else '❌ BELOW TARGET'}"
                 f", target ≥ {ACCURACY_TARGET:.0%})")
    lines.append(f"- **Overall gaze precision** (on_camera): {overall_precision:.1%}")
    lines.append(f"- **Overall gaze recall** (on_camera): {overall_recall:.1%}")
    lines.append(f"- **Overall face detection accuracy**: {overall_face_acc:.1%}")
    if failed_clips:
        lines.append(f"- **⚠ Failed clips**: {len(failed_clips)} (report is incomplete)")
    lines.append("")

    # Failed clips section (if any)
    if failed_clips:
        lines.append("## ⚠ Failed Clips")
        lines.append("")
        lines.append("The following clips could not be processed. Their results are **not**")
        lines.append("included in the accuracy numbers above, making this report incomplete.")
        lines.append("")
        lines.append("| Clip | Error |")
        lines.append("|------|-------|")
        for name, err in failed_clips:
            lines.append(f"| {name} | {err} |")
        lines.append("")

    # Per-clip table
    lines.append("## Per-Clip Results")
    lines.append("")
    lines.append("| Clip | Description | Bins | Gaze Accuracy | Precision | Recall | Face Accuracy | Avg Frame (ms) | Status |")
    lines.append("|------|-------------|------|---------------|-----------|--------|---------------|----------------|--------|")
    for r in results:
        status = "✅" if r.gaze_accuracy >= ACCURACY_TARGET else "❌"
        lines.append(
            f"| {r.clip_name} | {r.description[:50]} | "
            f"{r.evaluated_bins} | {r.gaze_accuracy:.1%} | "
            f"{r.gaze_precision:.1%} | {r.gaze_recall:.1%} | "
            f"{r.face_accuracy:.1%} | {r.avg_frame_ms:.1f} | {status} |"
        )
    lines.append("")

    # Detailed per-clip bin breakdown
    lines.append("## Detailed Bin Results")
    lines.append("")
    for r in results:
        lines.append(f"### {r.clip_name}")
        lines.append(f"*{r.description}*")
        lines.append("")
        lines.append(f"- Frames: {r.total_frames}, Processing: {r.processing_time_s:.1f}s, "
                     f"Avg: {r.avg_frame_ms:.1f} ms/frame")
        lines.append("")
        lines.append("| Bin (s) | Expected Gaze | Predicted | Frames | On-Camera | Face Det. | Correct |")
        lines.append("|---------|---------------|-----------|--------|-----------|-----------|---------|")
        for b in r.bin_results:
            correct_str = "✅" if b.gaze_correct else "❌"
            if b.expected_gaze == "ignore":
                correct_str = "—"
            lines.append(
                f"| {b.start_s:.0f}–{b.end_s:.0f} | {b.expected_gaze} | "
                f"{b.predicted_gaze} | {b.frame_count} | "
                f"{b.gaze_on_camera_count}/{b.frame_count} | "
                f"{b.face_detected_count}/{b.frame_count} | {correct_str} |"
            )
        lines.append("")

    # Performance summary
    if results:
        all_avg_ms = [r.avg_frame_ms for r in results if r.total_frames > 0]
        if all_avg_ms:
            lines.append("## Processing Performance")
            lines.append("")
            lines.append(f"- **Mean frame processing time**: {sum(all_avg_ms) / len(all_avg_ms):.1f} ms")
            lines.append(f"- **Min clip avg**: {min(all_avg_ms):.1f} ms")
            lines.append(f"- **Max clip avg**: {max(all_avg_ms):.1f} ms")
            lines.append(f"- **Processing resolution**: 320×240 (downscaled from source)")
            lines.append(f"- **Sample rate**: {sample_fps} FPS")
            lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append("1. Video clips are recorded with a webcam with scripted gaze behaviors.")
    lines.append("2. Each clip has a companion `.labels.json` with per-bin ground truth.")
    lines.append(f"3. Frames are sampled at {sample_fps} FPS"
                 f"{' (matching production default)' if sample_fps == SAMPLE_FPS else ''}.")
    lines.append("4. Each frame is processed through `VideoProcessor.process_frame_array()`")
    lines.append("   (same pipeline as production: resize → FaceMesh → gaze estimation).")
    lines.append("5. Per-bin predictions use majority vote across frames in the bin.")
    lines.append(f"6. Target: gaze binary accuracy ≥ {ACCURACY_TARGET:.0%} (from assignment rubric).")
    lines.append("")
    lines.append("### Targets (from assignment)")
    lines.append("")
    lines.append("| Metric | Target | Method |")
    lines.append("|--------|--------|--------|")
    lines.append("| Eye contact binary accuracy | ≥ 85% | Gaze on-camera vs labeled ground truth |")
    lines.append("| Face detection accuracy | ≥ 95% | Face present/absent vs labeled ground truth |")
    lines.append("")
    lines.append("### Precision & Recall (on_camera class)")
    lines.append("")
    lines.append("- **Precision**: Of all bins the system predicted as `on_camera`, what")
    lines.append("  fraction were actually `on_camera`? High precision means few false")
    lines.append("  positives (system rarely says 'eye contact' when there is none).")
    lines.append("- **Recall**: Of all bins that were actually `on_camera`, what fraction")
    lines.append("  did the system correctly detect? High recall means few false negatives")
    lines.append("  (system rarely misses real eye contact).")
    lines.append("- A system biased toward `off_camera` will have high precision but low")
    lines.append("  recall; a system biased toward `on_camera` will have high recall but")
    lines.append("  low precision.")
    lines.append("")
    lines.append("See `docs/real-media-test-protocol.md` for how to record and label test clips.")
    lines.append("")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────


def find_clips(clips_dir: Path) -> list[tuple[Path, Path]]:
    """Find video files with matching .labels.json files."""
    pairs: list[tuple[Path, Path]] = []
    for video_path in sorted(clips_dir.iterdir()):
        if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        label_path = video_path.with_suffix(".labels.json")
        if not label_path.exists():
            print(f"  ⚠ Skipping {video_path.name}: no .labels.json found")
            continue
        pairs.append((video_path, label_path))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate gaze/face detection accuracy on real video clips",
    )
    parser.add_argument(
        "--clips-dir",
        type=Path,
        default=DEFAULT_CLIPS_DIR,
        help=f"Directory containing video clips and .labels.json files (default: {DEFAULT_CLIPS_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output markdown report path (default: {OUTPUT_PATH})",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=SAMPLE_FPS,
        help=f"Frame sampling rate (default: {SAMPLE_FPS})",
    )
    args = parser.parse_args()

    clips_dir: Path = args.clips_dir
    output_path: Path = args.output

    if not clips_dir.exists():
        print(f"❌ Clips directory not found: {clips_dir}")
        print()
        print("To use this script:")
        print(f"  1. Create the directory: mkdir -p {clips_dir}")
        print("  2. Record webcam clips with scripted gaze behaviors")
        print("  3. Create .labels.json files for each clip")
        print("  4. See docs/real-media-test-protocol.md for full instructions")
        return 1

    clip_pairs = find_clips(clips_dir)
    if not clip_pairs:
        print(f"❌ No labeled video clips found in {clips_dir}")
        print()
        print("Expected: video files (.mp4, .mov, .avi, .mkv, .webm)")
        print("          with matching .labels.json files")
        print()
        print("Example:")
        print(f"  {clips_dir}/gaze-test-01.mp4")
        print(f"  {clips_dir}/gaze-test-01.labels.json")
        print()
        print("See docs/real-media-test-protocol.md for recording instructions.")
        return 1

    print(f"Found {len(clip_pairs)} labeled clip(s) in {clips_dir}")
    print()

    sample_fps: int = args.fps
    results: list[ClipResult] = []
    failed_clips: list[tuple[str, str]] = []  # (clip_name, error_message)
    processor: Optional[VideoProcessor] = None

    try:
        processor = VideoProcessor()
    except Exception as e:
        # VideoProcessor init can fail (e.g. mediapipe not installed).
        # Record every clip as failed so the report is still generated.
        for video_path, _label_path in clip_pairs:
            failed_clips.append((video_path.name, f"VideoProcessor init failed: {e}"))
        print(f"  ❌ VideoProcessor init failed: {e}")

    if processor is not None:
        try:
            for video_path, label_path in clip_pairs:
                print(f"  Processing {video_path.name} ...", end=" ", flush=True)
                try:
                    labels = load_labels(label_path)
                    result = process_clip(video_path, labels, processor, sample_fps=sample_fps)
                    results.append(result)
                    status = "✅" if result.gaze_accuracy >= ACCURACY_TARGET else "❌"
                    print(f"{status} gaze={result.gaze_accuracy:.1%} "
                          f"face={result.face_accuracy:.1%} "
                          f"({result.total_frames} frames, {result.avg_frame_ms:.1f} ms/frame)")
                except Exception as e:
                    failed_clips.append((video_path.name, str(e)))
                    print(f"❌ Error: {e}")
        finally:
            processor.close()

    if not results and not failed_clips:
        print("\n❌ No clips were successfully processed.")
        return 1

    # Always generate and write the report — even when every clip failed.
    # This ensures a malformed label file or corrupt video never prevents
    # the report from being written; the failure is recorded inside it.
    report = generate_report(results, sample_fps=sample_fps, failed_clips=failed_clips)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print()
    print(f"✓ Report written to {output_path}")

    # Fail if any clips could not be processed
    if failed_clips:
        print()
        print(f"❌ {len(failed_clips)} clip(s) failed to process:")
        for name, err in failed_clips:
            print(f"   - {name}: {err}")
        print()
        print("The accuracy report is incomplete. Fix the failing clips and re-run.")
        return 1

    if not results:
        print("\n❌ No clips were successfully processed.")
        return 1

    # Print summary
    total_evaluated = sum(r.evaluated_bins for r in results)
    total_correct = sum(r.gaze_correct_bins for r in results)
    overall_acc = (total_correct / total_evaluated) if total_evaluated > 0 else 0.0
    print(f"  Overall gaze accuracy: {overall_acc:.1%} (target ≥ {ACCURACY_TARGET:.0%})")
    print()

    if overall_acc < ACCURACY_TARGET:
        print(f"❌ Below target ({ACCURACY_TARGET:.0%}). See report for details.")
        return 1

    print("✅ All targets met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
