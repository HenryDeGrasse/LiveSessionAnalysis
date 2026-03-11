# Demo Recording Guide

This guide is for producing the **3–5 minute demo video / live walkthrough**
that the assignment checklist expects. Missing a demo is an avoidable scoring
risk, so the goal here is to make the recording fast, repeatable, and clean.

## Fastest Setup

### One-command helper

```bash
make demo-setup
```

What it does:
- reuses an existing local LiveKit / backend / frontend stack when available
- starts LiveKit via Docker if port `7880` is not already in use
- starts the backend and frontend dev servers in the background when needed
- waits for both apps to be healthy
- creates a **practice-mode** demo session via the API
- prints backup tutor + student URLs for the demo flow

Keep that terminal open while recording if the helper started your local dev
servers.

### Manual setup

If you want to run everything yourself instead of using the helper:

```bash
# Terminal 1
cd backend
LSA_ENABLE_LIVEKIT=true \
LSA_ENABLE_LIVEKIT_ANALYTICS_WORKER=true \
LSA_LIVEKIT_URL=ws://127.0.0.1:7880 \
LSA_LIVEKIT_API_KEY=devkey \
LSA_LIVEKIT_API_SECRET=secret \
uv run --python 3.11 --with-requirements requirements.txt \
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2
cd frontend
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 \
NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8000 \
NEXT_PUBLIC_LIVEKIT_URL=ws://127.0.0.1:7880 \
npm run dev -- --hostname 0.0.0.0 --port 3000

# Terminal 3 (if LiveKit is not already running)
docker compose up -d livekit
```

## Prerequisites

Before you hit record, make sure you have:
- a local **LiveKit** dev server running (`docker compose up -d livekit` or `make demo-setup`)
- backend available at `http://localhost:8000`
- frontend available at `http://localhost:3000`
- one tutor browser window and one student window (best: second browser or incognito)
- working webcam + microphone permissions in both windows
- a short tutoring prompt ready so you do not improvise on camera

Recommended session type for the recording: **practice**.

Why practice mode? It makes the live coaching behavior easier to demonstrate,
especially the `check_for_understanding` nudge when the tutor talks for too
long.

## Recording Setup

Any of these are fine:

### OBS Studio
Best choice if you want the cleanest capture and control.
- record the full screen or the browser window at 1080p
- capture system audio if you want reviewer-visible proof of peer media
- hide the OBS window before you begin the actual take

### QuickTime (macOS)
Good lightweight option for a fast local recording.
- File → New Screen Recording
- record the browser window or full screen
- select the mic if you want narration

### Browser-based recorder
Loom / CleanShot / similar tools are fine if they do not clutter the screen.
If you use one, keep floating controls tucked away from the session UI.

## Recommended 3–5 Minute Demo Script

This is the cleanest sequence to record.

| Time | What to show | Notes |
|------|---------------|-------|
| 0:00–0:30 | Open the home page and create a session | Show tutor name entry and **session type = practice** |
| 0:30–0:45 | Show the student join link | Copy it or briefly show where it appears |
| 0:45–1:15 | Open the student link in a second browser/incognito window | Show consent / camera-mic permission on both sides |
| 1:15–1:45 | Show both participants connected in the live call | Make sure remote video is visible and clearly working |
| 1:45–2:15 | Highlight the tutor overlay pills | Attention, talk balance, and turn flow should be visible |
| 2:15–2:45 | Turn on **Coach debug** | Show latency p50/p95, degradation reason, raw metrics, and coaching decision output |
| 2:45–3:45 | Demonstrate a coaching nudge firing | In practice mode, let the tutor speak continuously while the student stays mostly quiet |
| 3:45–4:15 | End the session | Show the end-of-session summary overlay |
| 4:15–4:45 | Open the analytics detail page | Highlight metrics, flagged moments, and recommendations |
| 4:45–5:00 | Open the analytics dashboard | Show session list, health labels, and trend view |

## Suggested Talk Track

You do not need to say all of this verbatim, but this keeps the walkthrough
focused:

1. **Home page / creation**
   - “I’m creating a new tutoring session from the landing page.”
   - “I’ll use practice mode so coaching is tuned for student participation.”

2. **Join flow**
   - “Here is the student link. I’ll open it in a second browser so both roles are visible.”
   - “Both sides go through consent before the live session starts.”

3. **Live session**
   - “Now the tutor and student can see each other in the live call.”
   - “The tutor gets private overlay pills for attention, talk balance, and turn flow.”

4. **Debug panel**
   - “Behind the Coach debug toggle, I can inspect latency percentiles, detailed metrics, and coaching explainability.”
   - “This panel shows why a nudge fired, what other candidates were considered, and which ones were suppressed.”

5. **Nudge demo**
   - “I’m going to let the tutor hold the floor in practice mode to trigger a coaching suggestion.”
   - “This is designed to be sparse and tutor-only, not distracting to the student.”

6. **Post-session analytics**
   - “After the session ends, the app produces a summary, flagged moments, recommendations, and dashboard-level trends.”

## Important Note for the Live Nudge Demo

Live coaching has a global warmup before nudges are allowed.

- The current backend uses a **120-second global warmup**.
- That means the cleanest nudge demo usually happens **after the first two minutes**.
- For the `check_for_understanding` nudge, keep the session in **practice** mode and let the tutor speak for an extended stretch while the student contributes very little.

If you want a smoother take:
- do a dry run first without recording
- keep the practice-mode session type
- have the student give only brief acknowledgements once the warmup passes

## Tips for a Clean Demo

- close Slack, email, and unrelated tabs before recording
- use **good lighting** and keep the face centered so attention-state output looks stable
- keep browser zoom at 100% so the layout matches the real UI
- use a second browser or incognito window for the student role so cookies / local state stay separate
- keep the `make demo-setup` terminal nearby but **off camera**; it prints backup tutor/student URLs if you need to recover quickly
- if you narrate, speak briefly and intentionally — reviewers care more about the product flow than a long explanation
- preload `/analytics` in another tab before recording if you want the final navigation to feel instant

## Where to Save the Recording

Do **not** commit a raw demo video into the repo.

Recommended local save location:

```text
~/Movies/LiveSessionAnalysis/live-demo-YYYY-MM-DD.mp4
```

Then export or rename the trimmed submission copy to something obvious like:

```text
~/Movies/LiveSessionAnalysis/submission-demo.mp4
```

If you need to reference it in submission materials, link to the hosted file or
attach it separately rather than checking a large binary into git.

## Final Pre-Flight Checklist

Before recording, verify:
- LiveKit, backend, and frontend are all running
- tutor and student cameras work
- the tutor session is set to **practice**
- the debug toggle is visible on the tutor side
- your screen recorder is capturing the right monitor/window
- you know where you will navigate after ending the session (`/analytics/{id}` then `/analytics`)

If you want the quickest path, run `make demo-setup`, keep the printed backup
URLs handy, and then record the **full UI flow** from the home page.
