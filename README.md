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
NEXT_PUBLIC_LIVEKIT_SIMULCAST=false
NEXT_PUBLIC_LIVEKIT_VIDEO_CODEC=h264
NEXT_PUBLIC_LIVEKIT_VIDEO_MAX_BITRATE=4500000
```

## Authentication Setup

The app supports three sign-in methods: **Google OAuth**, **email/password**, and **guest** (for students joining via a link with no account required).

### Required environment variables

**Backend** (`LSA_` prefix, set via docker-compose or shell):

| Variable | Default | Description |
|----------|---------|-------------|
| `LSA_JWT_SECRET` | `dev-secret-change-in-production` | HMAC-SHA256 signing key for access tokens. Generate with `openssl rand -base64 32`. **Change before production.** |
| `LSA_AUTH_DB_PATH` | `data/auth.db` | SQLite file for user accounts. Created automatically on first run. Lives inside the `session-data` Docker volume. |
| `LSA_GOOGLE_CLIENT_ID` | *(empty)* | Google OAuth client ID. Leave empty to disable Google sign-in. |
| `LSA_JWT_EXPIRY_HOURS` | `24` | Access token lifetime in hours. |

**Frontend** (env vars or `frontend/.env.local`):

| Variable | Description |
|----------|-------------|
| `AUTH_SECRET` | NextAuth session encryption key. Generate with `openssl rand -base64 32`. **Change before production.** |
| `NEXTAUTH_URL` | Public URL of the frontend (e.g. `http://localhost:3000`). Required for OAuth callbacks. |
| `NEXTAUTH_BACKEND_URL` | Server-to-server backend URL used inside NextAuth callbacks (e.g. `http://backend:8000` in Docker, `http://localhost:8000` locally). |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID. Must match `LSA_GOOGLE_CLIENT_ID`. |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret. |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Exposes the client ID to the browser for the Google One Tap / sign-in button. |

### Setting up Google OAuth (optional)

Google sign-in is optional. Email/password and guest accounts work without it.

To enable Google sign-in:

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials.
2. Create an **OAuth 2.0 Client ID** of type **Web application**.
3. Add `http://localhost:3000/api/auth/callback/google` (and your production URL) as an **Authorized redirect URI**.
4. Copy the **Client ID** and **Client Secret**.
5. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the frontend environment.
6. Set `LSA_GOOGLE_CLIENT_ID` to the same Client ID in the backend environment.
7. Set `NEXT_PUBLIC_GOOGLE_CLIENT_ID` to the same Client ID for the browser-side button.

### Sign-in methods

| Method | Path | Notes |
|--------|------|-------|
| Email / password | `/login` | Register at `/register` first. Passwords are hashed with PBKDF2-HMAC-SHA256 (260,000 iterations, OWASP 2023 recommendation). |
| Google OAuth | `/login` → "Sign in with Google" | Requires Google credentials above. |
| Guest (student) | Automatic on student link join | No account required. Anonymous UUID identity. No expiry enforced yet (periodic cleanup is planned but not implemented). |

### Local development without auth

For quick local development, auth can be bypassed by hitting backend endpoints directly. The session WebSocket still uses per-session `tutor_token`/`student_token` for room access (unchanged). User-level auth is only required for REST API calls (session creation, analytics listing).

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
- for local high-quality LiveKit testing on a stable connection, the defaults should give Zoom/Meet-class quality: 1080p capture, H.264 codec, 4.5 Mbps, no simulcast. Set `NEXT_PUBLIC_LIVEKIT_ADAPTIVE_STREAM=false` and `NEXT_PUBLIC_LIVEKIT_DYNACAST=false` to prevent adaptive downscaling. For 1:N scenarios, re-enable simulcast with `NEXT_PUBLIC_LIVEKIT_SIMULCAST=true`
- production LiveKit Cloud setup steps are documented in `docs/livekit-cloud-setup.md`
- `LSA_CORS_ORIGINS` accepts either a JSON array or a comma-separated list (for example: `https://lsa-frontend.fly.dev,https://staging.example.com`)

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

1. Open http://localhost:3000 — unauthenticated users are redirected to `/login`
2. Sign in with Google, email/password (register at `/register` first), or continue as a guest (students joining via a student link are auto-authenticated as guests)
3. Once signed in, click "Create Session" on the home page — you'll get a session ID and student join link
4. Share the student link with the student
5. Both participants grant camera/mic access via the consent modal
6. The session page opens a role-aware live tutor↔student call surface while still uploading analytics to the backend
7. Tutor sees a minimal private coaching overlay and can end the session for everyone; students get a cleaner call-first view and can leave locally without seeing tutor metrics
8. Detailed live diagnostics stay behind the tutor `Coach debug` toggle (or `?debug=1` for explicit debug/test sessions)
9. After the session, visit /analytics for post-session analysis

## Key Features

- **Real-time video analysis**: MediaPipe FaceMesh for eye contact detection and expression analysis
- **Voice activity detection**: Per-participant webrtcvad for accurate speaking time and interruption tracking
- **5 coaching rules**: Student silence, low eye contact, tutor overtalk, energy drop, interruption spike
- **Adaptive degradation**: Automatically reduces processing load to stay under 500ms latency
- **AI Conversational Intelligence**: Real-time transcription, tone/uncertainty detection, and AI coaching copilot (see section below)
- **Redesigned post-session analytics**: Filterable tutor-centric review workspace with richer session cards, derived coaching lenses, recommendations, flagged moments, and comparison panels
- **Cross-session trends**: Track improvement over multiple sessions with a portfolio trend view and review queue
- **WebRTC peer media**: Tutor/student call UI using the existing authenticated websocket for signaling
- **Minimal live coaching UI**: Tutor gets subtle live status pills by default with richer diagnostics behind debug
- **Privacy-safe local traces**: optional per-session trace artifacts capture lifecycle events, compact signal traces, coaching decisions, and final summaries without raw media or SDP contents
- **Offline eval harness**: fast + replay eval layers under `backend/tests/evals/` validate production trace models, fixture expectations, compact signal-trace accuracy cases, and recorded session replays

## AI Conversational Intelligence

The system includes an optional multi-tier conversational intelligence layer that adds speech-to-text, tone analysis, and AI-powered coaching to live sessions. **All features are disabled by default** for backward compatibility — enable each tier independently via environment variables.

### Architecture

```
LiveKit Room Audio Tracks
  │
  ├─ VAD-gated audio ──→ DroppableAudioQueue ──→ STT Provider (Deepgram / AssemblyAI)
  │                                                    │
  │                                          TranscriptionStream
  │                                                    │
  │                            ┌───────────────────────┼──────────────────────┐
  │                            ▼                       ▼                      ▼
  │                   TranscriptBuffer     Uncertainty Detector      AI Coaching Copilot
  │                   (live display)       (tone + hedging)          (LLM suggestions)
  │                            │                       │                      │
  │                            └───────────────────────┼──────────────────────┘
  │                                                    ▼
  │                                           Tutor UI (WebSocket)
  │
  └─ Post-session ──→ TranscriptStore ──→ AI Summary + Analytics
```

### Tiers

| Tier | Feature | Config Flag | Requires |
|------|---------|-------------|----------|
| 1 | **Live Transcription** — real-time STT with per-speaker attribution | `LSA_ENABLE_TRANSCRIPTION=true` | STT API key |
| 2 | **Uncertainty Detection** — hedging, hesitation, tonal analysis | `LSA_ENABLE_UNCERTAINTY_DETECTION=true` | Tier 1 |
| 3 | **AI Coaching Copilot** — contextual LLM-powered suggestions | `LSA_ENABLE_AI_COACHING=true` | Tier 1 + LLM API key |
| 4 | **Frontend UX** — transcript panel, suggestion cards, uncertainty badges | Automatic when backend tiers enabled | — |
| 5 | **Post-Session Enrichment** — transcript storage + AI summaries | `LSA_ENABLE_TRANSCRIPT_STORAGE=true`, `LSA_ENABLE_AI_SESSION_SUMMARY=true` | Tier 1 + LLM API key |

### Configuration

All conversational intelligence settings use the `LSA_` prefix. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LSA_ENABLE_TRANSCRIPTION` | `false` | Master switch for real-time STT |
| `LSA_TRANSCRIPTION_PROVIDER` | `deepgram` | STT provider: `deepgram` or `assemblyai` |
| `LSA_TRANSCRIPTION_ROLES` | `tutor,student` | Which roles to transcribe |
| `LSA_DEEPGRAM_API_KEY` | *(empty)* | Deepgram API key |
| `LSA_DEEPGRAM_MIP_OPT_OUT` | `true` | Opt out of Deepgram model improvement program |
| `LSA_ASSEMBLYAI_API_KEY` | *(empty)* | AssemblyAI API key |
| `LSA_ENABLE_UNCERTAINTY_DETECTION` | `false` | Enable tone/uncertainty analysis |
| `LSA_UNCERTAINTY_UI_THRESHOLD` | `0.6` | UI threshold for surfacing uncertainty |
| `LSA_ENABLE_AI_COACHING` | `false` | Enable AI coaching suggestions |
| `LSA_AI_COACHING_PROVIDER` | `anthropic` | LLM provider currently supported in production |
| `LSA_AI_COACHING_MODEL` | `claude-sonnet-4-20250514` | Default coaching/summary model |
| `LSA_ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key for coaching |
| `LSA_AI_COACHING_MAX_CALLS_PER_HOUR` | `30` | Per-session hourly LLM call budget |
| `LSA_ENABLE_TRANSCRIPT_STORAGE` | `false` | Persist transcripts after session ends |
| `LSA_ENABLE_AI_SESSION_SUMMARY` | `false` | Generate AI summary post-session |

See `.env.example` and `.env.production.example` for the full annotated list.

### Privacy & Consent

- All transcription features require explicit user consent via the in-session consent modal
- PII scrubbing is applied before any data leaves the session context
- `LSA_DEEPGRAM_MIP_OPT_OUT=true` (default) prevents audio from being used for provider model training
- Transcript data can be deleted per-session via `DELETE /api/analytics/sessions/{id}/transcript`
- No raw audio is stored — only derived text transcripts

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

## Production Deployment

The production stack is **Fly.io** (app hosting) + **LiveKit Cloud** (media) +
**Neon Postgres** (relational data) + **Cloudflare R2** (trace/artifact storage) +
**Sentry** (observability).

| Service | URL |
|---------|-----|
| Frontend | https://lsa-frontend.fly.dev |
| Backend | https://lsa-backend.fly.dev |
| Backend health | https://lsa-backend.fly.dev/health |

See **[docs/production-deployment-guide.md](docs/production-deployment-guide.md)**
for the full deployment guide, including:

- account creation steps for every external service
- secrets generation commands (`openssl rand -base64 32`)
- step-by-step deployment sequence for backend and frontend
- DNS and custom-domain setup
- smoke test checklist
- rollback procedure

The annotated environment variable template is at
**[.env.production.example](.env.production.example)** — every variable is
documented with its purpose and a generation command.

For local development, use the lighter **[.env.example](.env.example)** with
localhost defaults.

### CI/CD

Pushing to `main` triggers an automatic deployment via GitHub Actions
(`.github/workflows/deploy.yml`):

1. **Frontend tests** — TypeScript check + unit tests
2. **Backend tests** — pytest (fast subset, excludes slow/replay)
3. **Deploy backend** → `fly deploy --app lsa-backend`
4. **Deploy frontend** → `fly deploy --app lsa-frontend` with `NEXT_PUBLIC_*` build args

Backend and frontend deploy in parallel after tests pass.

**Required GitHub Secrets** (already configured):

| Secret | Value |
|--------|-------|
| `FLY_API_TOKEN` | Fly.io org deploy token |
| `NEXT_PUBLIC_API_URL` | `https://lsa-backend.fly.dev` |
| `NEXT_PUBLIC_WS_URL` | `wss://lsa-backend.fly.dev` |
| `NEXT_PUBLIC_LIVEKIT_URL` | LiveKit Cloud WSS URL |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth client ID |

Optional: `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENVIRONMENT`

You can also trigger a deploy manually from the GitHub Actions tab
(**"Run workflow"** button).

## Documentation

- [Production Deployment Guide](docs/production-deployment-guide.md) - Full Fly.io + LiveKit Cloud + Postgres + R2 deployment walkthrough
- [AI Conversational Intelligence Plan](docs/ai-conversational-intelligence-plan.md) - Deep implementation plan for STT, uncertainty detection, AI coaching, and post-session enrichment
- [Decision Log](docs/decision-log.md) - Architecture choices and rationale
- [Web Production MVP Plan](docs/web-production-mvp-plan.md) - Recommended production deployment posture for the web pilot
- [LiveKit Cloud Setup](docs/livekit-cloud-setup.md) - Manual operator steps for LiveKit Cloud
- [LiveKit Migration Plan](docs/livekit-migration-plan.md) - Test-first migration from custom WebRTC to LiveKit
- [Privacy Analysis](docs/privacy-analysis.md) - Data handling and consent
- [API Reference](docs/api-reference.md) - REST and WebSocket endpoints (includes AI Conversational Intelligence endpoints)
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
