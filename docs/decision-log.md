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

### LiveKit as Default Media Plane (Supersedes Custom WebRTC)
**Decision**: Replace the custom WebRTC signaling implementation with LiveKit as the sole media transport. The legacy `usePeerConnection.ts` hook has been deleted and WebRTC signal relay removed from the backend websocket handler.

**Rationale**: LiveKit provides production-grade SFU infrastructure (TURN, bandwidth estimation, reconnect, codec negotiation) that would take months to build in-house. For 1:1 tutoring, we configure H.264 with simulcast disabled and higher bitrate tiers (up to 4.5 Mbps at 1080p) since all bandwidth goes to a single layer.

**Key configuration choices**:
- H.264 default codec: hardware encode/decode gives better quality-per-bit
- Simulcast disabled: no benefit for 1:1 — send one HD layer
- Bitrate: 2.5 Mbps (720p), 4.5 Mbps (1080p), vs LiveKit's 3 Mbps default

**Trade-offs**: Hard dependency on LiveKit infrastructure (local dev server or cloud). `livekit==0.18.3` pinned for protobuf<4 compatibility with mediapipe.

### Server-Side LiveKit Analytics Worker
**Decision**: Analytics processing (video frames, audio) is done by a server-side worker that subscribes to LiveKit room tracks, rather than the browser uploading analytics data via WebSocket.

**Rationale**: Eliminates double-bandwidth (media to SFU + analytics upload to backend). The worker joins with `hidden=True`, `canPublish=False`, `canSubscribe=True` so participants don't see it. When connected, the frontend stops sending analytics uploads.

**Data path**: Worker publishes metrics and nudges back to the tutor via LiveKit data packets (`lsa.metrics.v1` lossy, `lsa.nudge.v1` reliable), with WebSocket fallback if data packet send fails.

### Energy Removed as Live Nudge (Post-Session Only)
**Decision**: Remove `energy_drop` from the live coaching rules. Energy drops are now only surfaced as post-session flagged moments.

**Rationale**: User reported a false energy nudge during a lecture where a quiet-but-attentive student scored low on vocal energy (RMS ~0, rate variance ~0). In lecture mode, silent listening is correct behavior. Energy is too ambiguous for live coaching — it conflates low participation with low engagement. Post-session, an energy drop can be contextualized with the full session arc.

**Consensus**: Both GPT-4 and Claude agreed that energy is a supporting/post-session signal, not a standalone live nudge.

### Session-Type Profiles for Live Coaching
**Decision**: Coaching thresholds are parameterized by session type (`lecture`, `practice`, `socratic`, `general`, `discussion`). Each profile defines overtalk ceiling, silence threshold, off-task persistence, and applicable nudge rules.

**Rationale**: A tutor at 85% talk time is normal in a lecture but problematic in practice. A student silent for 180s is fine in a lecture but concerning in discussion. The same absolute thresholds cannot work across session types.

**Profile examples**:
- `lecture`: overtalk ceiling 0.92, silence threshold 300s, off-task 120s
- `practice`: overtalk ceiling 0.55, silence threshold 60s, off-task 45s
- `socratic`: overtalk ceiling 0.65, silence threshold 45s, off-task 60s

### Persistence-Based Off-Task Detection (Not Instantaneous)
**Decision**: Replace instantaneous `low_eye_contact` check with persistence-based `student_off_task` rule. The student must be in `OFF_TASK_AWAY` or `FACE_MISSING` state for longer than the profile's `off_task_seconds` threshold before a nudge fires.

**Rationale**: A momentary glance away is normal. Persistence-based detection (75s for general, 45s for practice) dramatically reduces false positives. The `AttentionStateTracker` tracks state transitions and durations with `time_in_current_state()`.

### Selective Visual-Confidence Suppression
**Decision**: Only rules that have `requires_visual_confidence=True` are gated by the visual confidence threshold (< 0.4). Audio-based rules (interruptions, tech check) are never suppressed by poor visual data.

**Rationale**: A blanket global suppress on all rules when camera confidence is low would disable the entire coaching system whenever the student covers their camera. Audio rules like `let_them_finish` and `tech_check` don't depend on visual data and should always run.

### Composite Check-for-Understanding Rule
**Decision**: Replace separate `tutor_overtalk` and `student_silence` rules with a single `check_for_understanding` rule that fires when the tutor's recent talk percentage exceeds the profile's overtalk ceiling.

**Rationale**: The profile-aware overtalk ceiling already encodes session-type norms, making the rule both simpler and more precise. One well-tuned rule is better than two overlapping ones.

---

## Authentication Decisions

### Backend-Authoritative Authentication (Not Frontend-Only)
**Decision**: User identity and JWT issuance are handled entirely by the FastAPI backend (`app/auth/`). The frontend (NextAuth.js) delegates all credential validation and token minting to backend endpoints; it never stores raw passwords or issues tokens on its own.

**Rationale**: Backend-authoritative auth ensures that any API call—from browsers, curl, tests, or future native clients—goes through the same identity pipeline. Frontend-only auth (e.g., JWT issued by NextAuth from a secrets-only config) creates a divergent identity model where the backend cannot independently verify who is making API calls. Keeping the source of truth in the backend also makes it straightforward to add role checks, audit logs, and token revocation later.

**Trade-offs**: Adds one round-trip for NextAuth's CredentialsProvider (browser → NextAuth API route → backend). This is negligible for auth flows and not on the hot path.

### SQLite for User Store (Not Postgres or an External Service)
**Decision**: User accounts are stored in a SQLite database (`data/auth.db`) managed directly by the backend using the standard library `sqlite3` module.

**Rationale**: Consistent with the existing project philosophy of minimal external dependencies (JSON file session storage, no database for analytics). SQLite handles concurrent reads well and supports the expected pilot-scale traffic (one tutor per server instance). The auth DB path is configurable (`LSA_AUTH_DB_PATH`) so it can be replaced with a Postgres connection string when the product grows. No ORM is introduced — raw SQL with parameterised queries keeps the dependency footprint small and the behaviour auditable.

**Alternatives considered**: Postgres (deferred: adds an infra dependency before it's needed), Auth0/Clerk (deferred: adds a vendor dependency and billing complexity for a pilot system).

### NextAuth.js (Auth.js v5) as the Frontend Auth Layer
**Decision**: The frontend uses NextAuth.js as the session/cookie management layer, with two providers: Google (OAuth) and Credentials (email/password and guest token). NextAuth does not issue its own JWTs for API calls; instead, it stores the backend-issued access token inside the NextAuth session and forwards it on every API request via an `Authorization: Bearer` header.

**Rationale**: NextAuth is the standard auth library for Next.js and handles the OAuth callback complexity, CSRF protection, session cookies, and the credentials form pattern out of the box. Using it as a thin wrapper around the backend identity system gives a production-quality auth UI without building PKCE flows from scratch. The pattern of storing an external token inside a NextAuth session is explicitly documented in the NextAuth ecosystem.

**Trade-offs**: NextAuth adds ~4 npm packages and a `/api/auth/[...nextauth]` route. The session object has a slightly non-standard shape (adds a `backendToken` field). These are minor and well-understood.

### Guest Accounts for Low-Friction Student Join
**Decision**: Students can join a session by clicking the student link without creating a full account. The frontend auto-creates a guest account via `POST /api/auth/guest` (backed by the auth router), which returns a short-lived access token and an anonymous user identity. Guests can optionally upgrade to a full account (email/password or Google) after the session.

**Rationale**: Requiring students to register before joining a tutoring session would significantly increase abandonment and friction. The session-token model (tutor shares a `student_token` link) already implies a trusted join path; the guest auth layer adds a server-side identity to that join so the student's participation is attributable (to the anonymous guest ID) in post-session analytics. Guest identity cleanup is not yet implemented; a periodic deletion job for inactive guest accounts is planned as future work.

**Privacy note**: Guest accounts are assigned a random UUID and an optional display name. No email or password is stored. If the guest later signs in with Google or creates an account, session history is not currently migrated across (future work).

### Separation of User Auth from Session Auth
**Decision**: The existing per-session `tutor_token` / `student_token` system is retained and operates independently of user-level auth. Session creation requires a valid user JWT; session joining (via the student token link) works with a guest JWT. The two token types serve different purposes and have different lifetimes.

**Rationale**: Session tokens are short-lived, role-specific, and tied to a single session room. They are the right granularity for WebSocket auth and LiveKit room access. User JWTs are longer-lived, identity-scoped, and used for REST API calls (analytics listing, session creation). Merging the two would require session tokens to carry full identity claims, complicating the analytics query model and making token revocation harder. Keeping them separate also means the analytics worker can still join rooms with a server-side LiveKit token that carries no user identity.

---

## AI Conversational Intelligence Decisions

### AssemblyAI Universal Streaming v3 as Primary STT
**Decision**: Use AssemblyAI's Universal Streaming v3 (`wss://streaming.assemblyai.com/v3/ws`, model `u3-rt-pro`) instead of Deepgram.

**Rationale**: Deepgram had login/account issues during integration. AssemblyAI v3 uses `TurnEvent` with `end_of_turn` semantics, raw PCM binary frames (no base64), and provides server-side VAD/endpointing — meaning we send all audio continuously and let the provider handle silence detection rather than filtering locally.

**Trade-offs**: AssemblyAI requires 50-1000ms of audio per WebSocket message (we buffer to 100ms internally). The v2 endpoint was deprecated (HTTP 410) so v3 is the only option.

### Continuous Audio Streaming (No Local VAD Gating)
**Decision**: Send ALL audio frames to the STT provider, not just frames where local VAD detects speech.

**Rationale**: Production STT systems (AssemblyAI, Deepgram, Google) expect continuous audio streams. Local VAD gating strips natural pauses and context, making the provider's built-in neural VAD perform worse. Quiet speech was being missed because `webrtcvad` at aggressiveness=3 classified it as silence before it reached AssemblyAI.

**Trade-offs**: Slightly higher STT billing (~$0.36/session instead of $0.18) since silence audio is sent. The quality improvement is substantial.

### Dual-Model LLM Architecture
**Decision**: Use two different models for coaching — Gemini 2.5 Flash for on-demand suggestions and Claude 3.5 Haiku for auto-suggestions.

**Rationale**: Benchmarked 6 models on OpenRouter. Gemini 2.5 Flash has ~540ms TTFB / ~1.4s total vs Haiku's ~980ms TTFB / ~2.8s total. When the tutor clicks "AI Suggest", they're waiting — speed matters. Auto-suggestions fire in the background every 35s, so quality matters more than speed. Both produce valid JSON output.

**Trade-offs**: Two model configurations to maintain. Gemini wraps JSON in markdown fences (`\`\`\`json`), requiring fence-stripping in the parser.

### SSE Streaming for On-Demand Suggestions
**Decision**: The `/suggest` endpoint returns Server-Sent Events when the client sends `Accept: text/event-stream`, streaming LLM tokens as they arrive.

**Rationale**: Reduces perceived latency for the tutor. The first tokens arrive in ~400ms even though total response takes ~1.4s. The frontend shows a loading indicator and pops the final parsed suggestion when complete.

### Speakable Suggested Prompts
**Decision**: The LLM prompt explicitly requires `suggested_prompt` to be a complete, natural sentence the tutor can read word-for-word to the student.

**Rationale**: The most valuable AI output is something the tutor can glance at and say immediately. Generic coaching notes ("ask about fractions") are less useful than speakable prompts ("Can you tell me what the 3 and 4 in three-fourths represent?").

### Sessions Are Invite-Link Only
**Decision**: Removed the manual "Join Session" form (session ID + token input) from the dashboard. Students join only via invite links shared by the tutor.

**Rationale**: The manual join form required a session token that users had no easy way to obtain. The invite link already embeds the token. Removing the form simplifies the UX and eliminates a confusing dead-end.
