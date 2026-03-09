Below is a paste-ready, “polished design doc” version of a LiveKit-centered refactor that you can actually implement without turning it into a multi-month platform rewrite. It’s optimized to score highly on the evaluation rubric (latency, accuracy validation, coaching value, reliability, docs), while still being bolder than the safe approaches. 

---

# LiveSessionAnalysis v2

## LiveKit-Centered Realtime Tutoring + Engagement Intelligence

*Date: 2026-03-09*

### Executive summary

Use LiveKit as the **media plane** (rooms, SFU/TURN, reconnects) and move analytics to a **server-side worker** that joins each room as a hidden participant, subscribes to the tutor/student tracks, computes engagement metrics, and sends tutor-only coaching events over LiveKit **data packets**. This produces a real tutoring session UX, with “analytics layered on top,” while maintaining strict privacy constraints (no raw media storage) and meeting the assignment’s performance/accuracy targets.  ([LiveKit Docs][1])

---

## 1) Requirements and success targets

These are the “non-negotiables” from the assignment rubric:

* **Latency:** <500ms end-to-end for live feedback; “excellent” is consistently <300ms. 
* **Update rate:** 1–2 Hz metrics updates. 
* **Accuracy targets:** eye contact ≥85%, speaking time ≥95%, low-false-positive interruptions, validated against ground truth. 
* **Coaching UX:** subtle, contextually-timed, configurable frequency; tutor-only nudges. 
* **Post-session analytics:** summary, flagged moments, trends, recommendations. 
* **Privacy:** consent + store derived metrics/summaries, not raw media. 

---

## 2) Core design principles

1. **Don’t own media transport.** LiveKit handles TURN/SFU/reconnect complexity.
2. **Canonical inputs are LiveKit tracks.** No dual-upload capture logic for analytics in the browser (that’s a common “safe” approach; you can do better).
3. **Separate “call surface” from “coaching surface.”** Call UI can evolve independently from a tutor-only coaching stream (future desktop overlay becomes straightforward).
4. **Hot path vs cold path.** Live coaching is the hot path; summaries/trends are cold path and must never slow the session.
5. **Precision > recall for live nudges.** Most signals become post-session “flagged moments”; only a few high-confidence nudges appear live. 

---

## 3) System overview

### Three-plane architecture

```text
(1) Media plane (LiveKit)
Tutor <——— SFU/TURN ———> Student
        \                /
         \              /
          \            /
           \          /
        Analytics Worker (hidden participant)
           (subscribes to tracks)

(2) Intelligence plane (Python worker)
Tracks → signals → metrics → coaching decisions → tutor-only events

(3) Product plane (FastAPI + Next.js)
Session lifecycle, token minting, consent, analytics storage, dashboard, trends
```

### Why this stands out

Most submissions will stop at “two browser streams → my own WS → backend.” LiveKit + server-side track subscription is closer to how production systems are actually built, without sacrificing the rubric requirements. 

---

## 4) LiveKit integration model

### Rooms & roles

Each session maps 1:1 to a LiveKit room:

* `room = session:{session_id}`
* Participants:

  * Tutor: identity `tutor:{tutor_id}`
  * Student: identity `student:{session_id}:{random}`
  * Analytics worker: identity `worker:{session_id}` (hidden)

### Token grants (role-based)

LiveKit access tokens encode identity, room, and permissions. ([LiveKit Docs][1])

Use these grants in the token issuance endpoint:

* **Tutor token**: join, publish A/V, publish data, subscribe
* **Student token**: join, publish A/V, publish data (optional), subscribe
* **Worker token**: join, **subscribe**, **publish data**, hidden=true, agent=true (optional)

Python token model supports these grants (including `can_publish_data`, `can_subscribe`, and `hidden`). ([LiveKit Docs][2])

### Webhooks for lifecycle truth (optional but polished)

LiveKit supports server-side webhooks/events for room/participant/track changes. ([LiveKit Docs][3])
Use this to mark:

* tutor joined
* student joined
* tracks published/unpublished
* room ended

This becomes your durable session lifecycle record (great for reliability/debug).

---

## 5) Live coaching transport: LiveKit data packets (tutor-only)

Do **not** create a separate “event gateway” unless you truly need it.

Use LiveKit data packets:

* publish reliable/losy packets
* optionally target only specific participant identities (`destinationIdentities`) ([LiveKit Docs][4])

### Topics (versioned contracts)

* `lsa.metrics.v1` (lossy; 1–2 Hz)
* `lsa.nudge.v1` (reliable; rare)
* `lsa.debug.v1` (reliable; only when debug enabled)

This is clean, low-latency, and keeps everything “in-room.”

---

## 6) Intelligence plane: analytics worker design (Python)

### Worker entrypoint

* The worker connects to the room using LiveKit Python real-time SDK (`livekit-rtc`), subscribes to remote tracks, and processes frames/audio. ([GitHub][5])
* Track subscription is a core LiveKit concept (auto-subscribe and selective subscription are supported). ([LiveKit Docs][6])

### Track subscription strategy

* Subscribe only to:

  * tutor audio + tutor camera video
  * student audio + student camera video
* Ignore screenshare tracks unless you explicitly support them.

### Video pipeline (sampled, low layer)

Goal: meet <500ms latency and keep CPU “reasonable” on typical hardware. 

* Use low FPS sampling: start 3 FPS, degrade to 2/1 FPS as needed
* Downscale to ~320×240 for FaceMesh/gaze
* Prefer “fresh frames”:

  * if processing backlog exists, drop stale frames

### Attention-state model (categorical)

Replace “eye contact %” as the only UI signal with a tutoring-aware state model:

* `FACE_MISSING`
* `LOW_CONFIDENCE`
* `CAMERA_FACING`
* `SCREEN_ENGAGED`
* `DOWN_ENGAGED`
* `OFF_TASK_AWAY`

Keep `camera_facing_pct` as a narrow proxy, but drive coaching from the categorical state + persistence (time-in-state). This directly addresses the “multi-monitor / looking at content vs disengagement” issue that many teams will ignore. 

### Audio pipeline (per participant; no diarization)

LiveKit gives separate participant tracks, so you get speaker identity “for free.”

* VAD per participant stream
* Energy/noise-floor gating (to reduce false positives)
* Segment smoothing (hangover)
* Overlap classification:

  * `backchannel` vs `hard_interruption` vs `echo_suspected`

This supports “interruptions with low false positives.” 

---

## 7) Metrics engine and hot-path timing

Emit 1–2 Hz `MetricsSnapshot` packets to tutor. 

### MetricsSnapshot (high-level)

Per participant:

* `attention_state`, `attention_confidence`
* `camera_facing_score` (0–1)
* `is_speaking` (bool)
* `talk_time_pct_windowed`
* `energy_score` (audio-primary)
* `time_since_spoke_s`

Session-level:

* `talk_balance` (tutor vs student)
* `mutual_silence_s`
* `response_latency_s` (student after tutor)
* `hard_interruptions_3m`, `backchannels_3m`, `cutoffs_3m`
* `degraded_mode` + reason
* `latency_ms_p50/p95` for processing stages (debug)

---

## 8) Coaching design: minimal, high-confidence nudges

To “stand out,” your nudges must feel professional: rare, explainable, and correct.

### Global guardrails (hard rules)

* No nudges in first 120s
* Max 1 nudge / 5 minutes
* Max 3 nudges / session
* Suppress if `LOW_CONFIDENCE` or `FACE_MISSING` dominates
* Suppress interruption nudges if echo suspected

This hits “non-intrusive” and “contextually appropriate timing” directly. 

### Session-type profiles (rubric-aligned)

Session type affects talk balance expectations (the assignment even provides example benchmarks). 

Profiles: `lecture`, `practice`, `socratic`, `general`
Each profile defines:

* expected talk ratio ranges
* silence thresholds
* interruption sensitivity

### Live nudges (only 3–4)

Examples (high precision):

1. **Check for understanding**
   Trigger: tutor talk ratio >0.85 (6m) AND student silence >4m
2. **Student likely off-task**
   Trigger: student `OFF_TASK_AWAY` >75s (persistent)
3. **Let them finish**
   Trigger: tutor hard interruptions/cutoffs exceed threshold in 3m window AND student talk share low
4. **Tech check**
   Trigger: mutual silence >30s AND face missing / audio muted / reconnect churn

Everything else becomes post-session flagged moments.

---

## 9) Post-session analytics (cold path)

Required outputs: summary, flagged moments, trends, recommendations. 

Store:

* session summary stats
* chart-ready time series (downsampled)
* flagged moments (timestamp + metric + description)
* recommendations (session-type-aware)

To keep it simple and polished:

* store summaries + small timeseries in DB (SQLite is fine locally)
* store full traces in JSON (object storage later)

---

## 10) Privacy posture (explicit)

The assignment expects privacy considerations documented. 

* **Do not store** raw video frames, raw PCM audio, SDP contents
* **Do store** derived metrics, nudges, flagged moments, summaries, and privacy-safe traces
* **Consent:** both tutor and student must consent before joining analytics-enabled sessions
* **Tutor-only coaching:** coaching events are sent only to tutor identity via `destinationIdentities` on data packets ([LiveKit Docs][4])

---

## 11) Traces + evals (how you become “head and shoulders above”)

Most teams will not have a real evaluation harness. You should.

### Local session trace (privacy-safe)

Record:

* lifecycle events (join/leave/reconnect, degraded-mode changes)
* signal traces (speech_active, attention_state, etc.)
* emitted metrics snapshots
* coaching decisions (candidate nudges + suppressed reasons)
* final summary

### Multi-tier eval suite

* Tier A (fast): deterministic golden sets (coaching + metrics math)
* Tier B (replay): recorded traces from real sessions
* Tier C (browser smoke): two-role join + remote media + tutor-only events
* Tier D (manual soak): two devices, network variability

This directly targets “validated against ground truth” and “reliability” scoring. 

---

## 12) Implementation milestones (ordered for a fast working demo)

No massive rewrite required; just the right sequence.

### Milestone 0 — LiveKit local dev + token issuance

* Run LiveKit locally (`livekit-server --dev` uses devkey/secret; binds to 127.0.0.1:7880 by default). ([LiveKit Docs][7])
* Add backend endpoint: `POST /api/sessions` → returns `session_id`
* Add backend endpoint: `POST /api/sessions/{id}/token` → returns LiveKit token with grants

**Done when**

* two browser tabs can join the same room with role-specific identity.

### Milestone 1 — Real call UI (remote audio/video)

* Next.js integrates LiveKit client SDK
* Session page renders local + remote media, waiting/connected states

**Done when**

* tutor and student can see/hear each other reliably (same LAN).

### Milestone 2 — Analytics worker joins room and reads tracks

* Worker connects via LiveKit Python SDK and subscribes to tracks (track_subscribed handler). ([GitHub][5])

**Done when**

* worker logs show it receives frames/audio chunks for both participants.

### Milestone 3 — Metrics + nudges over LiveKit data packets

* Worker computes minimal snapshot (talk ratio + speaking flags + face present)
* Worker publishes `lsa.metrics.v1` to tutor identity (destinationIdentities) ([LiveKit Docs][4])

**Done when**

* tutor overlay updates at 1–2 Hz 
* tutor receives events; student does not.

### Milestone 4 — Full metric set + minimal nudges + post-session analytics

* Implement attention-state, interruptions classification, energy, drift
* Add nudge guardrails and session-type profiles
* Persist summary + flagged moments; dashboard view

**Done when**

* you can run a short demo session and see post-session summary + timeline + recommendations. 

### Milestone 5 — Calibration, traces, evals, and “presentation polish”

* Run labeled validation clips and publish results (eye contact ≥85%, speaking ≥95%) 
* Add replay eval harness + CI target
* Add debug panel showing latency p50/p95, degraded mode, rule explanations

**Done when**

* you can show proof (numbers + tests), not just a demo.

---

## “Stand out” checklist (what reviewers will remember)

1. Real call UX (not simulated) + tutor-only coaching stream
2. Strictly minimal nudges + explainability (“why this fired / why others suppressed”)
3. Measured latency (p50/p95) displayed live + logged
4. Ground-truth accuracy report with methodology and results 
5. Replay eval harness catching regressions
6. Clean docs: decision log, limitations, privacy, calibration 

---

## Notes on local setup (pragmatic)

For local dev, LiveKit’s docs explicitly support running a dev instance via `livekit-server --dev`, with a known API key/secret pair (devkey/secret) and a bind flag for LAN access. ([LiveKit Docs][7])
This is good for:

* one-command demo
* two-device soak tests (phone + laptop)

---

If you want, paste your current repo structure and current “session create/join” endpoints; I can map them to an exact LiveKit token/join flow (including identity/role naming conventions and data-packet schemas) so the refactor stays clean and doesn’t sprawl.

[1]: https://docs.livekit.io/frontends/reference/tokens-grants/?utm_source=chatgpt.com "Tokens & grants | LiveKit Documentation"
[2]: https://docs.livekit.io/reference/python/livekit/api/access_token.html?utm_source=chatgpt.com "livekit.api.access_token API documentation"
[3]: https://docs.livekit.io/intro/basics/rooms-participants-tracks/webhooks-events/?utm_source=chatgpt.com "Webhooks & events | LiveKit Documentation"
[4]: https://docs.livekit.io/transport/data/packets/?utm_source=chatgpt.com "Data packets | LiveKit Documentation"
[5]: https://github.com/livekit/python-sdks "GitHub - livekit/python-sdks: LiveKit real-time and server SDKs for Python · GitHub"
[6]: https://docs.livekit.io/transport/media/subscribe/?utm_source=chatgpt.com "Subscribing to tracks | LiveKit Documentation"
[7]: https://docs.livekit.io/transport/self-hosting/local/ "Running LiveKit locally | LiveKit Documentation"

