# Milestone 5 — Calibration, Traces, Evals, and Presentation Polish

## Goal

Move from "working demo" to "provable quality." After this milestone, every
claim about accuracy, latency, or coaching correctness is backed by a
reproducible test, a measured number, or a document explaining the method.

v2.md's **done-when** criterion:

> You can show **proof** (numbers + tests), not just a demo.

---

## Current State

### Already built
- Replay eval harness: `replay.py`, `worker_replay.py` — feeds recorded traces
  through the metrics engine and coaching system, asserts outputs.
- 11 eval tests (accuracy pack × 10 signal-level golden fixtures, 1 practice-
  overtalk golden, 2 recorded-session replays, 1 worker replay).
- Session traces: full lifecycle + signal-level + coaching decision recording.
- Debug panel (session page `?debug=1`): connection state, raw snapshot JSON,
  per-field metrics, recent events, nudge history.
- Calibration doc, decision log, limitations doc, privacy analysis.

### What's missing (gap-by-gap)

| # | Gap | Impact | Effort |
|---|-----|--------|--------|
| 1 | No `make eval` / CI target | Evals only run if you know the pytest flag | S |
| 2 | Latency is single `server_processing_ms` — no p50/p95 | Can't prove "<300ms consistently" | M |
| 3 | Debug panel has no coaching explainability | Tutor can't see why a nudge fired or why others were suppressed | M |
| 4 | No accuracy report output | "≥85% eye contact, ≥95% speaking" exists in calibration doc as a how-to but no published numbers | M |
| 5 | Docs not updated for LiveKit + coaching overhaul | Decision log, limitations, calibration still reference old WebRTC and old coaching rules | M |
| 6 | MetricsSnapshot schema has minor P2 gaps | `talk_time_pct_windowed`, `time_since_spoke_s` per participant; degradation reason string | S |
| 7 | No `lsa.debug.v1` data packet topic for live debug | v2.md §5 mentions it; not implemented | S |

---

## Plan (ordered by demo/review impact)

### Phase 5A — Make target + CI plumbing (30 min)

Add `make eval` that runs the full eval pack, `make test-all` that runs
backend + frontend unit + evals, and `make lint` for type checks.

**Files touched:** `Makefile`

**Done when:** `make eval` passes cleanly, `make test-all` runs all 311+
backend + 13 frontend unit tests in one command.

---

### Phase 5B — Latency p50/p95 on MetricsSnapshot + debug panel (1–2 hr)

**Backend:**
- Add a `deque[float]` of recent processing times (last 100) on `SessionRoom`.
- Compute p50/p95 with `statistics.quantiles()`.
- Add `latency_p50_ms` and `latency_p95_ms` fields to `MetricsSnapshot`.
- Add `degradation_reason` string field (`"normal"`, `"skip_expression"`,
  `"skip_gaze"`, `"skip_gaze_and_expression"`).

**Frontend:**
- Add `latency_p50_ms`, `latency_p95_ms`, `degradation_reason` to
  `MetricsSnapshot` TypeScript type.
- Show them in the debug panel's "Current metrics" section.
- Add a compact latency badge on the tutor overlay bar (p95, hidden if <100ms).

**Tests:** Unit test for percentile computation; existing e2e should stay green.

**Done when:** debug panel shows p50/p95 ms and degradation reason live.

---

### Phase 5C — Coaching explainability in debug panel (1–2 hr)

**Backend:**
- Add a new field to the metrics websocket/data-packet payload:
  `coaching_decision` with `{ candidate_nudges, suppressed_reasons,
  emitted_nudge, trigger_features }` — only when `?debug=1` or a flag is set.
  (Avoid sending verbose coaching traces in production by default.)
- Or: publish on `lsa.debug.v1` topic (lossy) when debug mode is active.

**Frontend:**
- Add a "Coaching decisions" section to the debug panel.
- Show: "Candidates considered: [list]", "Suppressed: [reason list]",
  "Fired: [nudge_type] because [trigger_features summary]".
- Color-code: green for fired, gray for suppressed, red for budget-exhausted.

**Tests:** Verify the debug payload round-trips in a unit test.

**Done when:** tutor in debug mode can see *why* a nudge fired and *why*
others were suppressed, live during the session.

---

### Phase 5D — MetricsSnapshot schema polish (1 hr)

Add the P2 fields identified in the audit:

- `ParticipantMetrics.talk_time_pct_windowed` — recent-window talk ratio per
  participant (already computed by `SpeakingTimeTracker.recent_tutor_ratio()`).
- `ParticipantMetrics.time_since_spoke_seconds` — per-participant silence
  duration (student version exists at session level; add tutor equivalent +
  expose per-participant).
- `SessionMetrics.degradation_reason` — human-readable string.

**Frontend:** update TypeScript types.

**Tests:** existing snapshot tests + one new assertion per field.

**Done when:** snapshot schema matches v2.md §7 fully.

---

### Phase 5E — Accuracy report generation (1–2 hr)

Create a script `scripts/accuracy_report.py` that:

1. Loads all accuracy-pack traces from `tests/evals/fixtures/traces/`.
2. Replays each through `MetricsEngine`.
3. Compares final attention state, speaking ratios, interruption counts against
   labeled expectations.
4. Outputs a markdown report with:
   - Per-metric accuracy (eye contact binary accuracy, speaking time absolute
     error, interruption F1).
   - Per-trace pass/fail table.
   - Aggregate: "Eye contact: 87% accuracy across N traces", "Speaking time:
     2.1% mean absolute error", etc.
5. Writes `docs/accuracy-report.md` (gitignored so it's regenerated, not stale).

**Also:** Add `make accuracy-report` target.

**Tests:** The script itself is tested implicitly by the accuracy pack; the
report is a formatted view of the same data.

**Done when:** `make accuracy-report` produces a clean markdown table with
numbers matching v2.md targets.

---

### Phase 5F — Update docs for LiveKit + coaching overhaul (1 hr)

Update these existing docs to reflect the current architecture:

**`docs/decision-log.md`** — add entries for:
- LiveKit migration (phases, rationale, outcome)
- Energy nudge removal from live coaching (false positive in lectures)
- Session-type coaching profiles
- Persistence-based off-task detection
- Data packets for metrics/nudge delivery

**`docs/limitations.md`** — update:
- Remove "WebRTC production hardening needed" (LiveKit handles this now)
- Add LiveKit-specific limitations (local dev server, no TURN config yet)
- Update coaching nudge section for new 4-rule system
- Note energy is now post-session only

**`docs/calibration.md`** — update:
- Add section on attention-state window tuning
- Add section on session-type profile threshold tuning
- Note energy weights are less relevant for live coaching now

**`docs/privacy-analysis.md`** — update:
- Note LiveKit data packets carry metrics to tutor only via
  `destinationIdentities` (student never receives)
- Note worker joins as hidden participant

**Done when:** all four docs are accurate for the current codebase.

---

## Ordering rationale

| Phase | Why this order |
|-------|---------------|
| 5A | 30 min, unlocks "run everything in one command" for all later phases |
| 5B | Latency is the #1 rubric criterion; proving "<300ms" requires p50/p95 |
| 5C | Coaching explainability is the #2 "stand out" item in v2.md |
| 5D | Small schema polish, unblocks accuracy report having full fields |
| 5E | Produces the proof artifact ("numbers, not just a demo") |
| 5F | Docs are the final polish layer; easier to write after code is stable |

---

## Definition of Done (Milestone 5)

- [ ] `make eval` runs full eval pack (11 tests) and passes
- [ ] `make test-all` runs all backend + frontend tests in one command
- [ ] Debug panel shows latency p50/p95 and degradation reason
- [ ] Debug panel shows coaching decision explainability (candidates,
      suppressed, fired, trigger features)
- [ ] MetricsSnapshot has `talk_time_pct_windowed`, `time_since_spoke_seconds`,
      `degradation_reason` per v2.md §7
- [ ] `make accuracy-report` generates `docs/accuracy-report.md` with per-metric
      numbers
- [ ] Decision log, limitations, calibration, privacy docs updated for current
      architecture
- [ ] All existing tests still pass (311+ backend, 13 frontend unit, 5 e2e)
