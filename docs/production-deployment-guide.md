# Production Deployment Guide

This guide covers deploying LiveSessionAnalysis to the recommended production
stack: **Fly.io** (app hosting) + **LiveKit Cloud** (media) + **Postgres** (relational
data) + **Cloudflare R2** (trace/artifact object storage) + **Sentry** (observability).

---

## Table of Contents

1. [Prerequisites checklist](#1-prerequisites-checklist)
2. [Account creation steps](#2-account-creation-steps)
3. [Secrets generation commands](#3-secrets-generation-commands)
4. [External service configuration](#4-external-service-configuration)
5. [Local integration testing](#5-local-integration-testing)
6. [Deployment sequence](#6-deployment-sequence)
7. [DNS setup](#7-dns-setup)
8. [Smoke test checklist](#8-smoke-test-checklist)
9. [Rollback procedure](#9-rollback-procedure)
10. [Environment variable reference](#10-environment-variable-reference)
11. [Architecture notes](#11-architecture-notes)

---

## 1. Prerequisites checklist

Before you begin, confirm the following are in place:

- [ ] `flyctl` CLI installed (`curl -L https://fly.io/install.sh | sh`)
- [ ] `fly auth login` completed
- [ ] Docker installed and running (used by `fly deploy`)
- [ ] Git repo is clean (no untracked secrets committed)
- [ ] Access to the domain / DNS you will use for the frontend and backend
- [ ] Accounts created for all external services (see §2)

---

## 2. Account creation steps

### 2.1 Fly.io

1. Create an account at <https://fly.io>.
2. Install the CLI: `curl -L https://fly.io/install.sh | sh`
3. Authenticate: `fly auth login`
4. Create the two Fly apps (replace `lsa-backend` / `lsa-frontend` with your
   preferred app names — these determine the `.fly.dev` subdomain):

   ```bash
   fly apps create lsa-backend
   fly apps create lsa-frontend
   ```

5. Create a persistent data volume for the backend (1 GB is enough for
   temp/cache; real data lives in Postgres and R2):

   ```bash
   fly volumes create lsa_data --region ord --size 1 --app lsa-backend
   ```

   Choose the region closest to your users (`ord` = Chicago, `lax` = LA,
   `fra` = Frankfurt, etc.). Run `fly platform regions` for the full list.

### 2.2 Postgres (Neon — recommended for first deployment)

1. Create an account at <https://neon.tech> (or use Supabase, or a Fly Postgres
   managed cluster).
2. Create a new **project** and a **database** named `lsa`.
3. Copy the **connection string** from the Neon dashboard
   (`postgresql://user:password@ep-xxx.us-east-1.aws.neon.tech/lsa?sslmode=require`).
4. Store this as `LSA_DATABASE_URL` in §3.

   > **Fly Postgres alternative:** `fly postgres create --name lsa-db` creates a
   > managed Postgres cluster. Use `fly postgres connect -a lsa-db` to verify.
   > The internal connection string is `postgresql://user:password@lsa-db.flycast:5432/lsa`.

### 2.3 Cloudflare R2

1. Create a Cloudflare account at <https://dash.cloudflare.com>.
2. Navigate to **R2 Object Storage** and create a bucket named `lsa-traces`
   (or your preferred name).
3. Note the **Account ID** from the R2 overview page.
4. Create an **R2 API token** with **Object Read & Write** permissions:
   - Go to R2 → **Manage R2 API tokens** → **Create API Token**.
   - Copy the **Access Key ID** and **Secret Access Key**.
5. The endpoint URL for your account is:
   `https://<account-id>.r2.cloudflarestorage.com`

### 2.4 LiveKit Cloud

See `docs/livekit-cloud-setup.md` for the full step-by-step.  Summary:

1. Create a project at <https://cloud.livekit.io>.
2. From **Settings → Keys**, copy the **WSS URL**, **API Key**, and **API Secret**.
3. Register the backend webhook endpoint (§4.1 below).

### 2.5 Sentry

1. Create an account at <https://sentry.io>.
2. Create two projects:
   - **Backend**: platform = *Python / FastAPI*
   - **Frontend**: platform = *Next.js*
3. Copy the **DSN** for each project from *Settings → Projects → <project> →
   Client Keys (DSN)*.

### 2.6 Google OAuth (optional)

Required only if you want Google sign-in.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) →
   **APIs & Services → Credentials**.
2. Create an **OAuth 2.0 Client ID** of type **Web application**.
3. Add authorized redirect URIs:
   - `https://<your-frontend-domain>/api/auth/callback/google`
4. Copy the **Client ID** and **Client Secret**.

---

## 3. Secrets generation commands

Run these once locally.  Copy the output into §4 / §5 when setting secrets.

```bash
# Backend JWT signing key
openssl rand -base64 32

# NextAuth session encryption key
openssl rand -base64 32
```

These two values must be different.  Never reuse them across environments.

---

## 4. External service configuration

### 4.1 LiveKit Cloud webhook

In the LiveKit Cloud dashboard → **Settings → Webhooks → Add Endpoint**:

- **URL**: `https://lsa-backend.fly.dev/api/livekit/webhooks`
  (replace `lsa-backend` with your actual Fly app name)
- Enable at minimum: `room_started`, `room_finished`, `participant_joined`,
  `participant_left`, `track_published`, `track_unpublished`

### 4.2 Google OAuth redirect URI

In the Google Cloud Console OAuth client, add the production redirect URI:

```
https://<your-frontend-domain>/api/auth/callback/google
```

### 4.3 Postgres schema initialization and one-time local migration

This repo now includes two standalone helpers in `backend/scripts/`:

- `python scripts/init_db.py` — creates the `users` and `session_summaries`
  tables (idempotent `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`)
- `python scripts/migrate_local_to_postgres.py` — optionally imports existing
  local JSON session files from `data/sessions/` and users from `data/auth.db`

Initialize the schema first:

```bash
cd backend
LSA_DATABASE_URL="<your-production-dsn>" \
uv run --python 3.11 --with-requirements requirements.txt python scripts/init_db.py
```

If you have existing local/demo data to preserve, run the one-time migration:

```bash
cd backend
LSA_DATABASE_URL="<your-production-dsn>" \
LSA_STORAGE_BACKEND="postgres" \
uv run --python 3.11 --with-requirements requirements.txt \
  python scripts/migrate_local_to_postgres.py
```

Use `--dry-run` to preview what would be imported:

```bash
cd backend
LSA_DATABASE_URL="<your-production-dsn>" \
uv run --python 3.11 --with-requirements requirements.txt \
  python scripts/migrate_local_to_postgres.py --dry-run
```

For a Fly-deployed backend, run the same commands over SSH:

```bash
fly ssh console --app lsa-backend
# then run `uv run ... python scripts/init_db.py`
# and optionally `uv run ... python scripts/migrate_local_to_postgres.py`
```

---

## 5. Local integration testing

Before pushing to Fly.io you can validate the full production storage stack
(Postgres + S3-compatible object storage) locally using
`docker-compose.production.yml`.  This file spins up:

| Service | Image | Role |
|---|---|---|
| `postgres` | `postgres:16-alpine` | Relational store — stands in for Neon/Fly Postgres |
| `minio` | `minio/minio:latest` | S3-compatible object store — stands in for Cloudflare R2 |
| `minio-init` | `minio/mc:latest` | One-shot container that creates the `lsa-traces` bucket |
| `backend` | `./backend` | FastAPI app configured for `postgres` + `s3` backends |
| `frontend` | `./frontend` | Next.js app, built with local `NEXT_PUBLIC_*` args |
| `livekit` | `livekit/livekit-server:latest` | Local dev SFU for offline media testing |

### 5.1 Start the integration stack

```bash
# Build all images and start every service (includes local LiveKit dev server)
docker compose -f docker-compose.production.yml up --build
```

Once all services are healthy:

| Endpoint | URL |
|---|---|
| Frontend | <http://localhost:3000> |
| Backend health | <http://localhost:8000/health> |
| MinIO web console | <http://localhost:9001> (user: `minioadmin` / pass: `minioadmin`) |

### 5.2 Initialize the database schema

The Postgres database starts empty.  Run the schema initialisation script
against the local database:

```bash
cd backend && \
  LSA_DATABASE_URL="postgresql://lsa:lsa@localhost:5432/lsa" \
  uv run --python 3.11 --with-requirements requirements.txt \
  python scripts/init_db.py
```

Or exec into the running backend container:

```bash
docker compose -f docker-compose.production.yml \
  exec backend \
  uv run --python 3.11 --with-requirements requirements.txt \
  python scripts/init_db.py
```

### 5.3 Test with LiveKit Cloud instead of the local dev server

Set your LiveKit Cloud credentials before starting, then omit the `livekit`
service by starting only the non-LiveKit services:

```bash
export LSA_LIVEKIT_URL=wss://your-project.livekit.cloud
export LSA_LIVEKIT_API_KEY=your-livekit-api-key
export LSA_LIVEKIT_API_SECRET=your-livekit-api-secret
export NEXT_PUBLIC_LIVEKIT_URL=wss://your-project.livekit.cloud

docker compose -f docker-compose.production.yml \
  up --build postgres minio minio-init backend frontend
```

The backend and frontend will read the exported env vars and connect to
LiveKit Cloud directly.

### 5.4 Validate trace writes to MinIO

After completing a session, confirm the trace file landed in MinIO:

1. Open the [MinIO console](http://localhost:9001) and browse the
   `lsa-traces` bucket.
2. Or use a one-shot MinIO CLI container:

   ```bash
   docker compose -f docker-compose.production.yml \
     run --rm --entrypoint /bin/sh minio-init -c \
     "mc alias set local http://minio:9000 minioadmin minioadmin && mc ls local/lsa-traces"
   ```

### 5.5 Tear down

```bash
docker compose -f docker-compose.production.yml down -v
```

The `-v` flag removes the named volumes (`postgres-data`, `minio-data`,
`backend-data`), giving you a clean slate for the next test run.

---

## 6. Deployment sequence

Run these steps in order.  Steps marked **[MANUAL]** require action outside the
codebase.

### Step 1 — Set backend secrets

```bash
fly secrets set \
  LSA_JWT_SECRET="$(openssl rand -base64 32)" \
  LSA_DATABASE_URL="postgresql://user:password@host:5432/lsa?sslmode=require" \
  LSA_STORAGE_BACKEND="postgres" \
  LSA_LIVEKIT_URL="wss://your-project.livekit.cloud" \
  LSA_LIVEKIT_API_KEY="your-livekit-api-key" \
  LSA_LIVEKIT_API_SECRET="your-livekit-api-secret" \
  LSA_SENTRY_DSN="https://key@o0.ingest.sentry.io/project-id" \
  LSA_SENTRY_ENVIRONMENT="production" \
  LSA_TRACE_STORAGE_BACKEND="s3" \
  LSA_S3_ENDPOINT_URL="https://account-id.r2.cloudflarestorage.com" \
  LSA_S3_BUCKET_NAME="lsa-traces" \
  LSA_S3_ACCESS_KEY_ID="your-r2-access-key-id" \
  LSA_S3_SECRET_ACCESS_KEY="your-r2-secret-access-key" \
  LSA_GOOGLE_CLIENT_ID="your-google-client-id" \
  LSA_CORS_ORIGINS="https://lsa-frontend.fly.dev" \
  --app lsa-backend
```

> **Note:** Running `fly secrets set` with `$(openssl rand -base64 32)` inline
> generates the secret in the shell.  If you need to reuse the same value
> (e.g., to set `LSA_JWT_SECRET` and record it), generate it first:
> ```bash
> JWT_SECRET=$(openssl rand -base64 32)
> echo "Store this: $JWT_SECRET"
> fly secrets set LSA_JWT_SECRET="$JWT_SECRET" --app lsa-backend
> ```

### Step 2 — Deploy the backend

```bash
cd backend
fly deploy --app lsa-backend
```

Verify the backend is healthy:

```bash
fly status --app lsa-backend
curl https://lsa-backend.fly.dev/health
```

### Step 3 — Initialize the database schema

Run the one-off schema bootstrap from §4.3. The short version is:

```bash
fly ssh console --app lsa-backend
# then inside the container, from /app:
uv run --python 3.11 --with-requirements requirements.txt python - <<'PY'
import asyncio
from app.db import get_pool, close_pool
from app.db_schema import SCHEMA_SQL

async def main():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await close_pool()

asyncio.run(main())
PY
```

### Step 4 — Set frontend secrets

```bash
fly secrets set \
  AUTH_SECRET="$(openssl rand -base64 32)" \
  GOOGLE_CLIENT_ID="your-google-client-id" \
  GOOGLE_CLIENT_SECRET="your-google-client-secret" \
  NEXT_PUBLIC_GOOGLE_CLIENT_ID="your-google-client-id" \
  NEXTAUTH_URL="https://lsa-frontend.fly.dev" \
  NEXTAUTH_BACKEND_URL="http://lsa-backend.flycast:8000" \
  NEXT_PUBLIC_API_URL="https://lsa-backend.fly.dev" \
  NEXT_PUBLIC_WS_URL="wss://lsa-backend.fly.dev" \
  NEXT_PUBLIC_SENTRY_DSN="https://key@o0.ingest.sentry.io/frontend-project-id" \
  NEXT_PUBLIC_SENTRY_ENVIRONMENT="production" \
  SENTRY_DSN="https://key@o0.ingest.sentry.io/frontend-project-id" \
  SENTRY_ENVIRONMENT="production" \
  --app lsa-frontend
```

### Step 5 — Deploy the frontend

The frontend uses several `NEXT_PUBLIC_*` variables in client-side code, so
those values must be present at **build time**, not only as runtime Fly
secrets. Pass them as Docker build args during `fly deploy`:

```bash
cd frontend
fly deploy \
  --build-arg NEXT_PUBLIC_API_URL="https://lsa-backend.fly.dev" \
  --build-arg NEXT_PUBLIC_WS_URL="wss://lsa-backend.fly.dev" \
  --build-arg NEXT_PUBLIC_LIVEKIT_URL="wss://your-project.livekit.cloud" \
  --build-arg NEXT_PUBLIC_GOOGLE_CLIENT_ID="your-google-client-id" \
  --build-arg NEXT_PUBLIC_SENTRY_DSN="https://key@o0.ingest.sentry.io/frontend-project-id" \
  --build-arg NEXT_PUBLIC_SENTRY_ENVIRONMENT="production" \
  --app lsa-frontend
```

If Google OAuth or Sentry is disabled, you can omit those specific build args.

Verify the frontend is up:

```bash
fly status --app lsa-frontend
curl -I https://lsa-frontend.fly.dev
```

### Step 6 — [MANUAL] Register the LiveKit webhook

Follow §4.1 to register `https://lsa-backend.fly.dev/api/livekit/webhooks` in
the LiveKit Cloud dashboard.

### Step 7 — [MANUAL] Verify Sentry integration

Create a test error in each service and confirm it appears in the Sentry
dashboards for the backend and frontend projects.

---

## 7. DNS setup

Fly.io provides free `*.fly.dev` subdomains automatically.  For custom domains:

1. In the Fly dashboard → your app → **Certificates**, click **Add a
   certificate** and enter your domain (e.g., `api.example.com`).
2. Fly will provide a `CNAME` or `A` record target.  Add it in your DNS
   provider.
3. Wait for TLS provisioning (usually < 5 minutes after DNS propagates).
4. Update `NEXTAUTH_URL`, `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`,
   `LSA_CORS_ORIGINS`, and the LiveKit webhook URL to use your custom domain.
5. Re-deploy both apps to pick up the new environment values.

---

## 8. Smoke test checklist

Run these checks immediately after every production deployment:

### Backend health

```bash
# Should return 200 with {"status":"ok",...}
curl https://lsa-backend.fly.dev/health
```

### Authentication flow

- [ ] Open `https://lsa-frontend.fly.dev/login`
- [ ] Sign in with email/password (register first at `/register` if needed)
- [ ] If Google OAuth is enabled: sign in with Google
- [ ] Confirm redirect to the home page after sign-in

### Session creation and live call

- [ ] Click **Create Session** — a session ID and student join link appear
- [ ] Open the student link in a second browser/tab
- [ ] Both participants grant camera/mic access
- [ ] Confirm audio/video is visible in both windows
- [ ] Tutor sees live coaching overlay; student does not
- [ ] Click **End Session** — session ends for both participants

### Post-session analytics

- [ ] Navigate to `/analytics`
- [ ] Confirm the completed session appears in the list
- [ ] Open the session detail — metrics and summary are populated

### LiveKit Cloud dashboard

- [ ] Log in to <https://cloud.livekit.io> → **Rooms**
- [ ] Confirm the test session room appeared and closed

### Sentry

- [ ] Confirm no unexpected errors appear in the Sentry dashboards
- [ ] Trigger a deliberate test error (e.g., visit a nonexistent page) and
  confirm it is captured

### Logs

```bash
fly logs --app lsa-backend
fly logs --app lsa-frontend
```

No `ERROR` or `CRITICAL` log lines should appear for normal traffic.

---

## 9. Rollback procedure

### Fly.io — roll back to the previous release

```bash
# List recent releases
fly releases --app lsa-backend

# Roll back to a specific version
fly deploy --image registry.fly.io/lsa-backend:<previous-version> --app lsa-backend
```

The same applies to `lsa-frontend`.

### Database — point-in-time restore

For Neon: navigate to **Branches → Restore** and select a restore point.
For Fly Postgres: use `fly postgres backup list` and `fly postgres restore`.

### Emergency backend downgrade checklist

1. Roll back the Fly app image (above).
2. If the schema changed: restore the database from backup or run a down-migration.
3. Update `LSA_CORS_ORIGINS` if the frontend URL changed.
4. Re-register the LiveKit webhook if the backend URL changed.
5. Notify users of any expected downtime.

---

## 10. Environment variable reference

See `.env.production.example` in the project root for the full annotated list
of every variable, organized by service plane, with generation instructions.

| Plane | Key variables |
|---|---|
| Auth | `LSA_JWT_SECRET`, `AUTH_SECRET` |
| Google OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `LSA_GOOGLE_CLIENT_ID`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID` |
| Database | `LSA_DATABASE_URL`, `LSA_STORAGE_BACKEND` |
| Object Storage | `LSA_TRACE_STORAGE_BACKEND`, `LSA_S3_ENDPOINT_URL`, `LSA_S3_BUCKET_NAME`, `LSA_S3_ACCESS_KEY_ID`, `LSA_S3_SECRET_ACCESS_KEY` |
| LiveKit | `LSA_LIVEKIT_URL`, `LSA_LIVEKIT_API_KEY`, `LSA_LIVEKIT_API_SECRET`, `NEXT_PUBLIC_LIVEKIT_URL` |
| Observability | `LSA_SENTRY_DSN`, `LSA_SENTRY_ENVIRONMENT`, `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT` |
| Frontend URLs | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, `NEXTAUTH_URL`, `NEXTAUTH_BACKEND_URL` |
| CORS | `LSA_CORS_ORIGINS` |

---

## 11. Architecture notes

### Why single backend instance for now

Live session state (active rooms, reconnect grace periods) is currently held in
the backend process memory.  Running more than one backend instance without a
shared coordination layer (Redis or similar) would cause sessions to fail if
requests hit different instances.

**For the current pilot phase, keep `min_machines_running = 1` and
`auto_stop_machines = false` in `backend/fly.toml`** to prevent scale-to-zero
during active sessions.

### Migration path for persistence

The recommended migration order:

1. **Session summaries → Postgres** (`LSA_STORAGE_BACKEND=postgres`) — highest
   priority; enables SQL filtering and durable analytics.
2. **Auth → Postgres** (automatic when `LSA_STORAGE_BACKEND=postgres`) — replaces
   the local SQLite file.
3. **Traces → R2/S3** (`LSA_TRACE_STORAGE_BACKEND=s3`) — moves large artifact
   files off the ephemeral container disk.

Local file/SQLite stores remain the default and are fully supported for local
development.

### When to add Redis / multi-instance backend

Add shared state coordination when one of the following becomes true:

- Session volume requires more than one backend instance
- You need zero-downtime deploys without session drops
- You need cross-instance reconnect recovery

At that point, move live session state into Redis and revisit the Fly.io machine
sizing and `min_machines_running` settings.

### LiveKit self-hosting

LiveKit Cloud is recommended for the current deployment scale.  If you
later need to self-host LiveKit (cost, data residency, or custom SFU
configuration), the only code change needed is updating `LSA_LIVEKIT_URL` to
point at your self-hosted cluster.  LiveKit Cloud and self-hosted use the same
API key/secret and webhook HMAC scheme.
