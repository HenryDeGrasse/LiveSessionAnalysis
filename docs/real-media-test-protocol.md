# Real Media Accuracy Test Protocol

This document describes how to record, label, and validate the video processing
pipeline against real webcam video clips. It complements the synthetic-trace
accuracy report by testing the full upstream signal extraction (MediaPipe
FaceMesh → gaze estimation) on actual camera input.

## Why This Matters

The synthetic accuracy report (`docs/accuracy-report.md`) validates the metrics
engine and coaching logic, but not the upstream signal extraction pipeline.
Real-world accuracy depends on:

- MediaPipe FaceMesh performance on actual camera/microphone input
- Lighting, camera angle, glasses, and face orientation
- Compression artifacts and resolution variation

This protocol fills that gap.

## Quick Start

```bash
# 1. Record clips and label them (see below)
mkdir -p data/real-media-clips

# 2. Run the validation
make real-media-accuracy

# Or with a custom directory:
cd backend && uv run --python 3.11 --with-requirements requirements.txt \
    python ../scripts/real_media_accuracy.py --clips-dir ../data/real-media-clips
```

## Recording Test Clips

### Equipment

- Standard laptop webcam (720p or 1080p)
- Quiet room with normal indoor lighting (~300+ lux)
- Participant seated at normal laptop distance (~50–70 cm)

### Recommended Clips

Record 3–5 clips covering these scenarios:

#### Clip 1: Basic Gaze Alternation (`gaze-alternation.mp4`)
Duration: 60 seconds

| Time | Action |
|------|--------|
| 0–10s | Look directly at webcam lens |
| 10–20s | Look away to the right |
| 20–30s | Look directly at webcam lens |
| 30–40s | Look down at desk/keyboard |
| 40–50s | Look directly at webcam lens |
| 50–60s | Look away to the left |

#### Clip 2: Screen vs Camera (`screen-vs-camera.mp4`)
Duration: 60 seconds

| Time | Action |
|------|--------|
| 0–10s | Look directly at webcam lens |
| 10–20s | Look at screen content (slightly below camera) |
| 20–30s | Look directly at webcam lens |
| 30–40s | Look at screen content (slightly below camera) |
| 40–50s | Look directly at webcam lens |
| 50–60s | Look at screen content (slightly below camera) |

#### Clip 3: Face Missing (`face-missing.mp4`)
Duration: 40 seconds

| Time | Action |
|------|--------|
| 0–10s | Face visible, looking at camera |
| 10–20s | Cover camera / turn away completely |
| 20–30s | Face visible, looking at camera |
| 30–40s | Leave frame entirely |

#### Clip 4: Glasses / Varied Lighting (`glasses-lighting.mp4`)
Duration: 40 seconds — with glasses if available

| Time | Action |
|------|--------|
| 0–10s | Normal lighting, look at camera |
| 10–20s | Normal lighting, look away |
| 20–30s | Dim lighting, look at camera |
| 30–40s | Dim lighting, look away |

#### Clip 5: Natural Session Behavior (`natural-session.mp4`)
Duration: 120 seconds — simulate a real tutoring scenario

| Time | Action |
|------|--------|
| 0–15s | Look at camera (greeting) |
| 15–30s | Look at screen (reading) |
| 30–45s | Look at camera (explaining) |
| 45–60s | Look down (writing/notes) |
| 60–75s | Look at camera |
| 75–90s | Look at screen |
| 90–105s | Look at camera |
| 105–120s | Look away (thinking) |

### Recording Tips

1. **Use a timer** — have a countdown timer visible on a second screen or phone
   so transitions happen at precise intervals
2. **Hold each position** — maintain each gaze direction for the full bin
   duration; avoid transitioning during the last second of a bin
3. **Normal behavior** — don't exaggerate; use natural head positions and gaze
4. **Multiple takes** — record 2–3 attempts and pick the cleanest

### Recording Command (optional)

Use any recording tool. FFmpeg example for a 60-second clip:

```bash
ffmpeg -f avfoundation -framerate 30 -video_size 1280x720 \
    -i "0" -t 60 data/real-media-clips/gaze-alternation.mp4
```

On Linux:
```bash
ffmpeg -f v4l2 -framerate 30 -video_size 1280x720 \
    -i /dev/video0 -t 60 data/real-media-clips/gaze-alternation.mp4
```

## Labeling Format

Each video clip needs a companion `.labels.json` file with the same base name.

### Schema

```json
{
    "description": "Human-readable description of the clip",
    "bin_duration_seconds": 5,
    "bins": [
        {
            "start_s": 0,
            "end_s": 5,
            "gaze": "on_camera",
            "face_present": true
        },
        {
            "start_s": 5,
            "end_s": 10,
            "gaze": "off_camera",
            "face_present": true
        }
    ]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | What the clip tests |
| `bin_duration_seconds` | number | Duration of each evaluation bin (typically 5s) |
| `bins[].start_s` | number | Bin start time in seconds |
| `bins[].end_s` | number | Bin end time in seconds |
| `bins[].gaze` | string | `"on_camera"`, `"off_camera"`, or `"ignore"` |
| `bins[].face_present` | boolean | Whether a face should be visible |

### Gaze values

- **`on_camera`** — participant is looking directly at the webcam lens
- **`off_camera`** — participant is looking away (screen, down, left, right)
- **`ignore`** — transition period or ambiguous; excluded from accuracy calculation

### Example: `gaze-alternation.labels.json`

```json
{
    "description": "Alternating on-camera and off-camera gaze in 10s bins",
    "bin_duration_seconds": 5,
    "bins": [
        {"start_s": 0,  "end_s": 5,  "gaze": "on_camera",  "face_present": true},
        {"start_s": 5,  "end_s": 10, "gaze": "on_camera",  "face_present": true},
        {"start_s": 10, "end_s": 15, "gaze": "off_camera", "face_present": true},
        {"start_s": 15, "end_s": 20, "gaze": "off_camera", "face_present": true},
        {"start_s": 20, "end_s": 25, "gaze": "on_camera",  "face_present": true},
        {"start_s": 25, "end_s": 30, "gaze": "on_camera",  "face_present": true},
        {"start_s": 30, "end_s": 35, "gaze": "off_camera", "face_present": true},
        {"start_s": 35, "end_s": 40, "gaze": "off_camera", "face_present": true},
        {"start_s": 40, "end_s": 45, "gaze": "on_camera",  "face_present": true},
        {"start_s": 45, "end_s": 50, "gaze": "on_camera",  "face_present": true},
        {"start_s": 50, "end_s": 55, "gaze": "off_camera", "face_present": true},
        {"start_s": 55, "end_s": 60, "gaze": "off_camera", "face_present": true}
    ]
}
```

### Tips for Labeling

- Use 5-second bins by default (gives ~15 frames at 3 FPS for majority voting)
- Mark the first/last second of a transition as `"ignore"` if the gaze direction
  is ambiguous during the switch
- For "looking at screen" scenarios, label as `"off_camera"` — the system treats
  screen-looking the same as away (this is a known limitation, see
  `docs/limitations.md`)

## Running the Validation

```bash
# From project root
make real-media-accuracy

# With options
cd backend && uv run --python 3.11 --with-requirements requirements.txt \
    python ../scripts/real_media_accuracy.py \
        --clips-dir ../data/real-media-clips \
        --output ../docs/real-media-accuracy-report.md \
        --fps 3
```

### Output

The script produces:
1. Console output with per-clip accuracy
2. `docs/real-media-accuracy-report.md` with detailed results including:
   - Overall and per-clip gaze accuracy, precision, and recall
   - Precision: of predicted `on_camera` bins, how many were correct (quantifies false positives)
   - Recall: of actual `on_camera` bins, how many were detected (quantifies false negatives)
3. Exit code 0 if overall accuracy ≥ 85%, non-zero otherwise

### Example Output

```
Found 3 labeled clip(s) in data/real-media-clips

  Processing gaze-alternation.mp4 ... ✅ gaze=91.7% face=100.0% (180 frames, 42.3 ms/frame)
  Processing screen-vs-camera.mp4 ... ✅ gaze=87.5% face=100.0% (180 frames, 41.8 ms/frame)
  Processing face-missing.mp4 ...     ✅ gaze=100.0% face=87.5% (120 frames, 39.1 ms/frame)

✓ Report written to docs/real-media-accuracy-report.md
  Overall gaze accuracy: 91.4% (target ≥ 85%)

✅ All targets met.
```

## Expected Results and Thresholds

| Metric | Target | Notes |
|--------|--------|-------|
| Gaze binary accuracy | ≥ 85% | From assignment rubric |
| Face detection accuracy | ≥ 95% | Face present/absent |
| Avg frame processing | < 100 ms | At 320×240, single face |

### Common Issues

| Symptom | Likely Cause | Mitigation |
|---------|-------------|------------|
| Low gaze accuracy for screen-looking | "Screen" and "camera" are close together | Expected — this is a known limitation. Use `"ignore"` for ambiguous bins |
| Face not detected in dim lighting | MediaPipe confidence drops below threshold | Ensure ≥100 lux; see `calibration.md` |
| Wrong gaze with glasses | Reflective coatings shift iris landmarks | Note in report; no mitigation available |
| High processing time | Large source frames | Frames are auto-resized to 320×240; shouldn't be an issue |

## Threshold Calibration

If gaze accuracy is below target, try adjusting the gaze threshold:

```python
# In backend/app/config.py or via environment variable
LSA_GAZE_THRESHOLD_DEGREES=12  # stricter (default: 15)
LSA_GAZE_THRESHOLD_DEGREES=18  # more permissive
```

Then re-run validation. See `docs/calibration.md` for detailed guidance.

## Camera Position Reference

| Camera Position | Recommended Threshold | Notes |
|----------------|----------------------|-------|
| Laptop webcam (top-center) | 15° (default) | Best accuracy |
| External webcam (top of monitor) | 12–15° | May need tightening |
| External webcam (beside monitor) | 18–20° | More permissive needed |
| Phone camera (variable) | 15–20° | Position varies |

## File Organization

```
data/real-media-clips/          # NOT committed to git (video files too large)
├── gaze-alternation.mp4
├── gaze-alternation.labels.json
├── screen-vs-camera.mp4
├── screen-vs-camera.labels.json
├── face-missing.mp4
├── face-missing.labels.json
└── README.md                   # Optional: notes about recording conditions
```

**Important:** Video files should NOT be committed to the repository (they are
typically 10–100 MB each). Add `data/real-media-clips/*.mp4` etc. to
`.gitignore`. The `.labels.json` files can optionally be committed as they are
small and serve as documentation.

## Extending to Audio

This protocol currently covers video (gaze/face detection) only. Audio accuracy
validation can follow a similar pattern:

1. Record PCM audio with scripted speech/silence segments
2. Create `.labels.json` with speech activity ground truth
3. Run through `AudioProcessor` and compare

See the [traces and evals plan](traces-and-evals-plan-2026-03-09.md) for the
broader evaluation architecture.
