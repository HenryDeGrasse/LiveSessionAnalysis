# LiveKit Migration Plan

## Goal
Migrate the project from the current **custom websocket-signaled WebRTC call path** to a **LiveKit-centered media architecture** without breaking the existing tutor coaching, analytics, and post-session review flows.

This plan is intentionally incremental and test-first:
- switch the **media transport** first
- keep the current analytics/coaching path intact initially
- run both paths in parallel behind flags until parity is proven
- only after transport stability is proven, move analytics ingestion off the browser and onto server-side workers subscribing to LiveKit tracks

This is the safest path to a stronger long-term architecture for:
- production call reliability
- cleaner scaling boundaries
- future web + macOS clients
- lower long-term WebRTC maintenance burden

---

## Executive Decision
**Recommendation: migrate to LiveKit now, but do it in phases.**

### Why now
- the product is clearly centered around a real tutoring call experience
- production reliability matters more than minimizing refactor size
- the current repo is not yet so deeply coupled to the custom WebRTC path that migration cost is prohibitive
- future desktop/macOS support becomes easier when call media is handled by a dedicated media platform

### What not to do
Do **not** migrate all of these at once:
- media transport
- analytics ingestion architecture
- tutor live eventing
- session orchestration semantics
- dashboard contracts
- persistence model

That would be a brittle big-bang rewrite.

### What to do instead
Migrate one plane at a time:
1. **Media plane**: custom WebRTC → LiveKit
2. **Keep current analytics path** during migration
3. **Dual-stack test both providers** until parity is proven
4. **Later** move analytics workers to subscribe to LiveKit room tracks server-side
5. **Finally** remove the old transport

---

## Current Verified Baseline
From the current repository state:
- tutor/student live call UI exists
- backend relays custom signaling over websocket
- tutor-only coaching exists
- post-session analytics exists
- backend tests pass
- frontend TypeScript/build pass
- Playwright browser flows cover join/call/reconnect/end/analytics

This baseline matters because the migration must **preserve** the assignment-critical behaviors:
- realtime call
- low-latency analytics/coaching
- tutor-only live guidance
- session summary and trends

---

## Target End State

```text
Browser / Web App / future macOS App
  ├── joins LiveKit room for audio/video
  └── connects to Product API for tutor-only live events + analytics APIs

Product API
  ├── creates app session
  ├── maps app session -> LiveKit room
  ├── mints LiveKit tokens
  ├── receives LiveKit webhooks
  ├── exposes analytics/session APIs
  └── controls tutor/student session semantics

LiveKit
  ├── room/media transport
  ├── participant presence
  ├── reconnect/media reliability
  └── track delivery

Analytics Worker (later phase)
  ├── joins room as hidden participant
  ├── subscribes to tutor/student tracks
  ├── computes metrics/coaching server-side
  └── persists traces/summaries
```

### Interim state during migration
During the migration, the system should temporarily look like this:

```text
Browser
  ├── LiveKit for audio/video
  └── existing backend websocket/API for analytics uploads + tutor nudges
```

That is deliberate. It limits scope while preserving working intelligence features.

---

## Migration Principles

### 1. No big-bang rewrite
Every phase must be independently shippable and reversible.

### 2. Test-first before each behavior change
Add or update tests before changing the behavior they are meant to protect.

### 3. Keep a rollback path until the replacement is proven
The custom transport stays available behind a feature flag until LiveKit is proven in browser tests and manual cross-network validation.

### 4. Preserve stable product contracts where possible
Tutor coaching contracts, summary schemas, and dashboard payloads should stay stable during the transport migration.

### 5. Separate transport migration from analytics architecture migration
First prove LiveKit call parity. Only then move analytics to server-side room subscribers.

---

## Migration Scope and Non-Goals

## In scope
- add LiveKit as an alternate and later default media provider
- make session creation/provider selection explicit
- refactor frontend call code behind a provider-agnostic transport contract
- add backend LiveKit token issuance and webhook handling
- run parity tests against both providers
- make LiveKit the default transport
- later migrate analytics ingestion to server-side LiveKit workers

## Out of scope for the initial transport migration
- rewriting analytics/coaching logic
- replacing current summary/recommendation contracts
- changing the tutor-facing coaching UX model
- introducing macOS-specific functionality immediately
- deleting the current transport before parity is proven

---

## Provider Model
Introduce an explicit media provider model at the session level.

### Session field
- `media_provider: "custom_webrtc" | "livekit"`

### Why
This enables:
- dual-stack support
- canary rollout
- clean rollback
- provider-aware tests
- analytics comparisons across providers

### Default rollout strategy
- phase 1–3: default `custom_webrtc`
- phase 4 canary: selected sessions/users use `livekit`
- phase 5: default `livekit`
- phase 6+: keep legacy only as emergency fallback until removal

---

## Phased Plan

# Phase 0 — Abstractions, flags, and test harness preparation

## Goal
Create the migration seam before changing runtime behavior.

## Code changes
### Frontend
Refactor the session page to consume a provider-agnostic transport interface instead of directly depending on `usePeerConnection.ts`.

#### New structure
- `frontend/src/lib/call/CallTransport.ts`
- `frontend/src/lib/call/CustomWebRTCTransport.ts`
- `frontend/src/lib/call/LiveKitTransport.ts` (stub initially)
- `frontend/src/hooks/useCallTransport.ts`

### Backend
Add `media_provider` to session creation and storage models.

Likely touch:
- `backend/app/models.py`
- `backend/app/session_manager.py`
- `backend/app/main.py`
- analytics summary persistence path if session metadata should be preserved

### Config / flags
Introduce env/config like:
- `LSA_DEFAULT_MEDIA_PROVIDER=custom_webrtc`
- `LSA_ENABLE_LIVEKIT=false`
- `NEXT_PUBLIC_MEDIA_PROVIDER_OVERRIDE=` (optional for local/manual testing)

## Tests first (TDD)
### Backend pytest
Add failing tests for:
- creating a session with `media_provider`
- defaulting to configured provider
- preserving provider in session info/metadata

### Frontend test harness
Before transport refactor lands, add a lightweight frontend unit harness (recommended: Vitest + RTL) so we can test transport selection logic without relying only on Playwright.

Add failing tests for:
- provider selection logic
- session page choosing transport implementation
- provider-specific call state mapping staying consistent

### Playwright
Do **not** fork the test suite yet. Instead, prepare it to accept a provider env flag.

## Exit criteria
- no behavior change yet
- existing custom transport still works unchanged
- provider metadata exists end-to-end
- frontend transport abstraction exists

## Rollback
Safe: this phase should be pure refactor + metadata.

---

# Phase 1 — Backend LiveKit control-plane integration

## Goal
Teach the backend how to create and authorize LiveKit-backed sessions.

## Backend responsibilities to add
- LiveKit API credentials/config
- app session ↔ LiveKit room mapping
- LiveKit token issuance
- webhook endpoint for room/participant lifecycle
- signature verification for webhooks
- provider-aware session creation/join flow

## Likely backend additions
- LiveKit config in settings
- endpoint to mint room join tokens
- webhook endpoint
- room naming convention
- session metadata persistence for provider + room name

## Recommended API shape
### `POST /api/sessions`
Returns:
- `session_id`
- session tokens / role join data
- `media_provider`
- optionally room metadata if provider is `livekit`

### `POST /api/sessions/{id}/livekit-token`
Returns:
- room name
- participant identity
- signed LiveKit token

### `POST /api/livekit/webhooks`
Consumes:
- participant join/leave
- room started/finished
- track published/unpublished

## Tests first (TDD)
### Backend pytest
Add failing tests for:
- LiveKit token issuance requires valid session + role token
- tutor cannot mint student token and vice versa unless intended
- invalid/expired session is rejected
- webhook signature verification rejects bad signatures
- webhook updates session state correctly
- ended sessions cannot mint fresh join credentials

### No browser behavior change yet
Frontend should continue using custom provider by default.

## Exit criteria
- backend can issue LiveKit tokens correctly
- backend can process LiveKit webhook events safely
- current custom transport path is untouched

## Rollback
Disable `LSA_ENABLE_LIVEKIT`; existing provider continues to work.

---

# Phase 2 — Frontend LiveKit transport implementation behind a flag

## Goal
Tutor and student can complete a full session using LiveKit for media transport while the current analytics path remains unchanged.

## Frontend changes
Implement `LiveKitTransport` to provide the same high-level contract as the custom transport.

### Responsibilities
- connect to LiveKit room using backend-issued token
- publish local camera/mic tracks
- subscribe to remote tracks
- map LiveKit room/track state into the existing call status model
- preserve current local/remote video rendering contracts if possible
- preserve current mute/camera controls

## Keep unchanged initially
- consent UX
- tutor-only coaching UI
- analytics websocket hookup
- browser uploads for analytics frames/audio
- session summary generation path
- dashboard contracts

## TDD: tests first
### Frontend unit tests
Add failing tests for:
- LiveKit transport state mapping (`connecting`, `connected`, `reconnecting`, etc.)
- cleanup on leave/end session
- mute/camera toggles mapping correctly
- participant disconnect/reconnect semantics

### Playwright
Parameterize the current session suite to run against:
- `MEDIA_PROVIDER=custom_webrtc`
- `MEDIA_PROVIDER=livekit`

At this phase, allow a reduced initial subset for LiveKit if needed, but the end goal is full parity.

#### Must-pass scenarios
- tutor + student can join
- local and remote media visible
- tutor still gets coaching overlay/metrics
- student still does not see tutor metrics
- session end works for both sides
- analytics persist after session end

## Exit criteria
- LiveKit sessions work end-to-end in browser automation
- existing analytics path still functions while LiveKit is active
- no regression in tutor-only live guidance

## Rollback
Keep `media_provider=custom_webrtc` default; LiveKit only enabled for test/internal sessions.

---

# Phase 3 — Dual-stack parity and canary rollout

## Goal
Run both media providers in parallel until LiveKit proves it is equal or better.

## Rollout approach
- internal users only first
- staging environment fully enabled
- opt-in or allowlist in production/pilot
- compare metrics across providers

## TDD / coverage requirements
### Browser E2E matrix
Every high-value Playwright scenario should run against both providers:
- session creation
- tutor/student join
- live media appears
- reconnect within grace window
- student leaves / tutor sees disconnect state
- tutor ends session
- analytics detail page renders
- session metadata persists

### Backend tests
Provider-aware tests for:
- session creation with provider
- session info reflects provider
- token issuance
- webhook handling
- ended-session behavior

### Manual validation
At this phase, run non-localhost checks:
- two browsers
- two devices
- different networks
- TURN-required path
- long session soak

## Success metrics to compare
- join success rate
- time to first remote video
- reconnect recovery success rate
- unexpected disconnect rate
- browser error rate
- end-session summary availability
- tutor coaching latency

## Exit criteria
- LiveKit path matches or beats legacy path
- rollback remains trivial
- no major functional gaps remain in browser tests

## Rollback
Flip default provider back to legacy if needed.

---

# Phase 4 — Make LiveKit the default transport

## Goal
Switch the default media provider to LiveKit while keeping legacy transport available as a short-term fallback.

## Changes
- `LSA_DEFAULT_MEDIA_PROVIDER=livekit`
- keep `custom_webrtc` available only by explicit override
- update docs and operator runbooks
- monitor rollout closely

## Tests first / keep green
- full Playwright suite must still pass for LiveKit
- legacy smoke path may remain as a reduced fallback suite during retirement window

## Exit criteria
- the majority of real sessions run on LiveKit
- fallback is rarely needed
- operational metrics are stable

## Rollback
Immediate: revert default provider flag.

---

# Phase 5 — Move analytics ingestion off the browser and onto LiveKit room subscribers

## Goal
Upgrade from “LiveKit for call + browser uploads for analytics” to the cleaner final architecture.

## New architecture
Analytics workers join the room as hidden participants and subscribe to tutor/student tracks.

### Worker responsibilities
- subscribe to tutor video/audio and student video/audio
- run video/audio processing server-side
- compute metrics and coaching
- emit tutor-only live events
- write traces and summaries

## Why this phase is separate
Because this is not just a transport change. It changes the **source of truth** for analytics ingestion.

Separating it from the call migration keeps earlier phases much safer.

## TDD: tests first
### Backend/worker tests
Add failing tests for:
- worker can map LiveKit participant identities back to tutor/student roles
- worker emits the same metrics schema currently used by the UI
- coaching semantics stay compatible with existing summary/recommendation code
- session end still finalizes analytics correctly

### Replay/eval tests
Before switching production analytics ingestion, validate:
- same or better speaking time accuracy
- same or better interruption classification
- same or better attention/coaching semantics

### Browser tests
Browser UI should remain mostly unchanged. The tutor should not care whether metrics came from:
- browser uploads
- server-side room subscribers

That contract stability is a success condition.

## Exit criteria
- worker-driven analytics reach parity with browser-driven analytics
- browser media upload for analytics can be disabled safely
- coaching latency stays within budget

## Rollback
Keep browser-side analytics upload path behind a flag until parity is proven.

---

# Phase 6 — Remove legacy transport and duplicate browser analytics upload

## Goal
Delete migration complexity and converge on the final design.

## Remove
- custom websocket signaling for call media
- frontend legacy call transport
- provider branching no longer needed in normal code paths
- browser duplicate analytics media upload path (after parity proven)

## Keep
- stable tutor event contract
- stable summary/recommendation schema
- traces/eval infrastructure

## Exit criteria
- LiveKit is the sole production media transport
- analytics are room-subscriber driven
- legacy code no longer needed for rollback

---

## TDD Strategy

## Principle
Every phase should follow:
1. **Red**: add failing tests for the new behavior/contract
2. **Green**: add the minimum implementation to pass
3. **Refactor**: clean up while preserving a green suite

## Recommended test layers

### 1. Backend pytest (authoritative for session/control semantics)
Use for:
- provider metadata
- token issuance
- webhook validation
- lifecycle/finalization behavior
- worker integration points later

### 2. Frontend unit tests (new harness)
Recommended addition: **Vitest + RTL**

Use for:
- transport selection logic
- call-state mapping
- provider-independent session UI contracts
- cleanup behavior

### 3. Playwright browser tests
Use for:
- full tutor/student join flows
- remote media rendering
- reconnect flows
- tutor-only analytics visibility
- end-session → analytics availability
- provider parity

### 4. Manual real-network validation
Use for:
- TURN-required sessions
- two devices
- cross-network calls
- longer-duration soaks

### 5. Replay / eval harness
Especially important before browser-side analytics upload is removed.

Use for:
- coaching precision
- interruption semantics
- attention-state logic
- summary/recommendation regression

---

## Concrete Test Matrix

| Layer | Legacy provider | LiveKit provider | Notes |
|------|------------------|------------------|-------|
| Backend pytest | yes | yes | provider-aware tests |
| Frontend unit tests | yes | yes | provider selection + state mapping |
| Playwright smoke | yes | yes | same specs, parameterized |
| Manual cross-network | optional | required | LiveKit validation phase |
| Replay/eval | N/A initially | required before worker analytics cutover | compare semantics |

---

## Suggested First Failing Tests by Phase

### Phase 0
- backend: session creation persists `media_provider`
- frontend unit: session page chooses the correct transport implementation

### Phase 1
- backend: `POST /livekit-token` rejects invalid session/token
- backend: webhook signature verification rejects malformed payloads

### Phase 2
- frontend unit: LiveKit transport maps room state to existing call state labels
- Playwright: live call works with `media_provider=livekit`

### Phase 3
- Playwright: reconnect within grace period works for both providers
- Playwright: end session finalizes analytics for both providers

### Phase 5
- worker integration: tutor/student role mapping from LiveKit participant identity works
- replay/eval: worker-driven metrics stay within tolerance against recorded cases

---

## Rollout and Rollback Plan

## Rollout order
1. local dev behind flags
2. staging with LiveKit enabled
3. internal users only
4. limited production canary / allowlist
5. default provider switch
6. remove legacy only after multiple stable release cycles

## Rollback rule
At every phase before final removal, rollback must be achievable via:
- provider flag change
- disabling LiveKit issuance path
- leaving existing analytics path intact

If rollback requires emergency code surgery, the phase is not ready to ship.

---

## Observability Requirements
Add or confirm visibility into:
- join success/failure
- token issuance failures
- webhook signature failures
- room connect latency
- time to first remote video/audio
- reconnect success rate
- session end summary success
- tutor metrics delivery latency
- provider-specific error rates

Recommended tags on logs/metrics:
- `session_id`
- `media_provider`
- `role`
- `environment`
- later: `worker_id`

---

## API and Model Changes

## Session model
Add fields like:
- `media_provider`
- optional `livekit_room_name`
- optional `livekit_enabled_at`

## Session creation response
Should eventually include enough metadata for the client to know how to join, either directly or via follow-up calls.

## Session info endpoint
Should expose provider so the client can select transport cleanly.

## LiveKit token issuance
Must be role-aware and tied to the app session.

## Webhook handling
Must be idempotent and safe to replay.

---

## Risks and Mitigations

### Risk: transport migration breaks working browser flows
**Mitigation:** provider abstraction + Playwright matrix + fallback flag

### Risk: LiveKit join/presence semantics diverge from current session semantics
**Mitigation:** keep app session lifecycle authoritative in Product API/backend; do not let LiveKit alone define product truth

### Risk: analytics regress after later cutover to room-subscriber workers
**Mitigation:** replay/eval harness before browser upload removal

### Risk: rollout becomes hard to reverse
**Mitigation:** per-session provider field and default-provider flags until legacy removal

### Risk: frontend testing is too thin for provider refactor
**Mitigation:** add frontend unit harness in phase 0 instead of relying only on Playwright

---

## Definition of Done
The migration is complete only when all of the following are true:
- LiveKit is the sole production media provider
- tutor and student media flows no longer depend on custom websocket signaling
- tutor-only live coaching still works
- session summaries and analytics still work
- browser analytics media upload path is removed or fully disabled
- replay/eval coverage protects coaching/metric semantics after the cutover
- docs, runbooks, and test commands reflect the new architecture

---

## Recommended First Implementation Slice
If starting now, the highest-leverage first PR is:

### PR 1 — Migration seam only
- add `media_provider` to session metadata
- add provider abstraction on the frontend
- no runtime behavior change
- add backend tests for provider metadata
- add frontend unit harness and provider-selection tests
- keep all current browser tests green

### Why this first
It creates the seam that makes every later phase cleaner and safer.

---

## Recommended Verification Commands (current repo style)

### Backend
```bash
cd backend
uv run --python 3.11 --with-requirements requirements.txt pytest -q
```

### Frontend type/build
```bash
cd frontend
npx tsc --noEmit
npm run build
```

### Browser E2E
```bash
cd frontend
npm run test:e2e
```

### Later, after unit harness lands
```bash
cd frontend
npm run test:unit
```

---

## Final Recommendation
Proceed with the LiveKit migration **now**, but do it as a **test-first, provider-dual-stack migration**:
- LiveKit for call media first
- current analytics preserved during the transition
- full provider parity in browser tests
- only then move analytics ingestion to LiveKit room subscribers
- only then remove the old transport

That is the best path to a stronger production architecture without sacrificing the parts of the product that already work.
