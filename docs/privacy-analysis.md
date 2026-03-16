# Privacy Analysis

## Data Flow

### What Is Captured
- **Video**: Webcam frames from both tutor and student (JPEG-encoded, 320x240)
- **Audio**: Microphone input from both participants (16-bit PCM, 16kHz)

### What Is Processed
All video and audio data is processed **in memory** and **immediately discarded** after analysis. Depending on feature flags, the system extracts:
- Face landmarks (468+ points from MediaPipe FaceMesh)
- Iris position for gaze estimation
- Mouth/eyebrow distances for expression valence
- Voice activity detection (speech/silence binary)
- RMS energy and zero-crossing rate from audio
- Real-time speech transcripts for tutor-visible live transcription and downstream AI coaching / post-session analytics features when transcription is enabled

### What Is Stored
Stored data depends on which conversational-intelligence features are enabled.

**Baseline storage** persists only derived numeric metrics and text summaries as JSON files:
- Per-participant averages (eye contact score, talk time percentage, energy score)
- Session-level metrics (engagement score, interruption count, engagement trend)
- Timeline arrays (numeric values over time)
- Flagged moments (timestamp + description)
- Coaching nudges that were sent
- Recommendations (text strings)

**When transcript storage is enabled**, finalized transcript text may also be retained for post-session analytics and summaries.

**No video, raw audio, images, or recordings are ever stored.**

## Consent Model
Both tutor and student see a consent modal before camera/mic activation. The modal explains:
- What is analyzed (facial engagement, voice activity, and real-time transcription when enabled)
- What is stored (numeric metrics by default; transcript text only when transcript storage is enabled; no recordings)
- Who sees what (coaching nudges and live transcripts are visible only to the tutor)
- Whether AI coaching suggestions may be generated from transcript text when AI coaching is enabled

Camera and microphone access is only requested after explicit consent.

## Data Visibility
- **Tutor sees**: Live call UI, minimal live coaching overlay, coaching nudges, optional live transcript panel when transcription is enabled, optional debug panel with coaching decisions (candidates, suppressed reasons, trigger features), and post-session analytics
- **Student sees**: Live call UI and their own local/remote media, but no tutor metrics, nudges, live transcripts, or coaching decisions
- **Coaching nudges**: Sent only to the tutor via targeted LiveKit data packets (`destination_identities`), with WebSocket fallback — never to the student
- **Live transcripts**: Sent only to the tutor in real time; they are not shown to the student
- **Coaching decisions**: The debug panel shows which rules were evaluated, which were suppressed and why, and what metric values triggered the evaluation. This is tutor-only and off by default.

## Deployment Considerations
- **Local deployment** (docker-compose on tutor's machine): analytics media stays on that machine. LiveKit server runs locally; all media flows through localhost.
- **Remote server deployment**: video/audio traverse the network to the LiveKit SFU and backend analytics worker. Raw media frames are processed in memory and never stored. The analytics worker joins the LiveKit room with `hidden=True` — participants cannot see it in the room roster. Metrics and nudges are sent back via LiveKit data packets (targeted to the tutor only).

### LiveKit Worker Privacy
The server-side analytics worker:
- Subscribes to **both** participant tracks (video + audio) for metrics computation
- Processes frames in memory and discards them immediately
- Publishes metrics to the **tutor only** via `destination_identities` — the student never receives coaching data
- Joins with `hidden=True, agent=True` — invisible to participants
- Does not record, store, or forward raw media

## No Third-Party APIs
All ML inference runs locally via MediaPipe and webrtcvad. The app does not send analytics data to third-party ML APIs. LiveKit can run locally (via `livekit-server` binary) or via LiveKit Cloud — the choice affects where media is routed and should be disclosed to users.

## Data Retention
Session JSON files have a configurable retention period (default 90 days). Files are stored in `data/sessions/` and can be manually deleted at any time.

The current implementation runs expired-session cleanup on server startup. It does **not** yet run periodic cleanup for long-lived server processes.

## User Account Data

### What Is Stored for Authenticated Users
The system now supports user accounts (tutor and student). The following data is stored in `data/auth.db` (SQLite):

| Field | Notes |
|-------|-------|
| `id` | Random UUID, primary key |
| `email` | Lowercased, trimmed. Only present for email/password accounts. |
| `name` | Display name provided at registration. |
| `role` | `tutor` or `student` |
| `google_id` | Google account sub-ID. Only present for Google sign-in users. |
| `avatar_url` | Public Google profile picture URL. Only for Google sign-in users. |
| `is_guest` | `true` for anonymous guest accounts. |
| `password_hash` | PBKDF2-HMAC-SHA256 hash (260,000 iterations, random 32-byte salt, OWASP 2023 recommendation). **Never stored for Google or guest accounts.** |
| `created_at` / `updated_at` | ISO 8601 timestamps. |

**Raw passwords are never stored.** Passwords are hashed with PBKDF2-HMAC-SHA256 using a random 32-byte salt and 260,000 iterations (the OWASP 2023 recommendation for PBKDF2-SHA256). Constant-time comparison is used during verification to prevent timing attacks.

### Guest Accounts
Guest accounts are created automatically when a student joins via a student-token link without an existing account. They have:
- No email, no password
- An optional display name (may be blank)
- A randomly generated UUID identity

Guest account data is retained for **30 days of inactivity** then eligible for deletion. Guest session history is associated with the guest UUID; if the guest upgrades to a full account, history is not automatically migrated (future work).

### Google OAuth Data
When a user signs in with Google:
- The Google `sub` ID is stored (used to recognise returning users)
- The user's display name and profile picture URL from Google are stored
- No Google OAuth tokens (access token, refresh token) are stored server-side
- The frontend exchanges the Google ID token with the backend in a single request; the ID token itself is not persisted

### JWT Access Tokens
Backend-issued JWTs (`LSA_JWT_SECRET`) are:
- Short-lived (default 24 hours, configurable via `LSA_JWT_EXPIRY_HOURS`)
- Signed with HMAC-SHA256
- Not stored server-side (stateless)
- Scoped to user identity (`sub`, `role`)

No refresh token mechanism exists in the current implementation; users re-authenticate when the JWT expires.

### Data Visibility and Separation
- **Tutors** can query their own session history filtered by their user ID
- **Students** can query sessions they participated in (identified by `student_user_id`)
- **Neither side** can see the other's account data via the API
- **Coaching nudges and metrics** remain tutor-only regardless of auth state

## Recommendations for Production
1. Use WSS (WebSocket Secure) for encrypted transport
2. ~~Add authentication beyond session tokens~~ — user-level auth is now implemented (email/password, Google OAuth, guest)
3. Implement automatic data retention cleanup (periodic job for expired sessions and inactive guest accounts)
4. Consider GDPR/CCPA compliance: implement a user data export endpoint and a right-to-erasure flow for registered accounts
5. Add audit logging for sensitive data access (session analytics queries, auth events)
6. Rotate `LSA_JWT_SECRET` and `AUTH_SECRET` (NextAuth) before any production deployment; use a secrets manager rather than env vars in plaintext compose files
7. Consider adding refresh tokens if 24-hour JWT expiry is too short for tutors who run long sessions

## Third-Party AI Services

When AI Conversational Intelligence features are enabled, session data flows to external services:

### Speech-to-Text (AssemblyAI)
- **What is sent**: Raw PCM audio frames (16-bit, 16kHz mono) streamed over WebSocket
- **What is returned**: Transcribed text with word timestamps and confidence scores
- **Data retention**: AssemblyAI processes audio in real-time and does not retain audio after the session ends (per their streaming API terms)
- **Opt-out**: AssemblyAI Universal Streaming v3 does not currently offer a model-improvement opt-out flag (unlike Deepgram's `mip_opt_out`)

### LLM Coaching (OpenRouter → Anthropic / Google)
- **What is sent**: PII-scrubbed transcript text, session metrics (talk ratios, uncertainty scores, engagement), and a system prompt. No raw audio or video.
- **PII scrubbing**: Applied before every LLM call — regex-based removal of emails, phone numbers, names, addresses, and other PII patterns
- **What is returned**: JSON coaching suggestions (action, observation, suggested prompt)
- **Data retention**: OpenRouter is a pass-through router; data retention depends on the downstream model provider (Anthropic, Google). Neither retains API inputs for model training by default for API customers.

### Mitigation Measures
1. **Feature flags**: All AI features are disabled by default. Each tier can be enabled independently.
2. **PII scrubbing**: Applied to all LLM prompts before transmission
3. **Budget limits**: Hard ceiling of 60 LLM calls per session-hour
4. **Consent**: Users see an updated consent modal when transcription is enabled, explaining that audio will be processed by an external speech-to-text service
5. **Transcript deletion**: `DELETE /api/analytics/sessions/{id}/transcript` removes stored transcript data
6. **No recording**: Raw audio is never stored — only derived text transcripts (when transcript storage is enabled)
