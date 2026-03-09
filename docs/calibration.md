# Calibration Guide

## Gaze Threshold Calibration

### Default Configuration
- **Threshold angle**: 15 degrees (configurable via `GAZE_THRESHOLD_DEGREES`)
- **Camera assumption**: Top-center laptop webcam
- **Method**: Iris landmarks (468-472) relative to eye corners. Horizontal and vertical ratios are converted to approximate angles via `(ratio - 0.5) * 150.0` degrees

### How to Calibrate
1. Have the participant sit at their normal distance from the camera
2. Ask them to look directly at the webcam lens — this should register as "on camera"
3. Ask them to look at different screen positions — ideally only webcam gaze registers as eye contact
4. Adjust `GAZE_THRESHOLD_DEGREES` if needed:
   - **Lower (10-12)**: Stricter, only very direct gaze counts. Better for distinguishing camera vs screen-top
   - **Default (15)**: Balanced, captures most direct gazes with some tolerance
   - **Higher (18-20)**: More permissive, includes near-camera gazes. Better for external cameras placed slightly off-center

### Testing Against Ground Truth

**Recommended approach**: Use pre-recorded video clips with scripted gaze behaviors:

1. Create 5-minute test clips with scripted sequences:
   - Looking at camera (5s bins)
   - Looking away (down, left, right)
   - Looking at screen content (slightly below camera)

2. Label each 5-second bin as "on-camera" or "off-camera"

3. Feed frames into `video_processor/pipeline.py` (bypassing WebSocket) and compare:
   ```python
   from app.video_processor.pipeline import VideoProcessor

   processor = VideoProcessor()
   for frame_bytes in test_frames:
       result = processor.process_frame(frame_bytes)
       if result.gaze:
           predicted = result.gaze.on_camera
           # Compare with ground truth label
   ```

4. Report:
   - Binary classification accuracy (target: >= 85%)
   - Precision and recall separately
   - Test at 10, 15, and 20 degree thresholds

### Camera Position Adjustment
| Camera Position | Suggested Threshold |
|----------------|-------------------|
| Laptop webcam (top-center) | 15 degrees (default) |
| External webcam (top of monitor) | 12-15 degrees |
| External webcam (beside monitor) | 18-20 degrees |
| Phone camera (variable) | 15-20 degrees |

## Speaking Time Validation

### Pre-recorded Fixtures
Use pre-recorded PCM audio files with known speech segments:
1. Create alternating speech/silence segments with precise timestamps
2. Feed through `audio_processor/pipeline.py`
3. Compare detected speech segments with ground truth
4. Target: <= 5% absolute error in talk-time ratio

### Test Setup
```python
from app.audio_processor.pipeline import AudioProcessor

processor = AudioProcessor()
for chunk in pcm_chunks:
    result = processor.process_chunk(chunk)
    # Compare result.is_speech with ground truth
```

## Interruption Validation

### Pre-recorded Overlapping Speech
1. Create two PCM streams with known overlap timestamps
2. Feed both through separate AudioProcessor instances
3. When both report `is_speech=True`, count as interruption
4. Compare with labeled ground truth
5. Target: >= 80% F1 score

## Energy Score Calibration

### Component Weights
Default: `0.5 * rms + 0.3 * speech_rate_variance + 0.2 * expression_valence`

These weights can be adjusted via settings:
- `ENERGY_WEIGHT_RMS`: Audio RMS energy (most reliable signal)
- `ENERGY_WEIGHT_SPEECH_RATE`: Speech rate variance
- `ENERGY_WEIGHT_EXPRESSION`: Facial expression valence (least reliable)

The coaching system also supports a configurable baseline-drop threshold via:
- `ENERGY_DROP_FROM_BASELINE_THRESHOLD`: how far current energy must fall below the rolling baseline before the baseline-aware energy-drop rule fires

### Engagement Score Weights
Default: `student_eye * 40 + min_energy * 30 + talk_balance * 30`

Components:
- **Student eye contact** (40%): Most direct engagement signal
- **Minimum energy** (30%): Lower of tutor/student energy
- **Talk time balance** (30%): How balanced the conversation is (1.0 = equal split)

## Degradation Thresholds

| Level | Rolling Avg (ms) | Action | `degradation_reason` |
|-------|-----------------|--------|---------------------|
| 0 (Normal) | < 250 | 3 FPS, full analysis | `normal` |
| 1 (Mild) | 250-350 | 2 FPS, full analysis | `reduced_fps` |
| 2 (Moderate) | 350-450 | 1 FPS, skip expression | `skip_expression` |
| 3 (Severe) | > 450 | 1 FPS, skip gaze + expression | `skip_gaze_and_expression` |

Recovery: In the current implementation, the system steps back up when the rolling average of the recent processing-time samples drops back below the threshold.

### Latency Monitoring
The system tracks processing latency percentiles across a 100-sample sliding window:
- `latency_p50_ms` — median processing time
- `latency_p95_ms` — 95th percentile processing time
- `degradation_reason` — human-readable string for the current degradation state

These are exposed in `MetricsSnapshot` and shown in the tutor debug panel.

## Coaching Profile Thresholds

Each session type has calibrated thresholds for live nudge rules:

| Profile | Overtalk Ceiling | Silence Threshold | Off-Task Seconds | Talk Check After |
|---------|-----------------|-------------------|-----------------|-----------------|
| `lecture` | 0.92 | 300s | 120s | 120s |
| `practice` | 0.55 | 60s | 45s | 60s |
| `socratic` | 0.65 | 45s | 60s | 60s |
| `general` | 0.80 | 180s | 75s | 90s |
| `discussion` | 0.60 | 90s | 60s | 90s |

### How to Calibrate Session-Type Profiles
1. Run a session with `session_type=<type>` set at creation
2. Enable the debug panel (tutor only) to see coaching decisions in real-time
3. The "Coaching decisions" section shows:
   - **Candidates**: which rules considered firing
   - **Suppressed**: which were blocked and why (cooldown, confidence, threshold)
   - **Trigger features**: the metric values that triggered or nearly triggered the rule
4. Adjust profile thresholds in `backend/app/coaching_system/profiles.py`
5. Re-run `make eval` and `make accuracy-report` to verify no regressions

### Visual Confidence Gate
Only rules marked `requires_visual_confidence=True` (currently `student_off_task`) are suppressed when face confidence < 0.4. Audio-based rules always run regardless of visual data quality.
