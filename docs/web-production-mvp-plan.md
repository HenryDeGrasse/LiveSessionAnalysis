# Web Production MVP Plan

## Goal
Ship a **professional, real production web deployment** of the current tutoring-call + analytics system without pretending the architecture is already horizontally scalable.

This plan is intentionally pragmatic:
- keep the current Next.js + FastAPI + WebRTC architecture
- harden it for real internet-facing use
- add the missing production infrastructure around it
- be explicit about what is pilot-ready vs what must change before true multi-instance scale

If the team decides to replace the current custom WebRTC layer with LiveKit, see `docs/livekit-migration-plan.md` for the phased, test-first migration path.

## Current Verified Product State
The repository is already in a strong pilot-Web-MVP position:
- Next.js frontend builds successfully
- FastAPI backend passes its test suite on Python 3.9 and 3.11
- Playwright covers the main browser flows on localhost with fake media
- tutor and student can see/hear each other in-app via WebRTC
- backend analytics continue in parallel with the live call
- tutor-only coaching and post-session analytics exist

## Production Posture We Want
For the first real production deployment, we want:
- HTTPS everywhere
- WSS for session websockets
- TURN-backed WebRTC connectivity
- durable persistent storage for session summaries and product metadata
- environment separation: local / staging / production
- repeatable containerized builds
- real error monitoring and structured logs
- backups and retention policy
- honest operating constraints around session-state scaling

## Key Constraint: Why This Is Not Yet a Multi-Instance Backend
Today, live session state is still process-local:
- session rooms are held in backend memory
- reconnect/grace-period logic is local to one backend process
- analytics persistence is currently file-based by default

That means the **first production deployment should use a single live-session backend instance** or explicit sticky routing to a single session host. This is acceptable for a real pilot / low-volume MVP, but it is not the final scale architecture.

## Recommended Web Production Architecture

```text
Internet
  |
  v
[ DNS / TLS ]
  |
  v
[ Edge proxy: Caddy or Nginx ]
  |-------------------------------> [ coturn ]
  |
  +--> [ Next.js frontend container ]
  |
  +--> [ FastAPI backend container ]
            |
            +--> [ Postgres ]
            |
            +--> [ local/object trace storage ]
            |
            +--> [ Sentry / logs ]
```

## Recommended Stack

### 1. Edge / ingress
**Recommendation:** Caddy for the first production deployment.

Why:
- automatic HTTPS
- simple config
- easy reverse proxying for frontend + backend
- good fit for a small production footprint

Nginx is also fine if that matches existing ops comfort.

### 2. Frontend
**Recommendation:** keep **Next.js standalone** in a container.

Why:
- already implemented
- clean build artifact
- good enough for the current product surface
- easy to deploy behind an edge proxy

### 3. Backend
**Recommendation:** keep **FastAPI + Uvicorn** in a container.

Why:
- current codebase already fits the product
- websocket handling is already built
- analytics pipeline is already in Python

For the first production MVP, run **one live backend instance** for active sessions.

### 4. WebRTC connectivity
**Recommendation:** add **coturn** immediately.

Why:
- STUN-only is not production-grade
- TURN is required for dependable connectivity across NAT/firewalls
- this is the single most important infrastructure addition for real-world call reliability

### 5. Persistence
**Recommendation:** move production data to **Postgres**.

Use Postgres for:
- session summaries
- tutor metadata
- session-type metadata
- analytics listing/filtering
- future auth/account data
- durable audit-friendly storage

JSON files are still fine for local development and fixture workflows, but not as the primary production persistence layer.

### 6. Observability
**Recommendation:** add:
- **Sentry** for frontend + backend errors
- structured application logs
- uptime/health checks
- retention/backup checks for persistent stores

### 7. Deployment substrate
**Recommendation:** start with one of:
- a small VM
- Fly.io / Railway / Render / ECS-style container deployment
- a simple Docker-hosted server with Caddy in front

Do **not** start with Kubernetes unless there is already strong internal platform support. The current app does not need K8s complexity yet, and its live session state model does not benefit much from autoscaling today.

## Environment Strategy

### Local
Purpose:
- development
- feature work
- localhost testing

Current fit:
- `docker-compose.yml`
- direct localhost frontend/backend

### Staging
Purpose:
- real HTTPS/WSS
- TURN validation
- browser/device smoke tests
- pre-release QA

Should include:
- same topology as production
- real DNS/subdomain
- real TURN config
- isolated Postgres database
- Sentry pointing to staging project

### Production
Purpose:
- real user sessions
- stable logs/metrics
- backups
- explicit operating limits

Should include:
- managed TLS
- TURN
- Postgres backups
- secrets management
- release rollback path

## Build + Release Flow

### Frontend build
- build Next.js in CI
- produce standalone runtime image
- inject environment variables at deploy time

### Backend build
- build FastAPI runtime image
- install pinned Python dependencies
- run tests in CI before image promotion

### Release gates
At minimum, production release should require:
- backend tests passing
- frontend TypeScript passing
- frontend build passing
- Playwright E2E passing
- staging smoke check passing

## Immediate Production Work Items

### P0 — must do before calling it production
1. Add **TURN** (`coturn`) and production ICE configuration
2. Add **HTTPS/WSS** at the edge
3. Add **Sentry** to frontend and backend
4. Add **staging environment**
5. Move persistence from JSON-primary to **Postgres-primary** for production data
6. Document required env vars and secret handling

### P1 — strongly recommended right after first deployment
7. Add structured logs and request/session correlation ids
8. Add periodic retention cleanup job for persisted analytics/trace data
9. Add manual cross-device / cross-network / TURN validation checklist
10. Add longer browser soak coverage and operational smoke scripts

### P2 — next architecture step before scale
11. Move live session presence/state out of process memory
12. Add Redis or another shared coordination layer
13. Rework live session routing so multiple backend instances are safe
14. Revisit whether to keep custom WebRTC signaling only, or move toward LiveKit/SFU infrastructure

## Honest MVP Production Limits
For the first real production deployment, we should explicitly state:
- the app is production-ready for **pilot traffic**, not high-scale multi-instance traffic
- active live sessions should run through a single backend instance
- TURN is required for broad network reliability
- the browser test suite is strong on localhost, but real-device network validation is still operationally important

## Why We Are Not Recommending a Full SFU Yet
A platform like **LiveKit** may become the right longer-term production media layer.

But for the current product, keeping:
- WebRTC peer media
- backend analytics uploads
- current FastAPI coordination

is the fastest path to a professional production MVP.

Revisit LiveKit / mediasoup / Janus when one of these becomes true:
- real traffic volume grows
- peer-to-peer reliability is insufficient even with TURN
- multi-party sessions become a requirement
- recording/compliance/media routing needs become much stronger

## Proposed First Production Topology

```text
Caddy
  - serves TLS
  - routes / to frontend
  - routes /api and /ws to backend

Frontend container
  - Next.js standalone app

Backend container
  - FastAPI + websocket session handling
  - single live instance for active sessions

coturn
  - TURN/STUN for WebRTC connectivity

Postgres
  - durable summaries + product metadata

Sentry
  - frontend + backend error monitoring
```

## Decision Summary
If we are optimizing for **professional, real production readiness now**, the best path is:
- keep the current app architecture
- harden it with edge TLS, TURN, Postgres, Sentry, staging, and CI gates
- deploy as a deliberately single-instance live-session backend for the pilot phase
- postpone multi-instance/session-state re-architecture until after first real production usage

## Recommended Next Design Exercise
When walking through the system design, use this order:
1. define product requirements and non-goals
2. define the live-session critical path
3. define reliability requirements for WebRTC
4. define persistence requirements
5. define deployment topology
6. define scaling limits honestly
7. define the next architectural seam to upgrade later

That makes the system design story much clearer than jumping straight to tools.
