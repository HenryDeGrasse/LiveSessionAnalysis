# Known Limitations

## Core Session Experience

### In-App Peer Media Exists, but Production Call Reliability Still Needs Hardening
The current product **does** provide an in-app tutoring call surface: tutor and student can see and hear each other in the session page via WebRTC while backend analytics continue in parallel.

The main remaining limitation is **production-grade network reliability**, not the absence of peer media itself:
- localhost and fake-media browser coverage are in place
- real cross-device / cross-network validation is still needed
- TURN-backed ICE configuration is required for dependable production connectivity
- longer-duration soak testing is still needed to build confidence around reconnects and resource cleanup

See `docs/real-tutoring-session-experience-plan.md` and `docs/testing-audit-2026-03-09.md` for the current live-call status.

## Eye Contact Detection

### "Looking at camera" vs "Looking at screen"
The system measures whether the participant is looking at their **webcam camera**, not at screen content. This is a deliberate simplification:
- "Looking at camera" approximates direct engagement with the other person
- "Looking at screen" (reading shared content, looking at the other person's video feed slightly off-camera) registers as **not** eye contact
- The system cannot distinguish "looking at shared content on screen" from "distracted"

### Camera Position
The gaze threshold is calibrated for a typical **laptop webcam position** (top-center of screen). External cameras at different positions will need threshold adjustment. See `calibration.md`.

### Glasses
Glasses, especially with reflective coatings, may reduce iris landmark accuracy. Prescription lenses with strong refraction can shift apparent iris position. No mitigation is implemented.

### Lighting
Low-light conditions degrade MediaPipe FaceMesh landmark precision. The system reports stale or zero gaze data rather than crashing, but accuracy drops significantly below ~100 lux.

### Multi-Monitor Setups
Looking at a second monitor always registers as no eye contact, regardless of whether the participant is reading relevant session content.

## Audio Analysis

### Environment Noise
webrtcvad (mode 2) may misclassify background noise as speech in noisy environments. This can inflate speaking time for participants in loud settings.

### Audio Device Contention
Running both tutor and student on the same machine with one microphone is unreliable for validation. Use pre-recorded PCM fixtures for testing or two separate devices for demos.

### No Emotion Detection
The system detects voice activity and energy (RMS, speech rate) but does not perform emotion recognition from audio. The "energy" metric is a proxy for vocal engagement, not emotional state.

## Expression Analysis
Expression valence (smile ratio + eyebrow position) is a **weak secondary signal**:
- It supplements audio energy but has low standalone accuracy
- Cultural differences in facial expression are not accounted for
- Masks or face coverings disable expression analysis entirely

## Network and Latency
- WebSocket connections have a reconnect grace period (`reconnect_grace_seconds = 10.0`): when a participant disconnects, the backend waits before finalizing the session, allowing the client to reconnect (frontend has exponential backoff and tutor-facing disconnect/reconnect signaling)
- Reconnect behavior is backend/websocket-tested, but still lacks browser-level smoke coverage for full reconnect/resume UX
- Clock skew between client and server is not corrected; latency segments are measured independently
- Network jitter can cause frame reordering; the system processes frames in arrival order

## Engagement Score
The composite engagement score (`student_eye * 40 + min_energy * 30 + talk_balance * 30`) is a heuristic:
- Weights are not empirically validated against learning outcomes
- The score may not correlate with actual student comprehension
- Different session types (lecture vs discussion) may need different weighting

## Coaching Nudges
- Nudges are rule-based, not ML-driven; they cannot adapt to individual tutor styles
- Cooldown timers prevent nudge fatigue but may miss recurring issues
- No feedback loop: the system doesn't learn which nudges tutors find helpful

## Scale
- Designed for one session at a time per server instance
- JSON file storage is not suitable for high-volume analytics
- No built-in support for concurrent sessions sharing resources
