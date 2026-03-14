# Architecture Docs (Current State)

This document describes the **current** architecture of the project as it exists in code today.

It is meant to replace the older mental model of:

- custom websocket-signaled WebRTC as the primary media path
- browser-upload analytics as the default architecture

Those historical docs are still useful for context, but the current system is now **LiveKit-first** with a **server-side analytics worker**.

---

## 1. Executive Summary

The system is split into four practical planes:

1. **Media plane** — LiveKit carries the actual tutor↔student audio/video call.
2. **Intelligence plane** — a hidden backend worker subscribes to LiveKit room tracks and computes engagement/coaching signals.
3. **Product plane** — FastAPI owns auth, session lifecycle, websocket presence, reconnect grace handling, analytics APIs, and persistence orchestration.
4. **Storage plane** — local JSON/SQLite for development, Postgres + S3/R2 for production.

This is a deliberate move away from the earlier architecture where the browser did both:

- the live call, and
- the analytics upload path.

The new shape is closer to a production tutoring product:

- **LiveKit** handles media transport well
- the backend stays focused on **coaching logic and product semantics**
- the frontend stays focused on **call UX + tutor/student views**

---

## 2. High-Level System Diagram

```text
                     ┌──────────────────────────┐
                     │      FastAPI Backend     │
                     │--------------------------│
                     │ /api/sessions            │
                     │ /api/auth                │
                     │ /api/analytics           │
                     │ /ws/session/{id}         │
                     │ LiveKit token issuance   │
                     │ LiveKit webhook handling │
                     └─────────────┬────────────┘
                                   │
                      REST + WS    │
                                   │
        ┌──────────────────────────┴──────────────────────────┐
        │                                                     │
        ▼                                                     ▼
┌──────────────────┐                                 ┌──────────────────┐
│  Tutor Browser   │───────────── LiveKit ───────────│ Student Browser  │
│------------------│                                 │------------------│
│ Next.js session  │                                 │ Next.js session  │
│ local cam / mic  │                                 │ local cam / mic  │
│ private coach UI │                                 │ clean call UI    │
└────────┬─────────┘                                 └────────┬─────────┘
         │                                                      │
         └──────────────────────┬───────────────────────────────┘
                                │ subscribe to tracks
                                ▼
                     ┌──────────────────────────┐
                     │ Hidden LiveKit Worker    │
                     │--------------------------│
                     │ video_processor          │
                     │ audio_processor          │
                     │ metrics_engine           │
                     │ coaching_system          │
                     │ session summary / traces │
                     └──────────────────────────┘
```

### Key observation

There are **two different real-time channels** in play:

- **LiveKit** → actual audio/video + tutor-targeted data packets
- **FastAPI websocket** → presence, reconnect state, auth bootstrap, client status, and fallback transport for metrics/nudges/browser uploads

The websocket still matters, but it is no longer the media plane.

---

## 3. Core Architectural Decisions

### 3.1 LiveKit is the media plane

The frontend call transport is now LiveKit-based.

Relevant files:

- `frontend/src/hooks/useCallTransport.ts`
- `frontend/src/hooks/useLiveKitTransport.ts`
- `backend/app/livekit.py`
- `backend/app/main.py`

#### Why we chose it

**Pros**
- removes most custom WebRTC complexity from the app
- better production path for reconnects, codecs, room semantics, and TURN/SFU behavior
- easier path to future clients beyond the current web app
- tutor/student UX is now a real product call, not just analytics with media upload

**Tradeoff**
- hard dependency on LiveKit infra (local dev server or cloud)
- some legacy API/provider metadata (`custom_webrtc`) still exists even though the active call path is LiveKit-first
- media-plane debugging can shift from application logic to platform/config issues

### 3.2 Server-side analytics worker is the preferred ingest path

The hidden worker joins the LiveKit room as a subscriber and processes tutor/student tracks.

Relevant files:

- `backend/app/livekit_worker.py`
- `backend/app/session_runtime.py`
- `backend/app/livekit.py`

#### Why we chose it

**Pros**
- avoids double-uploading media from the browser in the default case
- keeps analytics logic centralized and role-aware on the server
- makes coaching delivery independent of browser-side frame/audio encoding logic
- cleaner long-term architecture than “call in LiveKit, analytics via parallel browser uploads”

**Tradeoff**
- each active room consumes backend worker CPU/memory
- backend becomes more operationally important during live sessions
- if the worker is unhealthy, analytics quality drops even if the call still works

### 3.3 Product semantics stay backend-authoritative

The backend still owns:

- session creation
- tutor/student role assignment
- session tokens
- LiveKit join token issuance
- session end/finalization
- persistence of analytics summaries and traces

Relevant files:

- `backend/app/main.py`
- `backend/app/session_manager.py`
- `backend/app/ws.py`

#### Why we chose it

**Pros**
- LiveKit handles media transport, but the app still controls product truth
- tutor/student semantics stay explicit
- analytics and auth are not coupled to client-side assumptions

**Tradeoff**
- live session state is held in-process, which limits horizontal scaling today

### 3.4 Rule-based coaching remains explicit and explainable

The coaching system is not a black-box model. It is a rule engine with session-type profiles, cooldowns, and suppression logic.

Relevant files:

- `backend/app/coaching_system/coach.py`
- `backend/app/coaching_system/rules.py`
- `backend/app/coaching_system/profiles.py`

#### Why we chose it

**Pros**
- predictable behavior
- testability / replayability
- better tutor trust and easier debugging
- easy to gate on visual confidence, degraded mode, or session type

**Tradeoff**
- lower ceiling than a well-trained learned system
- cannot personalize deeply to tutor style without more state/modeling
- requires careful threshold tuning to avoid false positives

---

## 4. Runtime Flow

## 4.1 Session creation

A tutor creates a session through `POST /api/sessions`.

The backend creates a `SessionRoom` containing:

- `session_id`
- tutor token
- student token(s)
- session type
- coaching intensity
- optional LiveKit room name
- in-memory participant state

Relevant files:

- `backend/app/main.py`
- `backend/app/session_manager.py`

### Important design choice

The app separates:

- **user identity** (JWT-authenticated user)
- **session role access** (per-session tutor/student token)

That means the session link is lightweight and role-bound, while the API layer still has real users behind it.

---

## 4.2 Session join and websocket bootstrap

When a participant opens `/session/[id]`, the frontend:

1. fetches session info
2. opens the authenticated session websocket
3. sends `user_auth` first if it has a user JWT
4. sends `client_status` updates
5. joins LiveKit with a role-aware token

Relevant files:

- `frontend/src/app/session/[id]/page.tsx`
- `frontend/src/hooks/useWebSocket.ts`
- `backend/app/ws.py`

### Why keep the websocket?

Because the websocket still carries product/session control that LiveKit alone does not replace:

- participant-ready / disconnected / reconnected messages
- reconnect grace-period semantics
- user-auth association for session summaries
- client media-state hints (`audio_muted`, `video_enabled`, `tab_hidden`)
- websocket fallback for metrics/nudges when needed
- browser-upload analytics fallback when the worker is disabled

---

## 4.3 LiveKit join path

The backend issues a LiveKit JWT through `/api/sessions/{session_id}/livekit-token`.

That payload includes:

- room name
- identity
- signed LiveKit token
- expiry

Relevant files:

- `backend/app/main.py`
- `backend/app/livekit.py`

### Identity model

LiveKit identities are explicit and session-scoped:

- tutor → `{session_id}:tutor`
- student → `{session_id}:student:{index}`
- worker → `worker:{session_id}`

This makes mapping room tracks back to product roles deterministic.

---

## 4.4 Hidden analytics worker startup

When the room is active and LiveKit analytics worker mode is enabled, the backend starts a hidden subscriber worker.

The worker:

- joins as a hidden/agent participant
- subscribes to tutor + student audio/video tracks
- converts frames/audio to the formats expected by the analytics pipeline
- feeds them into the same processing code used by the rest of the backend runtime

Relevant files:

- `backend/app/livekit_worker.py`
- `backend/app/session_runtime.py`
- `backend/app/livekit.py`

### Design tradeoff

This preserves one canonical backend analytics pipeline while letting the media source change from:

- browser-uploaded JPEG/PCM, to
- LiveKit-subscribed tracks

That was an important migration strategy because it reduced rewrite risk.

---

## 4.5 Video processing path

The video hot path lives in `backend/app/video_processor/`.

Flow:

1. decode/resize frame
2. detect face landmarks (MediaPipe FaceMesh)
3. estimate head pose
4. estimate gaze by fusing iris position + head pose
5. optionally analyze expression valence
6. emit visual observations into the metrics engine

Relevant files:

- `backend/app/video_processor/pipeline.py`
- `backend/app/video_processor/face_detector.py`
- `backend/app/video_processor/gaze_estimator.py`
- `backend/app/video_processor/head_pose.py`
- `backend/app/video_processor/expression_analyzer.py`
- `backend/app/video_processor/live_gaze_filter.py`

### Important tuning choices

- default analysis rate is **3 FPS**
- adaptive degradation can step analysis down to **1 FPS**
- gaze can be disabled before audio is ever sacrificed
- expression is treated as a weak secondary signal

### Why this matters

The architecture explicitly favors:

- live responsiveness
- CPU affordability
- explainability

over trying to do dense frame-by-frame vision analytics.

---

## 4.6 Audio processing path

The audio hot path lives in `backend/app/audio_processor/`.

Flow:

1. receive PCM from browser fallback or worker-resampled LiveKit audio
2. run `webrtcvad`
3. gate raw VAD using adaptive noise floor + zero-crossing sanity checks
4. extract prosody features (RMS, RMS dB, speech-rate proxy)
5. feed speaking state into speaking-time and interruption trackers

Relevant files:

- `backend/app/audio_processor/pipeline.py`
- `backend/app/audio_processor/vad.py`
- `backend/app/audio_processor/prosody.py`

### Why this architecture works well

Because tutor and student are already separated by track/role, the system avoids a big class of problems entirely:

- no speaker diarization
- no “who was speaking?” guesswork
- interruption tracking is based on actual per-role overlap

That is one of the strongest architectural choices in the project.

---

## 4.7 Metrics engine

The metrics engine is the bridge between raw signals and product-facing snapshots.

Relevant files:

- `backend/app/metrics_engine/engine.py`
- `backend/app/metrics_engine/attention_state.py`
- `backend/app/metrics_engine/speaking_time.py`
- `backend/app/metrics_engine/interruptions.py`
- `backend/app/metrics_engine/energy.py`
- `backend/app/metrics_engine/attention_drift.py`

It computes:

- eye-contact / visual-attention scores
- categorical attention state
- talk-time ratios
- turn counts
- response latency
- overlap classification
- energy score and energy drop
- engagement score / trend

### Snapshot cadence

- normal history snapshots → ~1 Hz (`metrics_emit_loop`)
- fast-path UI-only refreshes → on meaningful audio / overlap / attention changes

This is a good example of a **hot-path vs cold-path split**:

- history and persistence stay regular and stable
- live UI can still feel responsive

---

## 4.8 Coaching engine

The coach evaluates a small set of high-confidence live rules.

Relevant files:

- `backend/app/coaching_system/coach.py`
- `backend/app/coaching_system/rules.py`
- `backend/app/coaching_system/profiles.py`

Current rule set includes rules such as:

- `check_for_understanding`
- `student_off_task`
- `let_them_finish`
- `tech_check`
- `re_engage_silence`
- `encourage_student_response`
- `interruption_burst`
- `session_momentum_loss`

### Design principle

The system is intentionally **precision-first**.

That means:

- fewer live nudges
- more suppression logic
- heavy use of cooldowns, warmups, degraded-mode guards, and visual-confidence gating

The product bias is: **better to miss a marginal live nudge than to annoy the tutor with a wrong one**.

---

## 4.9 Tutor-only delivery

Metrics and nudges are published to the tutor via:

1. **LiveKit data packets** (preferred), targeted to the tutor identity only
2. **websocket fallback** if LiveKit data-packet delivery is unavailable

Relevant files:

- `backend/app/session_runtime.py`
- `backend/app/livekit_worker.py`
- `frontend/src/hooks/useLiveKitTransport.ts`
- `frontend/src/app/session/[id]/page.tsx`

### Why this is important

The tutor and student are deliberately seeing different products:

- **Tutor** → live call + private coaching overlay
- **Student** → clean call view only

That separation is central to the architecture.

---

## 4.10 Session finalization and persistence

When a session ends, the backend:

1. cancels the metrics loop
2. stops the LiveKit analytics worker
3. generates a `SessionSummary`
4. persists the summary
5. finalizes any session trace
6. notifies connected participants
7. cleans up in-memory processing resources

Relevant files:

- `backend/app/session_runtime.py`
- `backend/app/analytics/summary.py`
- `backend/app/analytics/session_store.py`
- `backend/app/analytics/pg_session_store.py`
- `backend/app/observability/trace_recorder.py`

---

## 5. Backend Architecture by Module

## 5.1 API / App layer

Files:

- `backend/app/main.py`
- `backend/app/models.py`

Responsibilities:

- FastAPI routing
- CORS
- health and readiness checks
- session creation and join helpers
- auth router mounting
- analytics router mounting
- LiveKit webhook endpoint

## 5.2 Live session state

Files:

- `backend/app/session_manager.py`
- `backend/app/ws.py`

Responsibilities:

- in-memory active sessions
- participant connection state
- disconnect grace tasks
- per-session trace recorder handle
- websocket presence and reconnect semantics

### Big tradeoff

This is intentionally simple and fast, but it means active room state is **not distributed**.

That is why the current production guidance is effectively **single backend instance for live sessions**.

## 5.3 Processing runtime

Files:

- `backend/app/session_runtime.py`
- `backend/app/livekit_worker.py`

Responsibilities:

- manage per-session processors
- bridge incoming media to analytics pipeline
- emit live metrics snapshots
- invoke coach
- finalize sessions cleanly

## 5.4 Analytics APIs and stores

Files:

- `backend/app/analytics/router.py`
- `backend/app/analytics/summary.py`
- `backend/app/analytics/recommendations.py`
- `backend/app/analytics/trends.py`
- `backend/app/analytics/session_store.py`
- `backend/app/analytics/pg_session_store.py`

Responsibilities:

- session lists/detail APIs
- tutor recommendations
- student-facing insights
- trend views
- local or Postgres-backed summary persistence

## 5.5 Auth

Files:

- `backend/app/auth/router.py`
- `backend/app/auth/jwt_utils.py`
- `backend/app/auth/user_store.py`
- `backend/app/auth/pg_user_store.py`

Responsibilities:

- registration/login
- guest auth
- Google auth
- backend-issued JWTs
- local SQLite or Postgres-backed user store

### Tradeoff

The backend remains the source of truth for identity, while NextAuth is used as the frontend session wrapper. That adds a small amount of integration complexity but keeps the backend authoritative.

## 5.6 Observability

Files:

- `backend/app/observability/trace_recorder.py`
- `backend/app/observability/trace_models.py`
- `backend/app/observability/trace_store.py`
- `backend/app/observability/s3_trace_store.py`

Responsibilities:

- privacy-safe session traces
- incremental NDJSON logging
- local or S3/R2-backed trace persistence
- replay/eval support

---

## 6. Frontend Architecture

## 6.1 Session page as orchestration layer

Primary file:

- `frontend/src/app/session/[id]/page.tsx`

It coordinates:

- role resolution
- consent and media acquisition
- websocket bootstrap
- LiveKit join
- local/remote video rendering
- tutor-only metrics/nudges
- session-end UX
- debug mode

This file is large because it is currently the product-level composition root for the live session experience.

## 6.2 Media transport abstraction

Files:

- `frontend/src/hooks/useCallTransport.ts`
- `frontend/src/hooks/useLiveKitTransport.ts`

Current reality:

- `useCallTransport` is effectively a compatibility wrapper
- the active implementation is `useLiveKitTransport`

### Why keep the wrapper?

Because it preserves a seam for:

- future transport swaps
- test stability
- reducing session-page coupling to one SDK

## 6.3 Websocket hook

File:

- `frontend/src/hooks/useWebSocket.ts`

Responsibilities:

- connect to session websocket
- reconnect with exponential backoff
- handle terminal close conditions
- send JSON control frames and binary fallback payloads

## 6.4 UI state hooks

Files:

- `frontend/src/hooks/useMediaStream.ts`
- `frontend/src/hooks/useMetrics.ts`
- `frontend/src/hooks/useNudges.ts`

These keep media capture, live metrics state, and nudge UX separately testable from the session page itself.

---

## 7. Storage Architecture

## 7.1 Local development mode

Default local mode uses:

- SQLite for auth (`data/auth.db`)
- JSON files for session summaries (`data/sessions/`)
- local files for traces (`data/traces/`)

### Why this is good

It keeps the default developer experience very light.

### Tradeoff

It is not the right production storage story.

## 7.2 Production mode

Production can switch to:

- Postgres for users and session summaries
- S3-compatible object storage (R2) for traces

Relevant files:

- `backend/app/analytics/__init__.py`
- `backend/app/auth/__init__.py`
- `backend/app/db.py`
- `backend/app/db_schema.py`
- `docs/production-deployment-guide.md`

### Why this split

Structured, queryable data belongs in Postgres; large trace artifacts belong in object storage.

---

## 8. Deployment Model

Recommended production stack:

- frontend on Fly.io
- backend on Fly.io
- LiveKit Cloud for media
- Postgres for durable storage
- Cloudflare R2 / S3-compatible store for traces
- Sentry for observability

### Important current constraint

Because active session state lives in-memory, the backend is still architected like a **single-session-state authority**, not a horizontally coordinated cluster.

That is the main reason the deployment guidance recommends keeping a single backend instance for live session handling.

---

## 9. Important Tradeoffs We Made

This section is the real “why” behind the current system.

## 9.1 LiveKit instead of custom WebRTC

### We gained
- a real production media plane
- less in-house WebRTC complexity
- cleaner reconnect/media behavior
- a better long-term product architecture

### We accepted
- an external infrastructure dependency
- operational reliance on LiveKit correctness/config
- some leftover compatibility surface in models/docs during migration cleanup

## 9.2 Server-side analytics worker instead of browser-default uploads

### We gained
- a cleaner architecture
- no default duplicate media upload path
- centralized processing
- easier parity across clients

### We accepted
- higher server compute responsibility
- more sensitivity to backend worker health

## 9.3 Rule-based coaching instead of ML-generated live advice

### We gained
- explainability
- deterministic tests and replay evals
- less hallucination / less tutor distrust
- easier suppression and product tuning

### We accepted
- less adaptivity
- more manual threshold tuning
- lower ultimate sophistication ceiling

## 9.4 Categorical attention state instead of raw eye-contact percentage

### We gained
- more tutoring-relevant semantics
- better product behavior around “screen engaged” vs “away”
- easier suppression and persistence-based off-task logic

### We accepted
- a heuristic state model, not a true intent detector
- limited ability to distinguish productive off-camera work from distraction in all cases

## 9.5 Audio-primary engagement and interruption model

### We gained
- robustness
- always-available signals even under degraded video
- strong turn-taking / overlap semantics

### We accepted
- no emotion recognition
- sensitivity to environment noise and device quality

## 9.6 In-memory active session manager instead of distributed state

### We gained
- very simple implementation
- low operational overhead
- easy local development and tests

### We accepted
- no true multi-instance scale for live sessions yet
- future Redis/shared-state work when scaling out

## 9.7 Local-first storage defaults instead of requiring cloud infra everywhere

### We gained
- very low-friction development
- inspectable JSON summaries and local DB files
- simple demos/tests

### We accepted
- a second storage mode to maintain
- extra migration logic between local and production backends

## 9.8 1:1 optimization over generalized group-call semantics

The system is still primarily optimized for **1 tutor + 1 student**.

There is some multi-student scaffolding:

- multiple student tokens
- multi-student LiveKit identities
- per-student metrics structures
- remote participant tile rendering

But the deeper analytics/coaching semantics are still centered on a primary tutor↔student interaction.

### We gained
- cleaner, more accurate tutoring analytics
- simpler interruption and talk-balance semantics

### We accepted
- partial rather than complete group-session support today

---

## 10. Current Caveats / Notable Edges

- The frontend runtime is effectively **LiveKit-only**, even though some shared types still mention `custom_webrtc`.
- The backend websocket is still important; this is not a “LiveKit replaces everything” architecture.
- Session state is in-memory, so live-session horizontal scaling is still a future architecture step.
- The worker is hidden from participants, but it still consumes backend resources per room.
- Raw media is processed in memory and not persisted, but the system still handles sensitive live audio/video and must be treated accordingly.
- Some historical docs describe the migration path rather than the current steady state.

---

## 11. Best Files to Read When Discussing Architecture

If you want to walk the architecture in code, these are the best anchors:

### Backend
- `backend/app/main.py`
- `backend/app/session_manager.py`
- `backend/app/ws.py`
- `backend/app/livekit.py`
- `backend/app/livekit_worker.py`
- `backend/app/session_runtime.py`
- `backend/app/metrics_engine/engine.py`
- `backend/app/coaching_system/coach.py`
- `backend/app/analytics/summary.py`

### Frontend
- `frontend/src/app/session/[id]/page.tsx`
- `frontend/src/hooks/useLiveKitTransport.ts`
- `frontend/src/hooks/useWebSocket.ts`
- `frontend/src/lib/call/livekit-config.ts`
- `frontend/src/lib/types.ts`

### Ops / docs
- `docs/decision-log.md`
- `docs/privacy-analysis.md`
- `docs/production-deployment-guide.md`

---

## 12. Historical Context

These docs are still useful, but they are no longer the best source for current-state architecture:

- `docs/real-tutoring-session-experience-plan.md`
- `docs/livekit-migration-plan.md`

They describe the transition from:

- analytics-only / custom transport thinking
- toward the current LiveKit + hidden-worker architecture

In other words:

- **decision log** = why we made the moves
- **historical plans** = how we got here
- **this file** = what the system looks like now
