# LLM Review Instructions

This guide is for any follow-up LLM or agent doing analysis on this repository.

## Goal

Produce a **verified** technical review of the project:
- current implementation state
- weaknesses and flaws
- missing functionality
- missing tests
- edge cases
- latency / performance risks
- documentation mismatches

Do **not** trust prior summaries blindly. Verify everything against code, docs, and runnable commands.

---

## Non-Negotiable Review Rules

1. **Read before claiming**
   - Do not infer behavior from filenames or comments alone.
   - Read the relevant implementation files before making claims.

2. **Run validation commands**
   - If you claim tests pass, run them.
   - If you claim frontend builds, build it.
   - If you claim Python compatibility, verify with the target version.

3. **Separate verified facts from interpretation**
   - Explicitly distinguish:
     - verified true
     - partially true / misleading
     - false
     - not yet verified

4. **Do not over-credit partial implementations**
   - If a feature exists in a model or helper but is not wired end-to-end, call that out.

5. **Check docs against code**
   - Many of the most important gaps in this repo are doc/implementation mismatches.

---

## Read Order

Read these first:

1. `docs/assignment.md`
2. `README.md`
3. `docs/deep-dive-review.md`
4. `docs/overnight-polish-plan.md`
5. `docs/api-reference.md`
6. `docs/decision-log.md`
7. `docs/limitations.md`
8. `docs/calibration.md`

Then inspect the actual implementation:

### Backend core
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/config.py`
- `backend/app/session_manager.py`
- `backend/app/ws.py`

### Metrics / coaching
- `backend/app/metrics_engine/engine.py`
- `backend/app/metrics_engine/speaking_time.py`
- `backend/app/metrics_engine/energy.py`
- `backend/app/coaching_system/rules.py`
- `backend/app/coaching_system/coach.py`

### Analytics / persistence
- `backend/app/analytics/summary.py`
- `backend/app/analytics/session_store.py`
- `backend/app/analytics/trends.py`
- `backend/app/analytics/router.py`

### Frontend critical path
- `frontend/src/app/page.tsx`
- `frontend/src/app/session/[id]/page.tsx`
- `frontend/src/app/analytics/page.tsx`
- `frontend/src/app/analytics/[id]/page.tsx`
- `frontend/src/lib/types.ts`
- `frontend/src/hooks/useWebSocket.ts`
- `frontend/src/hooks/useMetrics.ts`
- `frontend/src/hooks/useNudges.ts`

### Tests
Read the most important test files, especially:
- `backend/tests/test_websocket_e2e.py`
- `backend/tests/test_reconnect.py`
- `backend/tests/test_protocol_fuzz.py`
- `backend/tests/test_long_session_cleanup.py`
- `backend/tests/test_pipeline_latency.py`
- `backend/tests/test_coaching_rules.py`
- `backend/tests/test_metrics_engine.py`
- `backend/tests/test_summary.py`

---

## Commands You Should Run

### Backend tests (Python 3.11)
```bash
cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest -q
```

### Backend tests (Python 3.9)
```bash
cd backend && uv run --python 3.9 --with-requirements requirements.txt pytest -q
```

### Frontend build
```bash
cd frontend && npm run build
```

### Count backend test files
```bash
find backend/tests -maxdepth 1 -name 'test_*.py' | wc -l
```

### Optional: collect test counts for specific files
```bash
cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest tests/test_reconnect.py --collect-only -q
cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest tests/test_protocol_fuzz.py --collect-only -q
cd backend && uv run --python 3.11 --with-requirements requirements.txt pytest tests/test_long_session_cleanup.py --collect-only -q
```

---

## Current Verified Baseline

At the time this guide was last updated, the following had been verified:

- backend tests pass on **Python 3.11**
- backend tests pass on **Python 3.9**
- frontend build passes
- backend suite size is **267 passing tests**
- backend test file count is **22** `test_*.py` files

Do not repeat those claims without re-checking.

---

## High-Risk Areas to Scrutinize

These are the areas where previous summaries overclaimed or where partial implementations exist.

### 1. Reconnect / disconnect semantics
Look carefully at:
- `backend/app/ws.py`
- `backend/app/session_manager.py`
- `backend/tests/test_reconnect.py`
- `backend/tests/test_websocket_e2e.py`

Questions to answer:
- Does reconnect grace exist only in helpers, or does it work end-to-end?
- Is `session_end` emitted only when the session truly ends?
- Can the frontend incorrectly believe the session ended during grace?

### 2. Tutor identity / session metadata
Look carefully at:
- `backend/app/main.py`
- `backend/app/session_manager.py`
- `backend/app/analytics/summary.py`
- `frontend/src/app/page.tsx`

Questions to answer:
- Does the frontend actually send `tutor_id`?
- Does the frontend actually send `session_type`?
- Is `session_type` persisted into saved summaries?
- Are trends truly tutor-specific in the default UI flow?

### 3. Adaptive FPS
Look carefully at:
- `backend/app/models.py`
- `backend/app/metrics_engine/engine.py`
- `backend/app/ws.py`
- `frontend/src/app/session/[id]/page.tsx`

Questions to answer:
- Is `target_fps` emitted by the backend?
- Does the frontend actually adjust its send interval?
- Is the implementation clean, or timer/polling-based and fragile?
- Are there tests for frontend adaptive behavior?

### 4. Energy baseline vs coaching behavior
Look carefully at:
- `backend/app/metrics_engine/energy.py`
- `backend/app/coaching_system/rules.py`
- `backend/tests/test_long_session_cleanup.py`
- `backend/tests/test_coaching_rules.py`

Questions to answer:
- Is baseline tracking real?
- Does the coach actually use drop-from-baseline, or just an absolute threshold?
- Do the docs oversell baseline-aware coaching?

### 5. Retention cleanup
Look carefully at:
- `backend/app/analytics/session_store.py`
- runtime call sites

Questions to answer:
- Does cleanup exist only as a method?
- Is it invoked automatically anywhere?
- Are docs phrased as if retention is enforced automatically?

### 6. Latency claims
Look carefully at:
- `backend/tests/test_pipeline_latency.py`
- `backend/tests/fixtures/test_face.jpg`
- `backend/app/video_processor/*`

Questions to answer:
- Do latency tests exercise a true detected-face path?
- Are gaze/expression timings meaningful, or mostly near-zero because the face path is not fully engaged?
- Is there real evidence for the hot path staying under budget?

### 7. Frontend quality gates
Look carefully at:
- whether there are any frontend tests
- whether ESLint is configured
- session page state transitions

Questions to answer:
- Is the user-facing surface under-tested?
- Are there browser smoke tests?
- Are there likely UI state bugs around reconnect/session-end?

---

## What a Good Review Should Deliver

A strong follow-up review should include:

### 1. Verified status table
Example structure:
- backend tests: pass/fail
- frontend build: pass/fail
- Python versions verified: list
- frontend tests: present/absent
- browser smoke tests: present/absent

### 2. Claim audit
For any prior summary being reviewed, mark each important claim as:
- true
- partially true
- false
- unverifiable from current state

### 3. Implementation gaps
Call out missing or partial end-to-end flows, not just missing helper functions.

### 4. Testing gaps
Explicitly identify what is still not covered:
- browser-level
- websocket reconnect E2E
- real detected-face latency
- frontend state behavior
- metadata flow end-to-end

### 5. Documentation mismatches
List exact files where docs overstate behavior.

### 6. Prioritized next steps
Provide P0 / P1 / P2 recommendations.

---

## Specific Known Nuances

These are easy places to say something inaccurate if you review too quickly:

- The repo is **not** limited to Python 3.11; it has been verified on 3.9 and 3.11.
- Reconnect grace now exists, but that does **not** mean reconnect UX is fully browser-E2E validated.
- Tutor identity/session metadata now exists in backend APIs/models **and** the default frontend flow, but that does **not** mean the flow is thoroughly browser-tested.
- Energy baseline tracking now exists and is partially used by coaching, but that does **not** mean it is well-calibrated.
- Retention cleanup now exists and runs at startup, but that does **not** mean retention is continuously enforced during long-lived uptime.
- Adaptive FPS now exists, but that does **not** mean it is cleanly implemented or well-tested.

---

## Suggested Output File(s)

If you are asked to leave written artifacts, prefer:
- `docs/<date>-review.md`
- `docs/<date>-verification-notes.md`
- `docs/<date>-followup-plan.md`

Keep the output evidence-based and cite exact files.

---

## Final Reminder

This repository has improved meaningfully, but it still contains several **partial implementations that look more complete than they are**.

Your job is to distinguish:
- what exists,
- what works end-to-end,
- what is only helper-level,
- and what is still just documented intent.
