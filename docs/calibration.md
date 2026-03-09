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

| Level | Rolling Avg (ms) | Action |
|-------|-----------------|--------|
| 0 (Normal) | < 250 | 3 FPS, full analysis |
| 1 (Mild) | 250-350 | 2 FPS, full analysis |
| 2 (Moderate) | 350-450 | 1 FPS, skip expression |
| 3 (Severe) | > 450 | 1 FPS, skip gaze + expression |

Recovery: In the current implementation, the system steps back up when the rolling average of the recent processing-time samples drops back below the threshold.
