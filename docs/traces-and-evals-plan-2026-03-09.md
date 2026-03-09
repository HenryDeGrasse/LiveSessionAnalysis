# Traces + Evals Plan for LiveSessionAnalysis

_Date: 2026-03-09_

## Implementation status

Initial Phase 1 + Phase 2 groundwork is now in the repo, plus the first Phase 3 replay slice:
- `backend/app/observability/trace_models.py`
- `backend/app/observability/trace_store.py`
- `backend/app/observability/trace_recorder.py`
- session lifecycle / coaching / signaling hooks in `backend/app/ws.py`
- fast eval scaffolding in `backend/tests/evals/`
- replay helper for compact signal traces in `backend/tests/evals/replay.py`
- exact-value replay assertions in the eval harness for state/category checks
- initial accuracy-pack fixtures for speaking-time ratio, eye-contact, hard/backchannel/echo interruption semantics, and attention-state coaching semantics
- recorded replay fixtures + replay tests in `backend/tests/evals/test_replay.py` and `backend/tests/evals/fixtures/recorded/`
- pytest markers in `backend/pytest.ini`

This document still describes the broader target architecture, but the first working slice has started.

## Why this plan

I reviewed **AgentForge** as the main reference repo and pulled the parts that are a strong fit for this project.

The most useful AgentForge patterns are:
- **schema-validated eval case definitions**
  - `AgentForge/apps/api/test/ai/eval-case.schema.ts`
- **shared assertion helpers for eval tiers**
  - `AgentForge/apps/api/test/ai/eval-assert.ts`
- **deterministic fast tier using production schemas/models so fixtures cannot drift silently**
  - `AgentForge/apps/api/test/ai/fixtures/tool-profiles.ts`
- **replay tier using recorded real sessions to catch regression without paying live-model cost every run**
  - `AgentForge/apps/api/test/ai/golden-sets-replay.spec.ts`
- **optional live tier behind env flags and budget gates**
  - `AgentForge/apps/api/test/ai/golden-sets.spec.ts`
- **optional trace service that no-ops cleanly when disabled**
  - `AgentForge/apps/api/src/app/endpoints/ai/observability/langfuse.service.ts`
- **structured telemetry that is machine-readable and explicitly privacy-aware**
  - `AgentForge/apps/api/src/app/endpoints/ai/agent/react-agent.service.ts`
  - `AgentForge/apps/api/src/app/endpoints/ai/agent/react-agent.service.spec.ts`

## What to copy vs what not to copy

## Copy
- multi-tier eval design
- fixture-first golden sets
- replay from recorded real runs
- structured telemetry with explicit privacy boundaries
- env-gated heavier tiers
- strong case metadata and assertion ergonomics

## Do **not** copy directly
- LLM-specific live eval design
- Langfuse as the first tracing layer
- thumbs-up/down trace scoring loop

This repo is currently a **real-time media/analytics/coaching** system, not an LLM agent. The best analogue to AgentForge's recorded LLM sessions is **recorded metrics/coaching/session traces**, not model transcripts.

---

## Recommended architecture for this repo

## 1. Add a local structured trace format first

Implement a **local JSON trace format** for completed sessions and eval runs.

### Why
- fits the current deterministic metrics/coaching architecture better than cloud AI tracing
- supports replay evals immediately
- preserves privacy by storing only structural/numeric state
- gives us debuggable artifacts when a browser test or manual session behaves oddly

### Proposed trace model

Create a backend-side trace schema, for example in:
- `backend/app/observability/trace_models.py`
- `backend/app/observability/trace_store.py`

Suggested models:

```python
class TracePoint(BaseModel):
    seq: int
    t_ms: int  # monotonic milliseconds since session start
    timestamp: datetime

class SessionEvent(TracePoint):
    event_type: Literal[
        "tutor_connected",
        "student_connected",
        "participant_ready",
        "participant_disconnected",
        "participant_reconnected",
        "session_end_requested",
        "session_end",
        "degradation_changed",
        "webrtc_signal_relayed",
    ]
    role: Optional[Literal["tutor", "student"]] = None
    data: dict = Field(default_factory=dict)

class VisualSignalPoint(TracePoint):
    role: Literal["tutor", "student"]
    face_present: bool
    gaze_on_camera: Optional[bool] = None
    attention_state: Optional[str] = None
    confidence: float = 0.0

class AudioSignalPoint(TracePoint):
    role: Literal["tutor", "student"]
    speech_active: bool
    rms_db: Optional[float] = None
    noise_floor_db: Optional[float] = None

class OverlapSegment(BaseModel):
    start_t_ms: int
    end_t_ms: int
    overlap_type: Literal["hard", "backchannel", "echo_suspected"]

class CoachingDecisionTrace(TracePoint):
    emitted_nudge: Optional[str] = None
    candidate_nudges: list[str] = Field(default_factory=list)
    suppressed_reasons: list[str] = Field(default_factory=list)
    metrics_index: Optional[int] = None
    trigger_features: dict = Field(default_factory=dict)

class SessionTrace(BaseModel):
    trace_version: int = 1
    session_id: str
    tutor_id: str = ""
    session_type: str = "general"
    started_at: datetime
    ended_at: datetime
    duration_seconds: float

    build: dict = Field(default_factory=dict)  # git_sha, app_version, models_version
    config_hash: str = ""
    capture_mode: Literal["prod", "eval", "browser-debug"] = "prod"
    env: dict = Field(default_factory=dict)

    events: list[SessionEvent] = Field(default_factory=list)
    visual_signals: list[VisualSignalPoint] = Field(default_factory=list)
    audio_signals: list[AudioSignalPoint] = Field(default_factory=list)
    overlap_segments: list[OverlapSegment] = Field(default_factory=list)

    metrics_history: list[MetricsSnapshot] = Field(default_factory=list)
    nudges: list[Nudge] = Field(default_factory=list)
    coaching_decisions: list[CoachingDecisionTrace] = Field(default_factory=list)
    summary: SessionSummary
```

### Additional trace design constraints
- every time-series artifact should carry both **`t_ms`** and **`seq`** so replay ordering is deterministic even when wall-clock timestamps collide
- store a compact **signal layer** in addition to `metrics_history`; this is what makes replay useful for the metrics engine, not just coaching outputs
- for `webrtc_signal_relayed`, record only **signal type, payload size, counts, and timing** — never full SDP/ICE contents
- prefer **incremental trace writing** (append-only NDJSON or periodic checkpoints) over a single end-of-session dump
- default retention/trimming should be safe by default: keep all for shorter sessions, then downsample or cap long-session snapshots/signals automatically

### Privacy rule
Follow the same spirit as AgentForge's Langfuse integration:
- **do store** session metadata, metrics snapshots, nudges, reconnect/degradation events, summary
- **do not store** raw video frames, raw PCM audio, SDP contents, or user-entered freeform text beyond already-saved tutor metadata

### Config
Add config like:
- `LSA_TRACE_DIR=data/traces`
- `LSA_ENABLE_SESSION_TRACING=false`
- `LSA_TRACE_WRITE_MODE=ndjson`
- `LSA_TRACE_MAX_METRICS_SNAPSHOTS=1800`
- `LSA_TRACE_MAX_SIGNAL_POINTS_PER_ROLE=7200`
- `LSA_TRACE_DOWNSAMPLE_LONG_SESSIONS=true`

Recommended default behavior:
- keep full-resolution traces for shorter sessions
- automatically downsample/cap long sessions instead of defaulting to unbounded growth

---

## 2. Build a Python eval harness modeled after AgentForge's golden sets

AgentForge's biggest win is not just “lots of tests”; it is **structured cases + shared assertions + multiple tiers**.

We should do the same in Python.

### Proposed layout

```text
backend/tests/evals/
  eval_case_schema.py
  eval_assert.py
  test_golden_fast.py
  test_replay.py
  fixtures/
    golden_sets.json
    traces/
      practice-overtalk-01.json
      lecture-high-tutor-share-ok-01.json
      screen-engaged-no-eye-nudge-01.json
      interruption-backchannel-01.json
      reconnect-grace-01.json
    recorded/
      localhost-two-party-001.json
      localhost-reconnect-001.json
    summaries/
      practice-low-energy-01.json
      lecture-healthy-01.json
```

### Why `backend/tests/evals/`
- keeps the eval harness distinct from classic unit tests
- makes it easy to run a subset in CI or nightly
- mirrors the organizational clarity of `AgentForge/apps/api/test/ai/`

### Assertion semantics and test selection
Borrow the AgentForge idea of shared assertion helpers, but make the assertions tolerance-aware for numeric/time-series systems.

Examples:
- `assert_metric_between("tutor_talk_ratio", 0.80, 0.90)`
- `assert_nudge_emitted("tutor_overtalk", within_s=30)`
- `assert_no_more_than("nudges", 1, window_s=300)`
- `assert_summary_field("engagement_score", approx=72, tolerance=3)`

Use pytest markers so tiers stay operable in CI:
- `@pytest.mark.eval_fast`
- `@pytest.mark.eval_replay`
- `@pytest.mark.browser_smoke`
- `@pytest.mark.soak_manual`

---

## 3. Use production Pydantic models to validate fixtures

This is one of the best AgentForge ideas.

In AgentForge, eval fixtures are coupled to production schemas so drift is caught structurally. We should do the Python equivalent by parsing fixtures through:
- `MetricsSnapshot`
- `SessionSummary`
- `Nudge`
- `SessionTrace` (new)

That means:
- a fixture with the wrong shape fails immediately
- renamed fields cannot silently rot the eval corpus
- the eval suite stays trustworthy as the product evolves

### Example case definition

```json
{
  "id": "practice-overtalk-should-nudge",
  "stage": "golden",
  "category": "coaching",
  "subcategory": "talk-balance",
  "fixture": "traces/practice-overtalk-01.json",
  "expectation": "expectations/practice-overtalk-01.json"
}
```

Keep **recorded input traces** separate from **expected assertions**.
That avoids accidentally promoting a buggy output into the replay fixture itself.

---

## 4. Define eval tiers that match this repo's actual risks

AgentForge has fast / replay / live / nightly. For this repo, I would adapt that to:

### Tier A — Fast deterministic evals (run every commit)
Purpose: validate metrics/coaching/summary behavior from saved traces.

Run against:
- saved compact signal traces (`visual_signals`, `audio_signals`, `overlap_segments`)
- saved `MetricsSnapshot` sequences
- saved `SessionSummary` fixtures
- saved reconnect event sequences

Example categories:
- interruption classification
- speaking-time ratio accuracy
- eye-contact / attention-state bin accuracy
- echo/backchannel suppression
- attention-state coaching suppression (`SCREEN_ENGAGED`, `DOWN_ENGAGED`)
- session-type-sensitive talk balance expectations
- summary/recommendation outputs
- short-session persistence

This tier is closest to AgentForge's **fast golden sets**.

### Tier B — Replay traces (run in CI, still deterministic)
Purpose: replay **real recorded session traces** captured from successful browser/manual runs.

This tier should catch:
- threshold drift
- unintended coaching behavior changes
- summary/recommendation changes against realistic metric histories
- reconnect/event sequencing regressions

This is the closest analogue to AgentForge's **replay tier**.

### Tier C — Browser smoke/live integration (already present, keep growing slowly)
Purpose: validate the product surface, not just backend logic.

Current coverage is already good:
- join
- role perspective
- media connect
- reconnect
- end session
- analytics persistence
- analytics redesign

I would keep this as the “live product” tier, not convert it into a giant everything-suite.

### Tier D — Manual/soak/network tier (documented, not default CI)
Purpose: real two-device, TURN-aware, longer-duration confidence.

Examples:
- two laptops on different networks
- one refresh + one reconnect
- 10–20 minute call soak
- mute/camera toggles mid-call
- end session from both roles

This is not a classic code eval tier, but it is essential for WebRTC confidence.

---

## 5. What traces should be recorded?

I would record **three levels** of trace artifacts.

### A. Session traces
Produced automatically on finalized sessions when tracing is enabled.

Use for:
- replay evals
- manual debugging
- regression triage

### B. Eval traces
Produced by the eval harness itself.

Use for:
- comparing expected vs actual outputs
- CI artifacts on failure
- spotting threshold drift over time

Example output file:
- `backend/test-artifacts/evals/<case-id>.json`

Include:
- case id
- fixture id
- expected nudge/recommendation assertions
- actual outputs
- pass/fail reasons

### C. Browser debug traces
On Playwright failure, export tutor/student debug-panel state and recent events into JSON alongside screenshots/videos.

This is especially useful for flaky reconnect/media issues.

---

## 6. First eval packs I would add here

These should come before anything fancy.

### Pack 1 — Accuracy pack (explicitly tied to rubric targets)
Focus:
- eye-contact / attention-state classification over labeled bins
- speaking-time ratio error tolerance
- interruption false-positive resistance on backchannels / echo-like traces

Assertions should be phrased in rubric-friendly terms, e.g.:
- eye-contact / attention-state bucket accuracy ≥ target over a labeled mini-corpus
- speaking-time ratio error within ±5%
- no interruption coaching on cooperative backchannels or echo-suspected overlap fixtures

Why first:
- this is the strongest direct bridge from the implementation to the rubric's “validated against ground truth” language
- it keeps replay/eval work from becoming purely UX/coaching regression coverage

### Pack 2 — Coaching golden set
Focus:
- `tutor_overtalk`
- `student_silence`
- `low_eye_contact`
- `interruption_spike`
- suppression cases for `SCREEN_ENGAGED`, `DOWN_ENGAGED`, echo/backchannel

Why second:
- this is the most product-sensitive logic after accuracy itself
- false positives here are directly user-visible and trust-damaging

### Pack 3 — Summary/recommendation golden set
Fixture input:
- `SessionSummary`

Assertions:
- expected recommendations present/absent
- session-type-sensitive outputs
- no contradictory recommendations
- no regressions on known edge cases

Why third:
- easy ROI
- fully deterministic
- directly user-facing in analytics

### Pack 4 — Reconnect/session lifecycle replay set
Fixture input:
- event sequence + signals + metrics snapshots

Assertions:
- no premature finalization during grace
- reconnect resumes correct state
- end-session saves summary even for short traces

Why fourth:
- this is where browser and backend semantics can diverge subtly

### Pack 5 — Analytics UI helper unit tests
Not AgentForge-style golden sets, but still worth adding.

Use a lightweight frontend unit harness later for:
- `frontend/src/lib/analytics.ts`
- formatting / health labels / comparisons / trend derivation

---

## 7. Tracing recommendation: local JSON now, optional cloud later

## My recommendation now
Implement **local structured traces first**.

Why:
- current app is not LLM-centric
- metrics/coaching/session replay is the urgent need
- local traces are simpler, cheaper, and privacy-safer

## Optional later
If the product later adds:
- AI-generated coaching summaries
- AI-generated tutor recommendations
- AI-generated practice plans

then copy AgentForge's **optional no-op observability wrapper** idea and add a cloud tracing layer (Langfuse or equivalent) only for those AI paths.

If that happens, trace only:
- model name
- prompt/response lengths
- latency
- cost
- selected summary type
- evaluation case id

Do **not** send raw student media, transcript-like private content, or dense session history without an explicit privacy decision.

---

## 8. Concrete rollout plan for this repo

## Phase 1 — Trace schema + incremental capture
Files to add:
- `backend/app/observability/trace_models.py`
- `backend/app/observability/trace_store.py`
- wiring in `backend/app/ws.py`
- small hooks in coaching/metrics layers for decision traces and signal capture

Goal:
- finalized sessions can optionally emit privacy-safe `SessionTrace` artifacts
- traces include signal-level inputs, ordered timeline metadata, provenance, and compact WebRTC signaling metadata
- trace writing is incremental rather than all-at-once

## Phase 2 — Fast eval harness
Files to add:
- `backend/tests/evals/eval_case_schema.py`
- `backend/tests/evals/eval_assert.py`
- `backend/tests/evals/test_golden_fast.py`
- `backend/tests/evals/fixtures/golden_sets.json`
- `backend/tests/evals/fixtures/expectations/*.json`
- first accuracy + coaching + recommendation fixtures

Goal:
- deterministic offline evals running in CI
- pytest markers cleanly separate fast/replay/browser/soak tiers

## Phase 3 — Replay tier
Files to add:
- `backend/tests/evals/test_replay.py`
- `backend/tests/evals/fixtures/recorded/*.json`
- helper script to promote a saved trace into replay fixtures

Goal:
- realistic regression coverage with no browser and no external services
- replay can re-evaluate metrics/coaching from compact signal traces, not just compare already-aggregated outputs

## Phase 4 — Browser trace export + soak
Files to add:
- Playwright helpers to export debug panel state on failure
- one longer soak-ish scenario (probably nightly/manual-triggered)

Goal:
- better triage for session UX regressions
- a path toward real-device / TURN-aware manual validation without bloating default CI

## Immediate follow-up backlog after the first replay slice

These are the next concrete items to preserve after the current context is cleared:

1. **Add a fixture-promotion helper**
   - purpose: turn real saved session traces into replay fixtures quickly
   - likely output: one recorded trace under `backend/tests/evals/fixtures/recorded/` plus a separate expectation file under `backend/tests/evals/fixtures/expectations/`
   - goal: make replay-corpus growth cheap and consistent

2. **Add browser debug trace export on Playwright failure**
   - export tutor/student debug-panel state and recent events into JSON artifacts
   - keep this alongside screenshots/videos for faster triage of browser/WebRTC failures

3. **Expand replay cases**
   - short-session persistence
   - reconnect with no peer recovery
   - face-missing / degradation transitions over time

These are the recommended next implementation steps after the first `eval_replay` slice now in the repo.

---

## 9. My recommendation in one sentence

Apply **AgentForge's multi-tier eval architecture and schema-validated fixtures**, but adapt the replay unit from **recorded LLM sessions** to **recorded session/coaching/metrics traces**, and use **local privacy-safe JSON traces** before introducing any cloud trace product.

---

## Best next implementation slice

If we do this next, I would start with:
1. `SessionTrace` local capture **including compact signal traces**
2. `backend/tests/evals/` fast golden set harness with shared tolerance-aware assertions
3. first 10–15 cases split between **accuracy targets** and **coaching precision / recommendation quality**

That gives the highest confidence per unit of work and maps cleanly onto the strongest parts of the AgentForge design while covering the rubric's metric-accuracy story more directly.
