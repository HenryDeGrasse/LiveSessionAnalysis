# Privacy Analysis

## Data Flow

### What Is Captured
- **Video**: Webcam frames from both tutor and student (JPEG-encoded, 320x240)
- **Audio**: Microphone input from both participants (16-bit PCM, 16kHz)

### What Is Processed
All video and audio data is processed **in memory** and **immediately discarded** after analysis. The system extracts:
- Face landmarks (468+ points from MediaPipe FaceMesh)
- Iris position for gaze estimation
- Mouth/eyebrow distances for expression valence
- Voice activity detection (speech/silence binary)
- RMS energy and zero-crossing rate from audio

### What Is Stored
**Only derived numeric metrics and text summaries** are persisted as JSON files:
- Per-participant averages (eye contact score, talk time percentage, energy score)
- Session-level metrics (engagement score, interruption count, engagement trend)
- Timeline arrays (numeric values over time)
- Flagged moments (timestamp + description)
- Coaching nudges that were sent
- Recommendations (text strings)

**No video, audio, images, or recordings are ever stored.**

## Consent Model
Both tutor and student see a consent modal before camera/mic activation. The modal explains:
- What is analyzed (facial engagement, voice activity)
- What is stored (only numeric metrics, no recordings)
- Who sees what (coaching nudges visible only to tutor)

Camera and microphone access is only requested after explicit consent.

## Data Visibility
- **Tutor sees**: Live call UI, minimal live coaching overlay, coaching nudges, optional debug panel with coaching decisions (candidates, suppressed reasons, trigger features), and post-session analytics
- **Student sees**: Live call UI and their own local/remote media, but no tutor metrics, nudges, or coaching decisions
- **Coaching nudges**: Sent only to the tutor via targeted LiveKit data packets (`destination_identities`), with WebSocket fallback — never to the student
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

## Recommendations for Production
1. Use WSS (WebSocket Secure) for encrypted transport
2. Add authentication beyond session tokens
3. Implement automatic data retention cleanup
4. Consider GDPR/CCPA compliance for user data rights
5. Add audit logging for data access
