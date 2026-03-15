# API Reference

## REST Endpoints

### Health Check
```
GET /health
```
Returns server status and MediaPipe readiness.

**Response:**
```json
{"status": "ok", "mediapipe_loaded": true}
```

### Create Session
```
POST /api/sessions
```
Creates a new tutoring session with unique tokens for tutor and student.

**Request Body (optional):**
```json
{
  "tutor_id": "tutor-abc",
  "session_type": "general",
  "media_provider": "custom_webrtc"
}
```

Notes:
- `media_provider` currently supports `custom_webrtc` and `livekit`
- if omitted, the backend uses the configured default media provider
- `livekit` creation is rejected unless LiveKit support is enabled/configured on the backend

**Response:**
```json
{
  "session_id": "abc123",
  "tutor_token": "tutor_token_value",
  "student_token": "student_token_value",
  "media_provider": "custom_webrtc",
  "livekit_room_name": null
}
```

### Session Info
```
GET /api/sessions/{session_id}/info
GET /api/sessions/{session_id}/info?token=...
```
Returns current session state (connection status, elapsed time). If a valid token is provided, the resolved role is included.

**Response:**
```json
{
  "session_id": "abc123",
  "tutor_connected": true,
  "student_connected": false,
  "started": false,
  "ended": false,
  "elapsed_seconds": 0.0,
  "role": "tutor",
  "media_provider": "custom_webrtc",
  "livekit_room_name": null
}
```

### Create LiveKit Join Token
```
POST /api/sessions/{session_id}/livekit-token?token=...
```
Creates a short-lived LiveKit room join token for the caller's resolved role.

Notes:
- requires a valid tutor or student session token
- only works for sessions created with `media_provider=livekit`
- returns `400` if the session is not configured for LiveKit or LiveKit is not enabled/configured on the backend

**Response:**
```json
{
  "url": "ws://localhost:7880",
  "room_name": "lsa-abc123",
  "identity": "abc123:tutor",
  "token": "livekit_join_jwt",
  "expires_at": 1760000000
}
```

### End Session
```
POST /api/sessions/{session_id}/end?token=...
```
Ends a live session immediately when called with a valid tutor or student token. Connected participants receive a `session_end` websocket message and the sockets are closed normally.

**Response:**
```json
{
  "status": "ended",
  "session_id": "abc123",
  "ended": true,
  "ended_by": "tutor"
}
```

### List Sessions (Analytics)
```
GET /api/analytics/sessions?tutor_id=xxx&last_n=10
```
Lists stored session summaries. Optional filters by tutor_id and count.

**Response:** Array of SessionSummary objects.

### Get Session Detail
```
GET /api/analytics/sessions/{session_id}
```
Returns full session detail including timeline data and flagged moments.

**Response:** SessionSummary object with timeline arrays.

### Get Recommendations
```
GET /api/analytics/sessions/{session_id}/recommendations
```
Returns coaching recommendations for a specific session.

**Response:** Array of recommendation strings.

### Get Trends
```
GET /api/analytics/trends?tutor_id=xxx&last_n=10
GET /api/analytics/trends?last_n=10
```
Returns cross-session trend data for a tutor. If `tutor_id` is omitted, the backend falls back to the most recent stored sessions across the demo data set.

**Response:**
```json
{
  "tutor_id": "xxx",
  "sessions": [...],
  "trends": {
    "engagement": "improving",
    "student_eye_contact": "stable",
    "interruptions": "declining",
    "talk_time_balance": "improving"
  }
}
```

### Debug Latency
```
GET /api/debug/latency?session_id=xxx
```
Returns latency statistics for a live session, including rolling averages for total processing, decode, FaceMesh, gaze, expression, and aggregation time.

### Debug Stats
```
GET /api/debug/stats?session_id=xxx
```
Returns comprehensive debug stats including connection status, nudge count, and metrics snapshot count.

## WebSocket Protocol

### Connection
```
WS /ws/session/{session_id}?token={token}
```
Connect with the token received from session creation. Token determines role (tutor/student).

### Client -> Server (Binary)
- `0x01` + JPEG bytes: Video frame
- `0x02` + PCM bytes: Audio chunk (PCM 16-bit, 16kHz, 30ms = 960 bytes)

### Client -> Server (JSON)
Small control/status messages and WebRTC signaling may also be sent over the same authenticated session websocket.

Client status example:
```json
{
  "type": "client_status",
  "data": {
    "audio_muted": true,
    "video_enabled": false,
    "tab_hidden": false
  }
}
```

WebRTC signaling example:
```json
{
  "type": "webrtc_signal",
  "data": {
    "signal_type": "offer",
    "payload": {
      "type": "offer",
      "sdp": "v=0..."
    }
  }
}
```

Notes:
- text/JSON websocket frames are used for signaling and small control messages
- binary websocket frames continue to carry analytics media payloads
- supported `signal_type` values are `offer`, `answer`, and `ice_candidate`

These signals help the backend suppress false speech/interruption detections when the browser has intentionally muted audio or disabled video, while also relaying peer-call setup messages between tutor and student.

### Server -> Client (JSON)
Tutor-facing analytics messages:
```json
{"type": "metrics", "data": MetricsSnapshot}
{"type": "nudge", "data": Nudge}
```

Participant/call state messages:
```json
{"type": "participant_ready", "data": {"session_id": "...", "role": "student", "reconnected": false}}
{"type": "participant_disconnected", "data": {"session_id": "...", "role": "student", "grace_seconds": 10}}
{"type": "participant_reconnected", "data": {"session_id": "...", "role": "student"}}
{"type": "webrtc_signal", "data": {"session_id": "...", "from_role": "tutor", "signal_type": "offer", "payload": {...}}}
```

Session end message (sent to any still-connected participant when the session truly ends):
```json
{"type": "session_end", "data": {"session_id": "...", "duration_seconds": 300}}
```

## Data Models

### MetricsSnapshot
```json
{
  "timestamp": "2025-01-01T00:00:00",
  "session_id": "abc123",
  "tutor": {
    "eye_contact_score": 0.8,
    "talk_time_percent": 0.6,
    "energy_score": 0.7,
    "energy_drop_from_baseline": 0.05,
    "is_speaking": false,
    "attention_state": "CAMERA_FACING",
    "attention_state_confidence": 0.92,
    "face_presence_score": 1.0,
    "visual_attention_score": 1.0
  },
  "student": {
    "eye_contact_score": 0.5,
    "talk_time_percent": 0.4,
    "energy_score": 0.6,
    "energy_drop_from_baseline": 0.12,
    "is_speaking": true,
    "attention_state": "SCREEN_ENGAGED",
    "attention_state_confidence": 0.81,
    "face_presence_score": 1.0,
    "visual_attention_score": 0.85
  },
  "session": {
    "interruption_count": 2,
    "recent_interruptions": 0,
    "hard_interruption_count": 1,
    "recent_hard_interruptions": 1,
    "backchannel_overlap_count": 1,
    "recent_backchannel_overlaps": 1,
    "echo_suspected": false,
    "active_overlap_duration_current": 0.0,
    "active_overlap_state": "none",
    "tutor_cutoffs": 1,
    "student_cutoffs": 0,
    "silence_duration_current": 0.0,
    "time_since_student_spoke": 0.0,
    "mutual_silence_duration_current": 0.0,
    "tutor_monologue_duration_current": 12.4,
    "tutor_turn_count": 8,
    "student_turn_count": 6,
    "student_response_latency_last_seconds": 0.8,
    "tutor_response_latency_last_seconds": 0.3,
    "recent_tutor_talk_percent": 0.55,
    "engagement_trend": "stable",
    "engagement_score": 75.0
  },
  "degraded": false,
  "gaze_unavailable": false,
  "server_processing_ms": 45.2,
  "target_fps": 3
}
```

Notes:
- `eye_contact_score` is a raw camera-facing ratio (`0.0` to `1.0`).
- `attention_state` is the higher-level visual-attention classifier: `FACE_MISSING`, `LOW_CONFIDENCE`, `CAMERA_FACING`, `SCREEN_ENGAGED`, `DOWN_ENGAGED`, `OFF_TASK_AWAY`.
- `visual_attention_score` is a coarse state-derived score used for engagement/coaching when the classifier has enough evidence.
- `attention_state_confidence` indicates how trustworthy the current categorical state is.
- `silence_duration_current` and `time_since_student_spoke` currently describe the student's ongoing silence timer.
- `mutual_silence_duration_current` tracks how long both participants have been silent simultaneously.
- `tutor_monologue_duration_current` tracks an ongoing uninterrupted tutor explanation streak while the student is silent.
- `student_response_latency_last_seconds` / `tutor_response_latency_last_seconds` capture the last observed response gap after the other speaker stopped.
- `interruption_count` is broader than `hard_interruption_count`; live coaching should prefer the hard/cutoff fields when trying to avoid false positives.
- `active_overlap_state` / `active_overlap_duration_current` exist so the tutor UI can react before an overlap fully ends.
- `backchannel_overlap_count` tracks short/cooperative overlaps that should usually not trigger a live nudge.
- `echo_suspected` indicates the backend has seen repeated quiet overlap patterns consistent with bleed/echo rather than real conversational interruption.

### Nudge
```json
{
  "id": "uuid",
  "timestamp": "2025-01-01T00:05:00",
  "nudge_type": "student_silence",
  "message": "Student has been quiet for a while. Try asking an open-ended question.",
  "priority": "medium",
  "trigger_metrics": {"student_talk_time_percent": 0.02}
}
```

---

## AI Conversational Intelligence Endpoints

These endpoints are part of the AI Conversational Intelligence system. They require the corresponding feature flags to be enabled (see `.env.example`).

### On-Demand AI Coaching Suggestion
```
POST /api/sessions/{session_id}/suggest?token={tutor_token}
```
Tutor-initiated request for an AI coaching suggestion. Bypasses the normal interval gating but respects the hourly budget (`LSA_AI_COACHING_MAX_CALLS_PER_HOUR`).

**Requires:** `LSA_ENABLE_TRANSCRIPTION=true`, `LSA_ENABLE_AI_COACHING=true`, valid LLM API key.

**Auth:** Tutor session token or authenticated user with tutor role.

**Response (200):**
```json
{
  "status": "ok",
  "suggestion": {
    "id": "ai-sug-123456abcdef",
    "action": "probe_understanding",
    "topic": "integration",
    "observation": "Student sounds uncertain about the relationship between derivatives and integrals",
    "suggestion": "Ask the student to explain how an integral reverses differentiation in their own words.",
    "suggested_prompt": "Can you walk me through how integrals and derivatives are connected?",
    "priority": "medium",
    "confidence": 0.85
  },
  "calls_remaining": 29
}
```

**Error Responses:**
- `404` — Session not found
- `403` — Not authorized (non-tutor role)
- `429` — Hourly budget exhausted
- `503` — AI coaching not configured or provider unavailable

### Suggestion Feedback
```
POST /api/sessions/{session_id}/suggestion-feedback?token={tutor_token}
```
Submit tutor feedback on a coaching suggestion for evaluation dataset construction.

**Request Body:**
```json
{
  "suggestion_id": "uuid",
  "helpful": true,
  "comment": "Good suggestion, student engaged more after I used it"
}
```

**Auth:** Tutor session token or authenticated user.

**Response (200):**
```json
{
  "status": "ok",
  "session_id": "abc123",
  "suggestion_id": "ai-sug-123456abcdef",
  "helpful": true
}
```

**Error Responses:**
- `404` — Session not found
- `403` — Not authorized

### Post-Session AI Summary
```
POST /api/sessions/{session_id}/ai-summary?token={token}
```
Generates a post-session AI summary from the stored transcript. Can be called after the session ends.

**Requires:** `LSA_ENABLE_AI_SESSION_SUMMARY=true`, `LSA_ENABLE_TRANSCRIPT_STORAGE=true`, valid LLM API key.

**Auth:** Tutor session token or authenticated user matching the tutor.

**Response (200):**
```json
{
  "status": "ok",
  "summary": {
    "topics_covered": ["integration", "u-substitution", "chain rule"],
    "key_moments": [
      {
        "timestamp": 812.4,
        "label": "student_breakthrough",
        "description": "Student connected substitution to the chain rule"
      }
    ],
    "student_understanding_map": {
      "basic derivatives": 0.9,
      "integration by parts": 0.4
    },
    "tutor_strengths": ["clear scaffolding"],
    "tutor_growth_areas": ["check for understanding sooner"],
    "recommended_follow_up": ["Review integration by parts with more practice problems"],
    "session_narrative": "The tutor guided the student from uncertainty about substitution toward a clearer conceptual link with the chain rule."
  }
}
```

**Error Responses:**
- `404` — Session not found or no transcript available
- `403` — Not authorized
- `503` — AI summary not configured or provider unavailable

### Delete Transcript
```
DELETE /api/analytics/sessions/{session_id}/transcript
DELETE /api/sessions/{session_id}/transcript
```
Deletes transcript data for a session from both Postgres and S3/R2 storage. Both paths resolve to the same handler.

**Auth:** Authenticated owner of the session required.

**Response:** `204 No Content` on success.

**Error Responses:**
- `401` — Authentication required
- `403` — Not authorized for this session
- `404` — Session not found
