# Known Limitations

## Core Session Experience

### LiveKit-Based Peer Media with Local Dev Dependency
The in-app tutoring call now uses **LiveKit** as the sole media transport (custom WebRTC removed). Tutor and student connect via LiveKit rooms with HD video (H.264, up to 4.5 Mbps at 1080p).

**Remaining limitations**:
- Requires a LiveKit server (local `livekit-server` binary or cloud deployment)
- `livekit==0.18.3` is pinned due to protobuf<4 requirement from mediapipe; upgrading to `livekit>=0.19` requires resolving the mediapipe/protobuf conflict
- Cross-network (TURN) configuration not yet validated in production
- Soak testing for long sessions (>1hr) still needed
- The server-side analytics worker subscribes to tracks with `hidden=True` — participants don't see it, but it consumes server resources for each active room

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
- Nudges are rule-based with session-type profiles, not ML-driven; they cannot adapt to individual tutor styles beyond the session-type preset
- 4 live rules (`check_for_understanding`, `student_off_task`, `let_them_finish`, `tech_check`) — sparse by design (precision > recall)
- `energy_drop` was removed as a live nudge due to false positives in lectures (quiet-but-attentive students). Energy is now post-session only.
- Persistence-based off-task detection reduces false positives but may miss short disengagement episodes (< profile threshold)
- Visual-confidence suppression only gates visual rules — if gaze data is unreliable, off-task nudges are suppressed but audio-based nudges still fire
- Cooldown timers prevent nudge fatigue but may miss recurring issues
- No feedback loop: the system doesn't learn which nudges tutors find helpful
- Session type must be set at session creation; mid-session type changes are not supported

## Scale
- Designed for one session at a time per server instance
- JSON file storage is not suitable for high-volume analytics
- No built-in support for concurrent sessions sharing resources

## AI Conversational Intelligence

### Transcription Quality
- Quiet speech may not be transcribed if the student speaks softly or far from the microphone
- Background noise degrades STT accuracy significantly
- AssemblyAI's streaming model has ~1-2s latency; transcripts are not instantaneous
- Non-English speech is not supported (English-only model configured)
- Overlapping speech (both participants talking) may produce garbled transcripts

### Uncertainty Detection
- Linguistic hedging detection uses keyword/pattern matching, not ML — may miss subtle uncertainty or flag normal conversational fillers
- Paralinguistic signals (pitch variation, pause patterns) depend on Praat pitch extraction, which returns 0.0 when parselmouth is not installed (Docker ARM64 builds are slow)
- Uncertainty scores are heuristic composites, not empirically validated against actual student understanding

### AI Coaching Copilot
- LLM suggestions depend on transcript quality — garbage-in, garbage-out
- 35-second baseline interval means the first auto-suggestion takes ~35s minimum
- Requires at least 20 words of transcript before any suggestion fires
- Budget ceiling of 60 LLM calls/hour — can exhaust in intensive sessions
- Output validation rejects domain answers but cannot guarantee pedagogical quality
- Gemini 2.5 Flash occasionally wraps JSON in markdown fences (handled by fence-stripping parser, but novel formats could break parsing)
- No feedback loop — the system does not learn from tutor feedback on suggestions

### Cost
- AssemblyAI streaming: ~$0.36/session (both roles, continuous audio)
- OpenRouter LLM calls: ~$0.01-0.05/session depending on call count
- No local/offline STT or LLM option — requires internet connectivity and API keys

### Privacy
- Transcript text is sent to AssemblyAI for processing (opt-out from model training not available in v3)
- LLM prompts containing scrubbed transcript text are sent to OpenRouter → model provider
- PII scrubbing is pattern-based (regex), not ML-based — may miss uncommon PII formats
