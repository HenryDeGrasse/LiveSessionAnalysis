# LiveKit Cloud Setup — Manual Operator Steps

This document records every manual action required to connect the LSA backend and
frontend to a LiveKit Cloud project.  These steps cannot be automated by the
codebase and must be performed by the operator once before (or during) first
production deployment.

---

## 1. Create a LiveKit Cloud project

1. Go to <https://cloud.livekit.io> and sign in (create an account if needed).
2. Click **New Project** and give it a name (e.g. `lsa-prod`).
3. Select the region closest to your Fly.io backend deployment.

---

## 2. Copy project credentials

On the project dashboard, under **Settings → Keys**, copy:

| Value | Where used |
|---|---|
| **WSS URL** (`wss://…livekit.cloud`) | `LSA_LIVEKIT_URL` backend secret; `NEXT_PUBLIC_LIVEKIT_URL` frontend build arg |
| **API Key** | `LSA_LIVEKIT_API_KEY` backend secret |
| **API Secret** | `LSA_LIVEKIT_API_SECRET` backend secret |

---

## 3. Register the webhook endpoint

1. In the LiveKit Cloud dashboard, navigate to **Settings → Webhooks**.
2. Click **Add Endpoint**.
3. Set the **URL** to your backend's webhook path:

   ```
   https://lsa-backend.fly.dev/api/livekit/webhooks
   ```

   Replace `lsa-backend` with your actual Fly.io app name.

4. Leave the signing key as-is (LiveKit Cloud signs with your project's API
   secret, which is the same HMAC-SHA256 scheme used by self-hosted LiveKit and
   already verified by `backend/app/livekit.py`).

5. Enable at minimum these event types (or select **All Events**):
   - `room_started`
   - `room_finished`
   - `participant_joined`
   - `participant_left`
   - `track_published`
   - `track_unpublished`

---

## 4. Set Fly.io backend secrets

Run these `fly secrets set` commands for your **backend** app:

```bash
fly secrets set \
  LSA_LIVEKIT_URL="wss://<your-project>.livekit.cloud" \
  LSA_LIVEKIT_API_KEY="<api-key>" \
  LSA_LIVEKIT_API_SECRET="<api-secret>" \
  --app lsa-backend
```

---

## 5. Set the CORS origin for the frontend URL

After the frontend is deployed, add its URL to the backend's allowed origins:

```bash
fly secrets set \
  LSA_CORS_ORIGINS="http://localhost:3000,https://lsa-frontend.fly.dev" \
  --app lsa-backend
```

`LSA_CORS_ORIGINS` accepts either a comma-separated list or a JSON array.

---

## 6. Set the LiveKit URL for the frontend build

The frontend embeds the LiveKit WSS URL at build time via a `NEXT_PUBLIC_*` env
var.  Set it as a **build arg** in the Fly.io frontend config (already wired in
`frontend/Dockerfile` and `frontend/fly.toml`):

```bash
# Option A — set via fly.toml [build.args] (committed, non-secret)
# Edit frontend/fly.toml:
#   [build]
#     [build.args]
#       NEXT_PUBLIC_LIVEKIT_URL = "wss://<your-project>.livekit.cloud"

# Option B — inject at deploy time
fly deploy --build-arg NEXT_PUBLIC_LIVEKIT_URL="wss://<your-project>.livekit.cloud" \
  --app lsa-frontend
```

---

## 7. Verify the integration

1. Deploy both services (`fly deploy --app lsa-backend` and
   `fly deploy --app lsa-frontend`).
2. In the LiveKit Cloud dashboard, open **Rooms** and start a test session.
3. Check that webhook events appear in the backend logs:

   ```bash
   fly logs --app lsa-backend | grep livekit_webhook
   ```

4. Confirm participant join/leave events are processed (look for `"status":
   "processed"` in the logs).

---

## Notes

- The webhook verification logic in `backend/app/livekit.py` uses HMAC-SHA256
  (identical for LiveKit Cloud and self-hosted), so no code changes are needed
  when switching between the two.
- LiveKit Cloud's media key rotation is transparent to this application; only
  the API key/secret used for room tokens and webhook verification matter.
- If you later migrate to self-hosted LiveKit, simply update `LSA_LIVEKIT_URL`
  and keep the same API key/secret pattern.
