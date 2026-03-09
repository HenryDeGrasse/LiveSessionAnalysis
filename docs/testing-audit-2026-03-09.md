# Testing Audit — 2026-03-09

## Verified Current Status

### Commands re-run
```bash
cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest -q
cd backend && uv run --python 3.9 --with-requirements requirements.txt pytest -q
cd frontend && npx tsc --noEmit
cd frontend && npm run build
cd frontend && npm run test:e2e
```

### Current verified results
- **Backend tests (Python 3.11): 281 passed**
- **Backend tests (Python 3.9): 281 passed**
- **Frontend TypeScript: pass**
- **Frontend production build: pass**
- **Playwright browser suite: 5 passed**

### New since the first audit draft
- a privacy-safe local session trace layer now exists under `backend/app/observability/`
- fast offline eval scaffolding now exists under `backend/tests/evals/`
- backend coverage now includes trace persistence, WebRTC signaling sanitization, coaching decision metadata, and a first production-model-validated golden fixture
- the initial accuracy pack now replays compact signal traces through production metrics/coaching code and checks speaking-time ratio, eye-contact score bins, hard/backchannel/echo interruption semantics, and attention-state coaching semantics (`SCREEN_ENGAGED` / `DOWN_ENGAGED` suppression vs `FACE_MISSING` / `OFF_TASK_AWAY` concern)
- a first replay tier now exists under `backend/tests/evals/test_replay.py` using recorded session traces plus separate expectation files to compare replayed outputs against stored recorded metrics/lifecycle expectations

## What is deeply tested right now

### Backend / analytics / metrics
The backend test suite is broad and meaningfully exercises the hard parts of the product:
- face detection / gaze / expression modules
- VAD / prosody / speech gating
- speaking-time and interruption semantics
- coaching rule behavior and cooldown guardrails
- attention-state classification
- metrics aggregation and summary generation
- session persistence / retention / trends / recommendations
- reconnect logic and websocket protocol behavior
- malformed-payload fuzz coverage
- short-session analytics persistence regression
- privacy-safe trace capture and persistence
- coaching decision-trace metadata and suppression reasons
- fast offline eval fixture validation against production trace models

This is not shallow test count padding. The core metrics/coaching/analytics backend is genuinely well-covered for the current scope.

### Browser-level product flows
Playwright now covers the highest-value real browser flows:
- tutor + student live-call join in separate browser contexts
- fake camera/microphone permission flow
- remote media presence on both sides
- tutor-only analytics visibility
- student clean local leave flow
- tutor end-for-everyone flow
- reconnect within grace period
- analytics persistence after session end
- redesigned analytics dashboard rendering and drill-down
- UI-created tutor/session-type metadata reaching persisted analytics and analytics UI

These browser tests already exposed and fixed real integration bugs, including:
- queued WebRTC events racing page readiness
- isolated-port CORS issues
- empty short sessions not persisting analytics summaries
- live call state mismatches in headless runs

## What is still not deeply tested

### 1. Real network / TURN / device variability
Current browser tests use Chromium with fake media devices on localhost.

That is excellent for deterministic regression coverage, but it is **not** the same as:
- two real machines
- different networks
- TURN-required traversal
- flaky Wi‑Fi / bandwidth drops
- real camera/mic hardware behavior

**Conclusion:** browser integration is strong on localhost, but production-like WebRTC reliability still needs manual cross-device validation and later a broader matrix.

### 2. Frontend unit-level harness
There is still no dedicated frontend unit/integration harness (e.g. Vitest + React Testing Library) for:
- analytics helper functions in `frontend/src/lib/analytics.ts`
- smaller page state transitions without running full Playwright
- hook-level regression tests

This is not a launch blocker today because Playwright now covers the highest-risk UX, but it is the main remaining automated-test gap on the frontend.

### 3. Long-duration browser soaks / resource behavior
No automated test currently runs a 20–60 minute browser session to catch:
- memory growth
- media-track leaks
- repeated reconnect churn
- gradual UI degradation

### 4. Visual regression testing
There is no screenshot baseline / visual diff testing. Layout/design regressions would currently be caught only by manual review or broad Playwright failures.

### 5. Ground-truth quality evals for coaching quality
The heuristics are unit-tested, but there is not yet a labeled evaluation corpus answering questions like:
- when should a low-eye-contact nudge fire?
- when is an interruption “real” vs backchannel/echo?
- are recommendations high-quality across many session summaries?

## Does an eval framework make sense now?

### Yes — **offline deterministic evals** make sense now
This project is at a stage where offline evals would create real value.

The best next eval layers would be:

#### A. Recommendation quality evals
Create a curated set of saved `SessionSummary` fixtures with expected recommendation outputs.

Use them to verify:
- recommendation presence/absence
- session-type-specific recommendation behavior
- wording regressions
- risk-priority ordering if ordering becomes more important later

This is especially useful because recommendations are already product-facing and can drift silently.

#### B. Coaching precision evals on saved metric traces
Create fixture traces of `MetricsSnapshot` sequences representing cases like:
- productive discussion
- lecture-heavy but acceptable session
- real tutor overtalk
- real student disengagement
- backchannels that should not trigger interruption coaching
- echo-like overlap cases

Then evaluate:
- whether nudges fire
- when they fire
- how many fire
- whether they respect global suppression/warmup rules

This would act like a mini regression benchmark for coaching precision.

#### C. Media/attention fixture evals
For the attention-state model, an eval set would be useful for cases such as:
- face missing
- screen engaged
- down engaged
- off-task away
- low confidence

That would help avoid drifting back toward noisy visual-attention behavior.

### What kind of eval system is probably *too much* right now?
- LLM-as-judge eval infrastructure
- expensive cloud eval orchestration
- fully automated “AI coach quality” scoring without labeled expectations

The rules/analytics are still deterministic enough that simpler golden-fixture evals are a better ROI.

## Do A/B tests make sense now?

### Mostly **not yet** for core behavior
For the current stage, classic production A/B testing is probably premature for core session behavior.

Reasons:
- likely not enough real traffic yet
- product still changing quickly
- reliability and clarity matter more than optimizing small deltas
- core behaviors should be made correct/stable before experimentation

### A/B tests that *could* make sense later
Once real usage exists and instrumentation is in place, these are reasonable candidates:

#### 1. Tutor live overlay density
Compare:
- ultra-minimal 3-pill overlay
- slightly more explicit status copy

Primary success metrics:
- tutor debug-toggle usage
- nudge dismiss rate
- session completion rate
- subjective tutor usefulness feedback

#### 2. Analytics review prioritization copy
Compare:
- “Needs review / Watchlist / On track”
- more operational labels like “Priority review / Review soon / Healthy”

Primary success metrics:
- analytics clickthrough to detail pages
- time spent on flagged sessions
- recommendation follow-up interactions

#### 3. Invite/join wording on the home page
Compare invite and role framing copy to improve successful first-join completion.

Primary success metrics:
- session creation -> student join completion
- time from create to both-participants-connected
- abandonment before consent

### A/B tests that should wait
Do **not** A/B test these yet:
- reconnect grace semantics
- end-session semantics
- student visibility of analytics/nudges
- anything that changes privacy expectations
- anything that materially changes WebRTC reliability behavior

Those should remain product decisions, not experiments, until the system is more mature.

## Recommended next testing priorities

### P0
1. **Add offline golden evals for recommendations and coaching traces**
2. **Run manual two-device / two-browser / TURN-aware smoke tests and document results**
3. **Add at least one longer browser soak scenario**
4. **Add a fixture-promotion helper for replay traces** so real saved traces can be turned into `fixtures/recorded/*.json` + expectation pairs quickly
5. **Add browser debug trace export on Playwright failure** so tutor/student debug state is saved alongside screenshots/videos
6. **Expand replay cases** for:
   - short-session persistence
   - reconnect with no peer recovery
   - face-missing / degradation transitions over time

### P1
7. Add lightweight frontend unit tests for `frontend/src/lib/analytics.ts`
8. Add a browser test for analytics filter persistence in URL/state if that UX becomes important
9. Add visual regression snapshots if UI polish becomes a frequent concern

## Bottom line
Right now, the project is **strongly tested for its current stage**, especially compared with where it started:
- backend logic is deeply tested
- browser integration coverage exists and is meaningful
- critical tutor/student/analytics flows are now exercised in a real browser

But it is not “everything is proven under all conditions.”

The main remaining test gaps are:
- real-network WebRTC validation
- frontend unit harness depth
- longer-duration browser soaks
- offline golden evals for coaching/recommendation quality

If we want the highest-leverage next step, it is **not** broad A/B testing yet.
It is **offline evals + manual real-network validation**.
