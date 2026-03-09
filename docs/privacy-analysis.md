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
- **Tutor sees**: Live call UI, minimal live coaching overlay, coaching nudges, optional debug-only live metrics, and post-session analytics
- **Student sees**: Live call UI and their own local/remote media, but no tutor metrics or nudges
- **Coaching nudges**: Sent only to the tutor's WebSocket connection, never to the student

## Deployment Considerations
- **Local deployment** (docker-compose on tutor's machine): analytics media stays on that machine; peer-call media may stay local/direct when both participants are on the same network/browser environment.
- **Remote server deployment**: analytics video/audio traverse the network to the backend and are never stored. Peer-call media is negotiated with WebRTC and may flow directly between participants or through TURN infrastructure depending on ICE configuration. Document this distinction clearly for users.

## No Third-Party APIs
All ML inference runs locally via MediaPipe and webrtcvad. The app does not send analytics data to third-party ML APIs. However, WebRTC ICE configuration may rely on external STUN/TURN servers in production, which is a separate network dependency and should be disclosed accurately.

## Data Retention
Session JSON files have a configurable retention period (default 90 days). Files are stored in `data/sessions/` and can be manually deleted at any time.

The current implementation runs expired-session cleanup on server startup. It does **not** yet run periodic cleanup for long-lived server processes.

## Recommendations for Production
1. Use WSS (WebSocket Secure) for encrypted transport
2. Add authentication beyond session tokens
3. Implement automatic data retention cleanup
4. Consider GDPR/CCPA compliance for user data rights
5. Add audit logging for data access
