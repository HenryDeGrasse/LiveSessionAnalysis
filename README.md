# AI-Powered Live Session Analysis

Real-time engagement analysis and coaching system for video tutoring sessions. Analyzes webcam video and audio from both tutor and student to measure engagement metrics and deliver non-intrusive coaching nudges during sessions, plus post-session analytics with cross-session trend tracking.

## Architecture

```
Tutor Browser                           Backend                           Student Browser
+-------------------+   WS signaling + analytics   +-----------------+   WS signaling + analytics   +-------------------+
| Local cam/mic     |------------------------------>| SessionRoom     |<------------------------------| Local cam/mic     |
| WebRTC peer media |<==== direct audio/video =====>| auth + relay    |===== direct audio/video ====>| WebRTC peer media |
| Tutor overlay     |<------------------------------| analytics       |------------------------------>| Student call UI   |
| Metrics + nudges  |        metrics + nudges       | VAD / gaze /    |          participant state    | (no tutor metrics)|
+-------------------+                               | expression      |                               +-------------------+
                                                    | metrics engine  |
                                                    +-----------------+
```

Both participants connect via their own browser with separate webcam/mic. The backend processes each stream independently, computes cross-participant metrics (talk time ratio, interruptions), and sends coaching nudges to the tutor only.

## Current Product State

The session page now includes a **WebRTC peer-media path** so tutor and student can share live audio/video in the same window while the existing backend analytics continue in parallel.

Current verified implementation state:
- authenticated session WebSocket now carries **JSON signaling/control** and **binary analytics payloads**
- backend relays WebRTC `offer` / `answer` / `ice_candidate` messages between tutor and student
- session UI renders a large remote participant view with a small local self-view
- tutor live coaching stays minimal by default; detailed metrics remain behind the debug toggle
- analytics-only fallback still exists behind `NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI=false`
- LiveKit sessions can optionally run analytics/coaching from a hidden backend room subscriber via `LSA_ENABLE_LIVEKIT_ANALYTICS_WORKER=true`

Important caveat:
- browser build/tests and backend signaling tests pass, but broad network reliability still depends on proper ICE/TURN configuration and manual two-browser validation

See `docs/real-tutoring-session-experience-plan.md` for the rollout plan and remaining work.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Or: Python 3.9-3.11, Node.js 18+

> Note: the backend test suite is verified on Python 3.9 and 3.11. `mediapipe==0.10.9` in `backend/requirements.txt` does not currently ship Python 3.12 wheels in this setup, so local backend development should avoid Python 3.12.

### Using Docker
```bash
docker compose up
```
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- LiveKit dev server: ws://localhost:7880

The compose stack now includes a local `livekit-server --dev` instance, so sessions created with the LiveKit provider can connect without extra setup.

### Local Development
```bash
# Backend
cd backend
uv run --python 3.11 --with-requirements requirements.txt uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Optional frontend envs:
```bash
NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI=true
NEXT_PUBLIC_ICE_SERVERS='[{"urls":"stun:stun.l.google.com:19302"}]'
NEXT_PUBLIC_LIVEKIT_URL=ws://127.0.0.1:7880
NEXT_PUBLIC_VIDEO_WIDTH=1920
NEXT_PUBLIC_VIDEO_HEIGHT=1080
NEXT_PUBLIC_VIDEO_FRAME_RATE=30
NEXT_PUBLIC_LIVEKIT_ADAPTIVE_STREAM=false
NEXT_PUBLIC_LIVEKIT_DYNACAST=false
```

Optional backend envs for LiveKit sessions:
```bash
LSA_ENABLE_LIVEKIT=true
LSA_ENABLE_LIVEKIT_ANALYTICS_WORKER=true
LSA_LIVEKIT_URL=ws://127.0.0.1:7880
LSA_LIVEKIT_API_KEY=devkey
LSA_LIVEKIT_API_SECRET=secret
```

Notes:
- set `NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI=false` to force the older analytics-only session UI
- for real deployment, add TURN-capable ICE servers instead of relying only on public STUN
- `livekit-server --dev` uses the `devkey` / `secret` pair expected by the current local setup and Playwright harness
- for local high-quality LiveKit testing on a stable connection, keep `NEXT_PUBLIC_VIDEO_WIDTH/HEIGHT` at `1920x1080` (or higher if your camera supports it) and set `NEXT_PUBLIC_LIVEKIT_ADAPTIVE_STREAM=false` plus `NEXT_PUBLIC_LIVEKIT_DYNACAST=false`

### Running Tests
```bash
# Backend
cd backend
uv run --python 3.11 --with-requirements requirements.txt pytest -v
uv run --python 3.9 --with-requirements requirements.txt pytest -q

# Run only the fast offline eval fixtures
pytest -m eval_fast -q

# Run recorded replay fixtures against production replay logic
pytest -m eval_replay -q

# Frontend typecheck/build
cd ../frontend
npm run test:unit
npx tsc --noEmit
npm run build

# Browser E2E (starts isolated frontend/backend servers on test-only ports)
npm run playwright:install   # first time only
npm run test:e2e

# Same smoke path against the LiveKit provider
npm run test:e2e:livekit
```

`npm run test:e2e:livekit` automatically enables LiveKit in the backend, enables the server-side LiveKit analytics worker, requests `media_provider=livekit`, and starts a local LiveKit dev server for the browser smoke suite using either:
- a local `livekit-server` binary, or
- Docker (`livekit/livekit-server`) if the daemon is running

The Playwright suite covers the live browser call path with fake media devices, including:
- tutor + student joining in separate browser contexts
- remote media appearing in both session pages
- tutor-only analytics visibility
- reconnect recovery within the grace period
- session end -> analytics availability

When `LSA_ENABLE_LIVEKIT_ANALYTICS_WORKER=true`, LiveKit sessions stop using browser binary uploads for analytics and instead run the existing metrics/coaching pipeline from a hidden backend worker subscribed to LiveKit room tracks.

## Usage

1. Open http://localhost:3000
2. Click "Create Session" - you'll get a session ID and student join link
3. Share the student link with the student
4. Both participants grant camera/mic access via the consent modal
5. The session page opens a role-aware live tutor↔student call surface while still uploading analytics to the backend
6. Tutor sees a minimal private coaching overlay and can end the session for everyone; students get a cleaner call-first view and can leave locally without seeing tutor metrics
7. Detailed live diagnostics stay behind the tutor `Coach debug` toggle (or `?debug=1` for explicit debug/test sessions)
8. After the session, visit /analytics for post-session analysis

## Key Features

- **Real-time video analysis**: MediaPipe FaceMesh for eye contact detection and expression analysis
- **Voice activity detection**: Per-participant webrtcvad for accurate speaking time and interruption tracking
- **5 coaching rules**: Student silence, low eye contact, tutor overtalk, energy drop, interruption spike
- **Adaptive degradation**: Automatically reduces processing load to stay under 500ms latency
- **Redesigned post-session analytics**: Filterable tutor-centric review workspace with richer session cards, derived coaching lenses, recommendations, flagged moments, and comparison panels
- **Cross-session trends**: Track improvement over multiple sessions with a portfolio trend view and review queue
- **WebRTC peer media**: Tutor/student call UI using the existing authenticated websocket for signaling
- **Minimal live coaching UI**: Tutor gets subtle live status pills by default with richer diagnostics behind debug
- **Privacy-safe local traces**: optional per-session trace artifacts capture lifecycle events, compact signal traces, coaching decisions, and final summaries without raw media or SDP contents
- **Offline eval harness**: fast + replay eval layers under `backend/tests/evals/` validate production trace models, fixture expectations, compact signal-trace accuracy cases, and recorded session replays

## Project Structure

```
backend/
  app/
    main.py                 # FastAPI app, CORS, health check
    config.py               # Pydantic settings (all thresholds)
    models.py               # Shared Pydantic models
    session_manager.py      # Session room management
    ws.py                   # WebSocket handler
    video_processor/        # MediaPipe FaceMesh, gaze, expression
    audio_processor/        # webrtcvad, prosody analysis
    metrics_engine/         # Cross-participant metric aggregation
    coaching_system/        # Rule-based coaching nudges
    analytics/              # Session storage, summary, trends
    observability/          # Privacy-safe session traces / trace store
  tests/                    # 281 tests including fast eval fixtures, replay tiers, and accuracy cases

frontend/
  e2e/                      # Playwright browser smoke/integration tests
  src/
    app/                    # Next.js pages (landing, session, analytics)
    components/             # Shared UI components
    hooks/                  # WebSocket, media, metrics hooks
    lib/                    # Types, constants, frame encoding
  playwright.config.ts      # Isolated browser E2E harness
```

## Documentation

- [Decision Log](docs/decision-log.md) - Architecture choices and rationale
- [Web Production MVP Plan](docs/web-production-mvp-plan.md) - Recommended production deployment posture for the web pilot
- [LiveKit Migration Plan](docs/livekit-migration-plan.md) - Test-first migration from custom WebRTC to LiveKit
- [Privacy Analysis](docs/privacy-analysis.md) - Data handling and consent
- [API Reference](docs/api-reference.md) - REST and WebSocket endpoints
- [Limitations](docs/limitations.md) - Known constraints and edge cases
- [Calibration Guide](docs/calibration.md) - Threshold tuning and validation

## Test Coverage

287 backend tests covering:
- Video pipeline (face detection, gaze estimation, expression analysis)
- Audio pipeline (VAD, prosody)
- Metrics engine (eye contact, speaking time, interruptions, energy, attention drift)
- Coaching system (5 rules, cooldowns, edge cases, trace-friendly evaluation metadata)
- Analytics (session storage, summary generation, trends, recommendations)
- Observability (privacy-safe trace recording, WebRTC signaling sanitization, incremental trace persistence)
- Offline eval harness (`backend/tests/evals/`) with production-model fixture validation, replayed accuracy cases for speaking ratio / attention-state / interruption semantics, and recorded session replay fixtures with separate expectations
- Graceful degradation (invalid frames, missing data, degradation levels)
- Pipeline latency (< 500ms assertions)
- WebSocket E2E (connection, authentication, endpoints, signaling relay, trace persistence)

Plus Playwright browser coverage for:
- full tutor+student live-call setup in browser
- tutor-only analytics visibility
- reconnect recovery within the grace period
- end-session finalization + analytics persistence
- redesigned analytics dashboard/detail rendering with seeded real backend data
- UI-created tutor/session-type metadata persisting into analytics after a real browser session
