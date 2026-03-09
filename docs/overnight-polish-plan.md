# Overnight Polish Plan

> **Historical note**: this plan captured an earlier polish pass before the current WebRTC/browser-integration state landed. Several items below are now complete, including in-app peer media, Playwright browser smoke coverage, reconnect UI coverage, and browser validation of tutor/session metadata flow. For the current verified test state, see `docs/testing-audit-2026-03-09.md`. For the current production-direction plan, see `docs/web-production-mvp-plan.md`.

## Goal

Use the latest progress as a base, then finish the parts that are still only partially implemented or only unit-tested. The repo is now stronger than before, but the remaining work is concentrated in a few high-impact areas: reconnect correctness, end-to-end metadata flow, real hot-path validation, and frontend test coverage.

---

## Current Starting Point

Verified as of this pass:
- backend suite passes at **267 tests**
- backend tests pass on **Python 3.9 and 3.11**
- frontend builds successfully
- audio streaming exists end-to-end in the browser path

New product-level finding:
- the app still does **not** provide actual tutor↔student in-app media playback, so it is not yet a full tutoring session experience
- fixing that gap is now a higher priority than additional analytics polish
- implementation planning for that work lives in `docs/real-tutoring-session-experience-plan.md`
- backend rate limiting exists
- `target_fps` plumbing exists end-to-end
- reconnect grace-period code exists
- `participant_disconnected` / `participant_reconnected` messaging exists
- retention cleanup runs at startup
- recent-window overtalk metric exists
- energy baseline tracking exists and is partially used by coaching
- a real detected-face latency fixture exists
- the home page now sends both `tutor_id` and `session_type`
- `session_type` now persists into saved summaries

Still missing or incomplete:
- no in-app peer media path for the real tutoring session experience
- no browser reconnect smoke/E2E coverage
- no browser smoke tests for the metadata flow
- reconnect media/metrics continuity is still under-validated
- baseline-drop calibration is still simplistic even though the threshold is now configurable
- frontend tests / linting are still absent

---

## Scope (Next Meaningful Iteration)

- Add the missing real tutor↔student media experience
- Finish partial real-time stability work
- Finish end-to-end personalization/metadata flow
- Add the missing validation layers
- Tighten documentation to match actual code

> For the dedicated peer-media architecture plan, see `docs/real-tutoring-session-experience-plan.md`.

## Non-Goals

- Full production auth/permissions system
- Multi-participant/group tutoring support
- New ML models or cloud inference services

---

## Phase 1 — Finish validation around the real-time loop

### 1. Add stronger websocket reconnect E2E coverage
- **Why:** reconnect signaling exists now, but coverage is still thin relative to the importance of the feature
- **Files:** `backend/tests/test_websocket_e2e.py`, optionally `backend/tests/test_reconnect.py`
- **Steps:**
  1. connect both participants
  2. disconnect one participant
  3. reconnect within grace
  4. assert session is still live and reconnect messaging behaves correctly
  5. verify finalization only happens after grace expiry when appropriate
- **Verify:**
  - websocket reconnect path is covered, not just helper functions

### 2. Add browser reconnect smoke coverage
- **Why:** backend/websocket behavior is improved, but the real tutor UI path is still unproven
- **Files:** browser test harness / e2e directory
- **Steps:**
  1. start a session in a browser test
  2. simulate student disconnect / reconnect
  3. verify disconnect banner appears then clears
  4. verify session does not show ended state prematurely
- **Verify:**
  - reconnect UX works in the real UI, not only in backend tests

### 3. Clean up adaptive client FPS handling
- **Why:** `target_fps` exists, but the frontend implementation is ref/polling based and not yet elegant
- **Files:** `frontend/src/app/session/[id]/page.tsx`, `frontend/src/hooks/*` if needed
- **Steps:**
  1. replace interval restart polling with state-driven scheduling
  2. ensure only one frame timer exists at a time
  3. add clear invariants for timer lifecycle
- **Verify:**
  - no interval leaks
  - send rate changes when `target_fps` changes
  - build still passes

---

## Phase 2 — Finish metadata / analytics truthfulness

### 4. Add browser coverage for tutor/session metadata flow
- **Why:** metadata wiring exists now, but there is still no browser-level proof that the UI-selected values survive end-to-end
- **Files:** browser test harness / e2e directory, docs as needed
- **Steps:**
  1. create a session from the home page with `tutor_id` and non-default `session_type`
  2. complete a short session
  3. verify saved analytics preserve both pieces of metadata
- **Verify:**
  - the UI-created metadata path is covered end-to-end

### 5. Calibrate and configure baseline-drop energy coaching
- **Why:** baseline-drop logic now exists and the threshold is configurable, but the behavior is still only lightly validated
- **Files:** `backend/app/config.py`, `backend/app/metrics_engine/energy.py`, `backend/app/coaching_system/rules.py`, tests
- **Steps:**
  1. add tests around threshold tuning and stable-low-energy sessions
  2. document the intended calibration range
  3. verify the default threshold is sensible against more realistic fixtures
- **Verify:**
  - calm-but-stable sessions do not spuriously fire
  - real drop scenarios do fire

---

## Phase 3 — Close the biggest validation gaps

### 7. Expand real detected-face latency coverage
- **Why:** a real detected-face fixture now exists, but one sample is not enough for strong confidence
- **Files:** `backend/tests/fixtures/*`, `backend/tests/test_pipeline_latency.py`, `backend/tests/test_face_detector.py`
- **Steps:**
  1. add more detected-face samples with different poses/lighting
  2. verify FaceMesh detects each of them in test
  3. compare stage timings across the detected-face set
- **Verify:**
  - gaze/expression timings are non-trivial and real
  - latency claim is backed by more than one hot-path sample

### 8. Add browser smoke tests
- **Why:** still no proof of the real browser flow
- **Files:** frontend test harness / Playwright config / e2e directory
- **Steps:**
  1. add a minimal frontend/browser test runner
  2. create one live-session smoke path
  3. create one analytics smoke path
- **Verify:**
  - browser can create/join a session and receive visible metrics state

### 9. Add frontend behavior tests
- **Why:** user-facing logic is still the least protected area
- **Files:** frontend test setup and targeted files
- **Focus areas:**
  - adaptive FPS interval changes
  - role resolution
  - session-end vs reconnect UI state
  - chart value transforms
  - nudge dismissal behavior
- **Verify:**
  - targeted frontend tests run in CI/local dev

---

## Phase 4 — Documentation truth pass

### 10. Reconcile remaining documentation with actual implementation
- **Why:** some doc truth issues were fixed in this pass, but metadata/reconnect/runtime semantics still need a clearer write-up
- **Files:** `docs/limitations.md`, `docs/api-reference.md`, `docs/privacy-analysis.md`, `README.md` (if UI metadata flow changes)
- **Steps:**
  1. clarify reconnect grace behavior vs final session end
  2. state which metadata features are API-level vs fully wired in the default UI
  3. document retention cleanup as a utility unless/since it is scheduled automatically
  4. update runtime instructions if frontend metadata flow changes
- **Verify:**
  - no doc claims behavior that code does not implement

---

## Acceptance Criteria

- [x] `session_end` is emitted only when the session truly ends
- [x] reconnect within grace works in a backend/websocket E2E test
- [ ] client adaptive FPS is simplified and directly tested
- [x] `tutor_id` and `session_type` flow from the UI into persisted analytics in the main code path
- [x] `session_type` survives save/load and influences downstream recommendations correctly
- [x] `energy_drop` uses real baseline/drop logic
- [x] latency tests exercise a real detected-face path
- [ ] at least one browser smoke test exists
- [ ] docs are aligned with actual runtime behavior

---

## Recommended Execution Order

### If only 1–2 hours are available
1. Add browser reconnect smoke coverage
2. Add browser metadata smoke coverage
3. Fix remaining doc truth around runtime limitations

### If half a day is available
1. Browser reconnect smoke coverage
2. Browser metadata smoke coverage
3. Baseline-threshold configuration
4. Clean up adaptive FPS timer logic
5. Frontend unit test bootstrap

### If a full overnight pass is available
1. Phase 1 entirely
2. Phase 2 entirely
3. Expand the detected-face fixture set
4. Browser smoke tests
5. Frontend unit/integration coverage
6. Documentation truth pass

---

## Context Notes for the Next Pass

The most important nuance after verification is this:

Several new capabilities now **exist**, but many of them are only **partially finished**.

The best next work is not inventing new features; it is finishing and proving the ones that were just added:
- reconnect grace
- adaptive FPS
- tutor/session metadata
- energy baseline logic
- retention behavior

See `docs/deep-dive-review.md` for the detailed verification notes behind this plan.
