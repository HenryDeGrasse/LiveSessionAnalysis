# Epic: Real Tutoring Session Experience

## Goal
Turn the current analytics-only session flow into a real tutoring session experience where the tutor and student can see and hear each other live while the backend continues to compute coaching metrics and post-session analytics. For Nerdy AI, this is not a polish item; it is a product requirement. A live tutoring analytics product that does not actually support the live session itself is missing the core user experience.

## Current Implementation Status
Verified in code/tests/builds:
- both participants grant camera/mic access
- both participants still send media-derived data to the backend for analytics
- the tutor still gets metrics and nudges
- the session websocket now relays WebRTC signaling (`offer` / `answer` / `ice_candidate`)
- the session page now has a live call surface with large remote media + small local self-view
- the tutor overlay is now minimal by default, with denser diagnostics behind the debug toggle
- backend signaling relay is covered by websocket E2E tests

Still open / not yet fully verified:
- manual two-device / cross-network smoke confirmation beyond localhost and fake-media browser coverage
- production-grade NAT traversal / TURN reliability
- longer-duration soak validation for reconnect/resource stability
- richer analytics/admin views after the live-call work

## Proposed Architecture (MVP)
Adopt a **dual-path media architecture**:

1. **Real-time tutoring call path:**
   - Use **WebRTC peer media** between tutor and student for live audio/video.
   - Use the existing authenticated WebSocket session channel as the **signaling transport** for SDP offers/answers and ICE candidates.
   - Render both **local preview** and **remote participant media** on the session page.

2. **Analytics path:**
   - Keep the current backend analytics ingestion path for now.
   - Reuse the same local `MediaStream` for:
     - WebRTC peer playback
     - backend analytics upload (video frames + PCM chunks)
   - Continue computing gaze, speaking time, interruptions, energy, coaching nudges, and post-session summaries in the backend.

This means **WebRTC is only for peer media playback/UI** in the MVP. The backend does **not** become an RTP/WebRTC media endpoint. Each participant still uploads their own local analytics stream to the existing backend pipeline.

This keeps the current analytics investment intact while adding the missing product experience.

## Why this architecture
- **Fastest path to usable product behavior:** users get a real tutoring call without rewriting the analytics backend first.
- **Minimal architectural disruption:** analytics pipeline can stay role-tagged and server-side.
- **Reasonable MVP complexity:** two-party WebRTC is far simpler than introducing an SFU immediately.
- **Future-proof enough:** if scale or reliability demands it later, peer media can migrate to an SFU while preserving analytics concepts and UI semantics.
- **Non-blocking for rubric-critical work:** metric accuracy, latency, coaching quality, and post-session analytics remain testable through the existing deterministic backend pipeline whether peer media is enabled or not.

## Scope (MVP)
- Two-party live video/audio between tutor and student
- Local + remote media rendering in the session UI
- WebRTC offer/answer/ICE signaling over the existing session WebSocket
- Reconnect-aware peer-call recovery for normal page refresh / transient disconnects
- Preserve current analytics flow and tutor-only coaching nudges
- Keep analytics-only mode available behind a feature flag (`ENABLE_WEBRTC_CALL_UI`) so the rubric-safe path still exists while peer media is being integrated
- Basic call-state UX:
  - waiting for participant
  - connecting media
  - connected
  - participant disconnected / reconnecting
  - session ended
- Configurable ICE server list for local/dev/prod environments
- Manual smoke test instructions and debug visibility for call setup

## Non-Goals
- Group sessions / more than two participants
- Recording, playback, or archival of raw call media
- Full production-grade SFU/media-server rollout in this iteration
- Cross-platform native mobile support
- End-to-end encryption design beyond standard WebRTC transport expectations
- Replacing the backend analytics ingestion path yet

## Architecture Notes
### Current architecture to preserve
- Separate role-tagged participants remain the right model for analytics.
- Tutor-only nudges remain the right product behavior.
- Existing session tokens remain the right lightweight auth primitive for now.

### New pieces to add
- `webrtc_signal` message type in the WS protocol
- peer connection lifecycle in the frontend
- remote media element(s) in the session page
- ICE server configuration surface
- signaling relay behavior in the backend session room
- a clear transport split on the existing websocket:
  - **text/JSON frames** = signaling + small control messages
  - **binary frames** = analytics media payloads
- deterministic offer flow for MVP:
  - **tutor is the offerer**
  - student answers
  - avoid perfect-negotiation complexity unless it becomes necessary

### Target session flow
1. Tutor creates session and opens session page.
2. Tutor grants camera/mic.
3. Tutor local stream is attached to:
   - local preview
   - peer connection tracks
   - analytics upload pipeline
4. Student joins and grants camera/mic.
5. Backend relays signaling messages between roles.
6. WebRTC connects; each participant sees/hears the other.
7. Existing analytics continue in parallel.
8. On disconnect, UI shows reconnect state; on reconnect, peer connection renegotiates if needed.
9. On end session, call ends for both participants and analytics finalize.

## Implementation Tasks

## Testing / Validation Philosophy
- Keep automated validation focused primarily on the analytics pipeline, metrics accuracy, coaching behavior, and latency budgets.
- Treat WebRTC as a product UX layer in MVP:
  - backend signaling gets unit/E2E coverage
  - peer media gets documented manual smoke tests
  - browser automation is useful but should not block the analytics deliverables
- This prevents the peer-media work from derailing the assignment's highest-weight scoring areas.

### Phase 1 — Signaling and media foundations
1. **Add WebRTC signaling protocol to backend websocket flow** — relay SDP/ICE between tutor and student.
   - Files: `backend/app/models.py`, `backend/app/ws.py`, `docs/api-reference.md`
   - Steps:
     1. add explicit websocket message types for signaling and participant-presence notifications
     2. relay `offer`, `answer`, and `ice_candidate` payloads only to the opposite role in the same room
     3. keep existing metrics/nudge/session messages intact
     4. document the signaling payload shape
   - Verify: `cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest -q`
   - Depends on: none

2. **Add a frontend peer connection hook** — encapsulate WebRTC lifecycle for two-party sessions.
   - Files: `frontend/src/hooks/usePeerConnection.ts`, `frontend/src/lib/types.ts`
   - Steps:
     1. create an `RTCPeerConnection`
     2. attach local stream tracks
     3. emit signaling messages via existing websocket hook
     4. surface remote stream, connection state, and errors
     5. handle ICE candidate exchange and teardown
   - Verify: `cd frontend && npm run build && npx tsc --noEmit`
   - Depends on: task 1

3. **Add remote media rendering to the session page** — make the call visible and audible.
   - Files: `frontend/src/app/session/[id]/page.tsx`, `frontend/src/hooks/usePeerConnection.ts`
   - Steps:
     1. render local and remote video panes
     2. autoplay remote audio/video correctly
     3. show waiting/connecting/connected states
     4. keep the minimal tutor overlay and local controls usable, with detailed diagnostics behind the debug toggle
   - Verify: `cd frontend && npm run build && npx tsc --noEmit`
   - Depends on: task 2

### Phase 2 — Reliability and UX
4. **Integrate reconnect-aware call recovery** — recover peer media after transient disconnects.
   - Files: `frontend/src/app/session/[id]/page.tsx`, `frontend/src/hooks/usePeerConnection.ts`, `backend/app/ws.py`
   - Steps:
     1. tie peer connection resets to participant disconnect/reconnect events
     2. renegotiate after reconnect when needed
     3. ensure the tutor disconnect banner and peer media state agree
     4. ensure ending the session tears down WebRTC cleanly
   - Verify: manual reconnect smoke in two browsers; backend tests still pass
   - Depends on: tasks 1–3

5. **Add ICE server configuration and environment docs** — make local/dev/prod connectivity realistic.
   - Files: `frontend/src/lib/constants.ts`, `README.md`, `docs/real-tutoring-session-experience-plan.md`
   - Steps:
     1. define configurable ICE servers from env
     2. document localhost expectations vs real NAT traversal needs
     3. call out that TURN is required for production reliability
   - Verify: `cd frontend && npm run build && npx tsc --noEmit`
   - Depends on: task 2

6. **Polish session call UX** — align the page with an actual tutoring product.
   - Files: `frontend/src/app/session/[id]/page.tsx`, optionally small shared UI components
   - Steps:
     1. label local vs remote video clearly
     2. keep mute/camera/end-session controls visible
     3. surface remote-audio / remote-video unavailable states
     4. keep the tutor overlay subtle and minimalist so the call stays primary
   - Verify: manual smoke in tutor + student windows
   - Depends on: task 3

### Phase 3 — Validation and observability
7. **Add backend websocket tests for signaling relay** — prove SDP/ICE messages route correctly.
   - Files: `backend/tests/test_websocket_e2e.py`, optionally `backend/tests/test_protocol_fuzz.py`
   - Steps:
     1. connect tutor and student sockets
     2. send synthetic signaling messages from one side
     3. assert the opposite side receives them unchanged
     4. assert invalid routing/auth still fails cleanly
   - Verify: `cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest -q`
   - Depends on: task 1

8. **Add browser smoke tests for live peer media setup** — cover the actual product gap.
   - Files: browser test harness / `e2e/*`, session page helpers
   - Steps:
     1. create/join a session in two browser contexts
     2. grant fake media
     3. assert remote media elements appear and call state becomes connected
     4. assert analytics/debug state still appears for tutor
   - Verify: browser smoke test command once harness exists
   - Depends on: tasks 2–6

9. **Add call debug instrumentation** — make failures diagnosable during rollout.
   - Files: `frontend/src/app/session/[id]/page.tsx`, `docs/api-reference.md`
   - Steps:
     1. expose peer connection state, ICE state, signaling state, remote-track presence in debug UI
     2. log significant call events to the debug panel
     3. distinguish analytics websocket issues from WebRTC media issues
   - Verify: manual check with `?debug=1`
   - Depends on: tasks 2–3

## Acceptance Criteria
- [x] Tutor and student can see each other live in the session page on localhost (Playwright fake-media coverage).
- [x] Tutor and student can hear each other live in the session page on localhost (Playwright remote-audio-track coverage).
- [x] Existing backend analytics still function while peer media code is active in the session UI.
- [x] Analytics-only mode remains available behind `NEXT_PUBLIC_ENABLE_WEBRTC_CALL_UI=false`.
- [x] Tutor still receives metrics and nudges; student still does not.
- [x] Refreshing one participant within the reconnect grace period has a code path that renegotiates peer media.
- [x] Ending a session tears down peer media state in the session UI and still finalizes analytics.
- [x] WebRTC signaling is backend-tested.
- [x] Manual smoke-test steps are documented for two-browser / two-device validation.
- [x] The project does not claim broad internet-traversal reliability without TURN.

## Risks / Notes
- **TURN is a real requirement for production.** Pure peer-to-peer may work on localhost and some home networks but will fail often without TURN.
- **Using the same local stream twice is acceptable for MVP.** The browser can attach one `MediaStream` to both WebRTC and analytics upload, but CPU/network impact should be monitored.
- **Do not relay raw peer media through the current FastAPI websocket path.** That would create a much bigger scalability and latency problem than needed.
- **Keep the analytics path separate for now.** Re-architecting analytics onto WebRTC itself is a follow-up, not an MVP requirement.
- **Do not overclaim privacy/network posture.** STUN/TURN choices should be documented precisely; a public STUN server is not the same thing as third-party analytics, but it is still an external network dependency.
- **If two-party reliability becomes insufficient, migrate to an SFU later.** The next likely candidates would be LiveKit / mediasoup / Janus rather than growing a custom relay.

## Manual Smoke Test
1. Start backend and frontend locally.
2. Open the tutor link in one browser/profile and the student link in another.
3. Grant camera/mic on both sides.
4. Confirm each side sees:
   - large remote participant video area
   - small local self-view
   - live audio playback from the other side
5. Confirm the tutor still receives:
   - minimal live coaching pills
   - metrics/nudges only on the tutor side
   - richer call/debug state under `?debug=1` or the `Coach debug` toggle
6. Refresh one side during an active session and confirm:
   - the other side shows reconnect state
   - the refreshed side rejoins within grace period
   - peer media renegotiates
7. End the session from either side and confirm:
   - peer media UI tears down
   - analytics become available afterward

## Automated Browser Coverage
Playwright now covers the highest-value browser paths with fake media devices:
- tutor + student call setup in separate browser contexts
- remote media present on both sides
- tutor-only analytics visibility
- reconnect recovery within the grace period
- end-session finalization + analytics persistence

Run:
```bash
cd frontend
npm run playwright:install   # first time only
npm run test:e2e
```

## Recommended Execution Order
1. Backend signaling relay
2. Frontend peer connection hook
3. Remote media rendering
4. Reconnect-aware recovery
5. ICE config + docs
6. Signaling tests
7. Browser smoke tests
8. UX polish and debug instrumentation
