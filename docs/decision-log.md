# Decision Log

## Architecture Decisions

### Two-Participant Model (Separate WebSocket Streams)
**Decision**: Each participant (tutor + student) connects via their own browser with separate webcam/mic, sending data over individual WebSocket connections tagged with role tokens.

**Rationale**: Eliminates the need for speaker diarization entirely. Each stream is already identified by role, making speaking time and interruption detection trivially accurate. `FaceMesh` with `max_num_faces=1` per stream is simpler and more reliable than multi-face detection in a shared frame.

**Alternatives considered**: Single webcam capturing both participants (rejected: unreliable face separation, no way to identify who is speaking). A pure analytics-only architecture without participant-visible peer media is now considered insufficient for the product; see the superseding decision below.

### Real Tutoring Session Experience (Superseding Prior WebRTC Rejection)
**Decision**: Move toward a dual-path architecture: WebRTC for the live tutor↔student call experience, while preserving separate role-tagged analytics ingestion for backend coaching and post-session analysis.

**Rationale**: For Nerdy AI, the product must support an actual tutoring session, not just analytics on two independent media uploads. The previous rejection of WebRTC optimized for implementation simplicity, but it created a major product gap: tutor and student cannot currently see or hear each other inside the app.

**Planned shape**:
- tutor and student use WebRTC peer media for live audio/video
- the existing authenticated session WebSocket relays signaling only
- the backend analytics pipeline continues to ingest role-tagged media-derived data separately
- tutor-only nudges and post-session analytics stay server-driven

**Trade-offs**: Adds signaling, ICE/TURN configuration, peer connection lifecycle, and reconnect complexity. However, this is the smallest change that closes the biggest user-facing gap without discarding the current analytics backend.

**Follow-up doc**: `docs/real-tutoring-session-experience-plan.md`

### MediaPipe FaceMesh for Gaze Estimation
**Decision**: Use MediaPipe FaceMesh with `refine_landmarks=True` for iris-based gaze estimation using landmarks 468-472.

**Rationale**: No extra ML model needed, low latency (<50ms per frame), works on CPU. The refined iris landmarks provide sufficient accuracy for "looking at camera vs. away" binary classification.

**Trade-offs**: Less accurate than dedicated eye-tracking hardware. Cannot distinguish "looking at screen content" from "distracted" (both register as off-camera). Glasses with reflective coatings may reduce accuracy.

### webrtcvad for Voice Activity Detection
**Decision**: Use webrtcvad (mode 2) with per-participant instances processing 30ms PCM chunks.

**Rationale**: Battle-tested, fast, works well for speech/silence binary classification. Mode 2 balances sensitivity and false positive rate. Per-participant instances eliminate diarization entirely.

### JSON File Storage (No Database)
**Decision**: Store session analytics as JSON files in `data/sessions/`.

**Rationale**: No database dependency, portable, sufficient for the scope. Each session is a single JSON file with all summary data, timeline arrays, and flagged moments. Easy to inspect, back up, and transfer.

### Proactive Adaptive Degradation
**Decision**: Monitor rolling average of last 5 frames' processing time, step down at 250ms/350ms/450ms thresholds.

**Rationale**: The goal is to **never exceed 500ms** rather than reacting after the budget is blown. Three degradation levels provide a smooth path: reduce FPS, skip expression analysis, then disable gaze entirely. Audio metrics always continue unaffected. In the current implementation, recovery happens when the rolling average of the recent processing-time samples drops back below the degradation thresholds.

### Token-Based Role Security
**Decision**: When creating a session, backend generates `tutor_token` and `student_token`. Clients connect with `?token=xxx` and backend determines role from the token.

**Rationale**: Prevents anyone from claiming the tutor role by guessing URL parameters. Tutor shares the student token via a link. Only the tutor connection receives metrics and nudges.

### Fixed Metrics Emit with Fast-Path UI Refreshes
**Decision**: MetricsSnapshot is still recorded on a fixed periodic loop, but the backend may also push extra UI-only metric snapshots on meaningful audio/overlap state changes.

**Rationale**: Keeps analytics history/coaching on a predictable cadence while letting the tutor UI react faster to speaking-state and interruption changes. Even if video degrades to 1 FPS or gaze becomes unavailable, the metrics snapshot still emits using the latest available data. Audio metrics are always available.

### Live Tutor UI Should Stay Minimal
**Decision**: The tutor session page should default to a minimal, low-distraction live overlay. Detailed metrics and visual diagnostics belong behind an explicit debug toggle, while students should continue to see none of them.

**Rationale**: The product goal is a real tutoring session, not a dashboard covering the call. Live metrics should support the tutor quietly in the background; richer diagnostics, historical trends, AI improvement guidance, and future practice/training flows belong in debug/admin/post-session views where they do not compete with the student conversation.

### Energy Metric: Audio-Primary
**Decision**: Composite energy score weighted as 0.5 * RMS + 0.3 * speech_rate_variance + 0.2 * expression_valence.

**Rationale**: Audio is more reliable and always available. Expression valence from facial landmarks is a weak secondary signal. The weighting reflects this reliability difference.

### Categorical Attention-State Model
**Decision**: Use a six-state visual-attention model for live tutoring UX: `FACE_MISSING`, `LOW_CONFIDENCE`, `CAMERA_FACING`, `SCREEN_ENGAGED`, `DOWN_ENGAGED`, `OFF_TASK_AWAY`.

**Rationale**: Raw eye-contact percentage was too blunt. The tutor needs to distinguish “off camera,” “can’t tell,” “looking at the screen,” and “looking down but plausibly engaged” so live nudges and overlays stay more precise and less annoying.

### Frame Rate: 3 FPS Default
**Decision**: Capture and process video at 3 FPS, adaptive down to 1 FPS.

**Rationale**: Sufficient for engagement metrics (eye contact, expression). Higher FPS would consume more CPU without meaningful accuracy improvement. Stays within latency budget with degradation path.
