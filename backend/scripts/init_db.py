#!/usr/bin/env python3
"""Initialize the Postgres schema.

Connects to the database configured by ``LSA_DATABASE_URL`` and creates the
``users`` and ``session_summaries`` tables (and their indexes) using
idempotent ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``
statements.  Safe to run multiple times — existing data is never modified.

[MANUAL] Operator steps before running this script
====================================================

(a) Provision a Postgres database.  Recommended options:

    • Neon (https://neon.tech) — generous free tier, serverless branching,
      no infrastructure to manage.  Create a project, copy the
      "Connection string" from the dashboard.

    • Supabase (https://supabase.com) — free tier, built-in auth and
      storage dashboard.  Project → Settings → Database → Connection string.

    • Fly Postgres — co-located with the app on Fly.io:
          fly pg create --name lsa-db --region ord
          fly pg attach lsa-db --app <your-app-name>
      Fly sets DATABASE_URL automatically; map it to LSA_DATABASE_URL in
      fly.toml [env] or via `fly secrets set`.

(b) Copy the Postgres connection string.  It should look like:
        postgresql://user:password@host:5432/dbname?sslmode=require

(c) Export it so this script can find it:
        export LSA_DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
    or add it to ``backend/.env``.

(d) Run this script from the ``backend/`` directory:
        cd backend
        python scripts/init_db.py

    The script will print the names of each table/index it creates (or
    confirms already exists) and exit with code 0 on success.

(e) (Optional) Run ``scripts/migrate_local_to_postgres.py`` to import any
    existing local JSON session files and SQLite users into Postgres.

(f) Also create a Cloudflare R2 bucket for trace storage:
        • Log in to Cloudflare dashboard → R2 → Create bucket
          (name suggestion: ``lsa-traces``).
        • Create an R2 API token: My Profile → API Tokens → Create Token →
          "Edit Cloudflare Workers Resources" (or R2-specific permissions).
          Note the Access Key ID and Secret Access Key.
        • Your R2 endpoint URL is:
          ``https://<account-id>.r2.cloudflarestorage.com``
        • Set these in the environment / Fly secrets:
              LSA_TRACE_STORAGE_BACKEND=s3
              LSA_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
              LSA_S3_BUCKET_NAME=lsa-traces
              LSA_S3_ACCESS_KEY_ID=<r2-access-key-id>
              LSA_S3_SECRET_ACCESS_KEY=<r2-secret>

Usage
-----
    cd backend
    python scripts/init_db.py
"""

from __future__ import annotations

import asyncio
import sys
import os

# ---------------------------------------------------------------------------
# Ensure the backend/ directory is on sys.path so ``app`` can be imported
# when the script is run directly (i.e. ``python scripts/init_db.py``).
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db import get_pool, close_pool  # noqa: E402
from app.db_schema import SCHEMA_SQL  # noqa: E402
from app.config import settings  # noqa: E402


async def _init_schema() -> None:
    """Create all tables and indexes (idempotent)."""
    db_url = settings.database_url
    if not db_url:
        print(
            "ERROR: LSA_DATABASE_URL is not set.\n"
            "Export the Postgres connection string and try again:\n"
            "  export LSA_DATABASE_URL='postgresql://user:pass@host/db?sslmode=require'",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Connecting to Postgres (host hidden) …")
    pool = await get_pool()

    print("Applying schema …")
    async with pool.acquire() as conn:
        # asyncpg requires each statement to be executed separately; split on
        # the semicolons that terminate each DDL block.
        statements = [s.strip() for s in SCHEMA_SQL.split(";") if s.strip()]
        for stmt in statements:
            await conn.execute(stmt)
            # Extract a human-readable label from the statement.
            first_line = stmt.splitlines()[0].strip()
            print(f"  OK  {first_line[:80]}")

    await close_pool()
    print("\nSchema initialisation complete.")


def main() -> None:
    asyncio.run(_init_schema())


if __name__ == "__main__":
    main()
