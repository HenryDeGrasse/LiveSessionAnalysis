# AI-Powered Live Session Analysis

Real-time engagement analysis and AI coaching for video tutoring sessions. Analyzes webcam video and audio from both tutor and student to measure engagement metrics, deliver non-intrusive coaching nudges, provide live speech-to-text transcription with uncertainty detection, and generate AI-powered teaching suggestions — all during the session, with post-session analytics and cross-session trend tracking.

## Architecture

```
┌──────────────────┐          LiveKit SFU           ┌──────────────────┐
│   Tutor Browser  │◄══════ audio / video ════════►│  Student Browser │
│                  │                                │                  │
│  Coaching overlay│       ┌───────────────┐        │  Clean call UI   │
│  Transcript panel│◄──────│   Backend     │───────►│  (no metrics)    │
│  AI Suggest btn  │ nudges│               │state   │                  │
└──────────────────┘       │  LiveKit      │        └──────────────────┘
                           │  Analytics    │
                           │  Worker       │
                           │    │          │
                           │    ▼          │
              ┌────────────┤  Metrics ◄────┤
              │            │  Engine       │
              │            │    │          │
              │  ┌─────────┤  Coaching     │
              │  │         │  System       │
              │  │         │    │          │
              │  │  ┌──────┤  STT Stream ──┼──► AssemblyAI (speech-to-text)
              │  │  │      │    │          │
              │  │  │  ┌───┤  Uncertainty  │
              │  │  │  │   │  Detector     │
              │  │  │  │   │    │          │
              │  │  │  │   │  AI Copilot ──┼──► Gemini Flash (on-demand)
              │  │  │  │   │              ─┼──► Claude Haiku (auto-suggest)
              │  │  │  │   └───────────────┘
              │  │  │  │
              ▼  ▼  ▼  ▼
         ┌─────────────────┐
         │  Post-Session   │
         │  Analytics      │
         │  Dashboard      │
         └─────────────────┘
```

Both participants connect via their browser. The backend LiveKit analytics worker subscribes to room tracks (hidden from participants), processes video and audio in real-time, and sends coaching nudges + metrics only to the tutor.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Or: Python 3.9-3.11, Node.js 18+

### One-Command Setup
```bash
docker compose up
```
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- LiveKit dev server: ws://localhost:7880

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

### Running Tests
```bash
# Backend (1,194 tests)
cd backend
uv run --python 3.11 --with-requirements requirements.txt pytest tests/ --ignore=tests/evals -q

# Frontend (242 tests)
cd frontend
npm run test:unit

# Browser E2E
npm run test:e2e
```

## Key Features

### Real-Time Video Analysis
- **MediaPipe FaceMesh** with iris landmarks for eye contact / gaze estimation (<50ms per frame)
- **6-state attention model**: `CAMERA_FACING`, `SCREEN_ENGAGED`, `DOWN_ENGAGED`, `OFF_TASK_AWAY`, `FACE_MISSING`, `LOW_CONFIDENCE`
- Adaptive degradation: auto-reduces processing to stay under 500ms latency

### Audio Analysis
- **webrtcvad** per-participant voice activity detection (30ms PCM chunks)
- **Praat/parselmouth** pitch extraction for prosody analysis
- RMS energy, speech rate estimation, zero-crossing rate
- Interruption classification: backchannel vs hard interruption vs echo

### Engagement Metrics
| Metric | Method | Target Accuracy |
|--------|--------|-----------------|
| Eye contact | Iris landmark gaze angle | ≥85% |
| Speaking time | Per-role VAD accumulation | ≥95% |
| Interruptions | Cross-stream overlap detection | Low false positives |
| Energy | RMS + speech rate + expression | Relative trend |
| Attention drift | Persistence-based state tracking | State-aware |

### Real-Time Coaching (5 Rules)
| Rule | Trigger | Example Nudge |
|------|---------|---------------|
| `check_for_understanding` | Tutor talk exceeds session-type ceiling | "Student has been quiet. Consider asking a question." |
| `student_off_task` | Student in OFF_TASK/FACE_MISSING > threshold | "Student may be distracted or having a tech issue." |
| `let_them_finish` | 3+ hard interruptions in recent window | "Several interruptions detected. Try more wait time." |
| `tech_check` | Extended mutual silence + participant off-camera | "Extended silence — consider checking in." |
| `ai_coaching_suggestion` | LLM-generated contextual suggestion | "Before we go further, can you tell me what the 3 and 4 in three-fourths represent?" |

All nudges are:
- **Tutor-only** — students never see coaching data
- **Configurable** — sensitivity adjustable via session type profiles and coaching intensity (`subtle` / `normal` / `aggressive`)
- **Rate-limited** — global cooldown (30s), per-rule cooldowns, warmup period, budget ceiling

### AI Conversational Intelligence

Optional multi-tier system (all disabled by default):

| Tier | Feature | Enable With |
|------|---------|-------------|
| 1 | **Live Transcription** — AssemblyAI Universal Streaming v3 | `LSA_ENABLE_TRANSCRIPTION=true` |
| 2 | **Uncertainty Detection** — linguistic hedging + prosodic signals | `LSA_ENABLE_UNCERTAINTY_DETECTION=true` |
| 3 | **AI Coaching Copilot** — dual-model LLM suggestions | `LSA_ENABLE_AI_COACHING=true` |

**Dual-model architecture:**
- **On-demand** (tutor clicks "AI Suggest"): Gemini 2.5 Flash via SSE streaming (~1s)
- **Auto-suggest** (background): Claude 3.5 Haiku (~3s, every 35s baseline)

The AI generates **speakable prompts** — complete sentences the tutor can read word-for-word to the student mid-session.

### Post-Session Analytics
- Session summary with engagement score, talk time ratios, flagged moments
- Timeline charts with toggleable metric overlays
- Cross-session trend tracking and session portfolio view
- AI-generated improvement recommendations
- Transcript review with uncertainty highlights

### Session Types & Profiles
| Type | Tutor Talk Ceiling | Silence Threshold | Use Case |
|------|-------------------|-------------------|----------|
| `general` | 75% | 120s | Default |
| `lecture` | 92% | 300s | Explanation-heavy |
| `practice` | 55% | 60s | Problem-solving |
| `socratic` | 65% | 45s | Question-driven |
| `discussion` | 70% | 90s | Open dialogue |

## Configuration

All backend settings use the `LSA_` prefix. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LSA_ENABLE_TRANSCRIPTION` | `false` | Live speech-to-text |
| `LSA_TRANSCRIPTION_PROVIDER` | `assemblyai` | `assemblyai` or `deepgram` |
| `LSA_ASSEMBLYAI_API_KEY` | — | AssemblyAI API key |
| `LSA_ENABLE_UNCERTAINTY_DETECTION` | `false` | Tone/uncertainty analysis |
| `LSA_ENABLE_AI_COACHING` | `false` | AI coaching suggestions |
| `LSA_AI_COACHING_MODEL` | `anthropic/claude-3.5-haiku` | Auto-suggest model (quality) |
| `LSA_AI_COACHING_ONDEMAND_MODEL` | `google/gemini-2.5-flash` | On-demand model (speed) |
| `LSA_OPENROUTER_API_KEY` | — | OpenRouter API key |

See `.env.example` for the full annotated list.

## Authentication

Three sign-in methods:
- **Email / password** — register at `/register`, PBKDF2-HMAC-SHA256 (260k iterations)
- **Google OAuth** — optional, requires Google Cloud credentials
- **Guest** — automatic for students joining via invite link (no account needed)

Sessions are **invite-link only**: tutor creates a session, copies the student link, shares it. No manual session ID / token entry.

## Project Structure

```
backend/
  app/
    main.py                  # FastAPI app
    config.py                # All thresholds (Pydantic settings)
    models.py                # Shared data models
    session_manager.py       # Session room management
    session_runtime.py       # Per-session resource orchestration
    livekit_worker.py        # Server-side analytics worker
    video_processor/         # MediaPipe FaceMesh, gaze, expression
    audio_processor/         # webrtcvad, prosody (Praat pitch)
    metrics_engine/          # Cross-participant metric aggregation
    coaching_system/         # Rule-based coaching (5 rules, profiles)
    analytics/               # Session storage, summaries, trends
    transcription/           # STT streaming (AssemblyAI, Deepgram)
    uncertainty/             # Linguistic + paralinguistic detection
    ai_coaching/             # LLM copilot, prompts, validation
    auth/                    # JWT, OAuth, guest accounts
    observability/           # Privacy-safe session traces
  tests/                     # 1,194 tests + eval fixtures

frontend/
  src/
    app/                     # Next.js pages (home, session, analytics)
    components/
      coaching/              # AISuggestionCard, SuggestButton
      transcript/            # TranscriptPanel, UncertaintyBadge
    hooks/                   # useMediaStream, useTranscript, useAISuggestion
    lib/                     # Types, constants, analytics utils
  e2e/                       # Playwright browser tests
```

## Performance

| Metric | Target | Measured |
|--------|--------|----------|
| Video processing latency | <500ms | <300ms typical (3 FPS) |
| Metric update frequency | 1-2 Hz | 1-3 Hz |
| AI on-demand suggestion | <2s | ~1s (Gemini 2.5 Flash + SSE) |
| AI auto-suggest | <5s | ~3s (Claude 3.5 Haiku) |
| Transcription latency | <2s | ~1-2s (AssemblyAI streaming) |

Adaptive degradation maintains latency under budget:
- L0: Full processing (3 FPS)
- L1: Reduced FPS, skip expression analysis
- L2: Disable gaze, audio-only metrics
- L3: Minimal processing

## Test Coverage

**1,194 backend tests** covering:
- Video pipeline (face detection, gaze, expression)
- Audio pipeline (VAD, prosody, pitch extraction)
- Metrics engine (eye contact, speaking time, interruptions, energy, attention)
- Coaching system (5 rules, cooldowns, session-type profiles, trace metadata)
- Transcription (stream lifecycle, tail injection, reconnect, clock mapping)
- Uncertainty detection (linguistic hedging, paralinguistic signals)
- AI coaching (copilot budget/interval, output validation, PII scrubbing, LLM client)
- Analytics (session storage, summaries, trends, recommendations)
- 22 accuracy eval cases (signal trace replay with ground-truth assertions)

**242 frontend tests** covering:
- Coaching components (suggestion card, suggest button, prompt block)
- Transcript hooks (partial/final handling, buffer management)
- Uncertainty display hooks
- Analytics dashboard rendering

**Playwright E2E** covering:
- Full tutor + student live call in browser
- Tutor-only analytics visibility
- Session lifecycle (create → join → end → analytics)

## Documentation

- [Decision Log](docs/decision-log.md) — Architecture choices and rationale
- [Privacy Analysis](docs/privacy-analysis.md) — Data handling, consent, STT/LLM data flow
- [Limitations](docs/limitations.md) — Known constraints and edge cases
- [Calibration Guide](docs/calibration.md) — Threshold tuning and validation
- [Accuracy Report](docs/accuracy-report.md) — 22/22 eval cases passing
- [API Reference](docs/api-reference.md) — REST and WebSocket endpoints
- [Architecture Deep Dive](docs/architecture_docs.md) — Pipeline internals
- [Production Deployment](docs/production-deployment-guide.md) — Fly.io + LiveKit Cloud + Neon Postgres

## Production

| Service | URL |
|---------|-----|
| Frontend | https://lsa-frontend.fly.dev |
| Backend | https://lsa-backend.fly.dev |

CI/CD via GitHub Actions: push to `main` → tests → deploy to Fly.io.
