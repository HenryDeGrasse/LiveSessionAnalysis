#!/usr/bin/env python3
"""One-time migration: local JSON sessions + SQLite users → Postgres.

Reads all JSON session files from ``data/sessions/`` (relative to the current
working directory, or overridden by ``LSA_SESSION_DATA_DIR``) and all users
from the SQLite database at ``data/auth.db`` (or ``LSA_AUTH_DB_PATH``), then
inserts them into the configured Postgres instance using the shared connection
helper in ``app.db``.

The migration is **idempotent**: each record is upserted (``INSERT … ON
CONFLICT DO UPDATE``), so re-running the script will not duplicate data.

[MANUAL] Prerequisites
=======================

1.  Run ``python scripts/init_db.py`` first to create the Postgres tables.

2.  Set ``LSA_DATABASE_URL`` to the target Postgres connection string:
        export LSA_DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"

3.  Also set ``LSA_STORAGE_BACKEND=postgres`` so the app uses Postgres-backed
    stores after migration:
        export LSA_STORAGE_BACKEND=postgres

4.  Run this script from the ``backend/`` directory:
        cd backend
        python scripts/migrate_local_to_postgres.py

    Pass ``--dry-run`` to print what *would* be migrated without writing:
        python scripts/migrate_local_to_postgres.py --dry-run

    Pass ``--sessions-dir`` / ``--auth-db`` to override the default paths:
        python scripts/migrate_local_to_postgres.py \
            --sessions-dir /path/to/data/sessions \
            --auth-db /path/to/data/auth.db

Usage
-----
    cd backend
    python scripts/migrate_local_to_postgres.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Ensure the backend/ directory is on sys.path so ``app`` can be imported
# when the script is run directly (i.e. ``python scripts/migrate_…``).
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import settings  # noqa: E402
from app.db import close_pool, get_pool  # noqa: E402
from app.models import SessionSummary  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_iso_timestamp(value: str | None) -> datetime:
    """Convert an ISO 8601 string to a timezone-aware UTC datetime."""
    if not value:
        return datetime.now(timezone.utc)

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Session migration helpers
# ---------------------------------------------------------------------------


def _load_local_sessions(sessions_dir: str) -> list[SessionSummary]:
    """Read all JSON session files from *sessions_dir*."""
    if not os.path.isdir(sessions_dir):
        logger.warning("Sessions directory not found: %s — skipping.", sessions_dir)
        return []

    summaries: list[SessionSummary] = []
    for fname in sorted(os.listdir(sessions_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(sessions_dir, fname)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            summaries.append(SessionSummary(**data))
        except Exception as exc:
            logger.error("Skipping %s — failed to parse: %s", path, exc)

    return summaries


async def _migrate_sessions(
    summaries: list[SessionSummary],
    dry_run: bool,
) -> tuple[int, int]:
    """Upsert *summaries* into Postgres. Returns (migrated, skipped)."""
    if not summaries:
        logger.info("No session files found — nothing to migrate.")
        return 0, 0

    if dry_run:
        logger.info("[DRY RUN] Would migrate %d session(s).", len(summaries))
        for s in summaries:
            logger.info("  session_id=%s  tutor=%s  end=%s", s.session_id, s.tutor_id, s.end_time)
        return len(summaries), 0

    pool = await get_pool()
    migrated = 0
    skipped = 0

    async with pool.acquire() as conn:
        for summary in summaries:
            try:
                await conn.execute(
                    """
                    INSERT INTO session_summaries
                        (session_id, tutor_id, student_user_id, session_type,
                         start_time, end_time, duration_seconds,
                         engagement_score, data)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                    ON CONFLICT (session_id) DO UPDATE SET
                        tutor_id         = EXCLUDED.tutor_id,
                        student_user_id  = EXCLUDED.student_user_id,
                        session_type     = EXCLUDED.session_type,
                        start_time       = EXCLUDED.start_time,
                        end_time         = EXCLUDED.end_time,
                        duration_seconds = EXCLUDED.duration_seconds,
                        engagement_score = EXCLUDED.engagement_score,
                        data             = EXCLUDED.data
                    """,
                    summary.session_id,
                    summary.tutor_id or None,
                    summary.student_user_id or None,
                    summary.session_type,
                    summary.start_time,
                    summary.end_time,
                    summary.duration_seconds,
                    summary.engagement_score,
                    summary.model_dump_json(),
                )
                logger.info("  ✓ session %s", summary.session_id)
                migrated += 1
            except Exception as exc:
                logger.error("  ✗ session %s — %s", summary.session_id, exc)
                skipped += 1

    return migrated, skipped


# ---------------------------------------------------------------------------
# User migration helpers
# ---------------------------------------------------------------------------


def _load_sqlite_users(auth_db_path: str) -> list[dict]:
    """Return all user rows from the SQLite auth database as dicts."""
    if not os.path.exists(auth_db_path):
        logger.warning("SQLite auth DB not found: %s — skipping.", auth_db_path)
        return []

    conn = sqlite3.connect(auth_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM users").fetchall()
    except sqlite3.OperationalError as exc:
        logger.error("Cannot read users from %s: %s", auth_db_path, exc)
        return []
    finally:
        conn.close()

    return [dict(row) for row in rows]


async def _migrate_users(
    user_rows: list[dict],
    dry_run: bool,
) -> tuple[int, int]:
    """Upsert *user_rows* into the Postgres users table."""
    if not user_rows:
        logger.info("No users found — nothing to migrate.")
        return 0, 0

    if dry_run:
        logger.info("[DRY RUN] Would migrate %d user(s).", len(user_rows))
        for row in user_rows:
            logger.info("  id=%s  email=%s  name=%s", row.get("id"), row.get("email"), row.get("name"))
        return len(user_rows), 0

    pool = await get_pool()
    migrated = 0
    skipped = 0

    async with pool.acquire() as conn:
        for row in user_rows:
            uid = row.get("id") or ""
            email = row.get("email")
            password_hash = row.get("password_hash")
            name = row.get("name") or ""
            role = row.get("role") or "tutor"
            google_id = row.get("google_id")
            avatar_url = row.get("avatar_url")
            is_guest = bool(row.get("is_guest", 0))
            created_at = _parse_iso_timestamp(row.get("created_at"))
            updated_at = _parse_iso_timestamp(row.get("updated_at"))

            if not uid or not name:
                logger.warning("Skipping user row with missing id or name: %s", row)
                skipped += 1
                continue

            try:
                await conn.execute(
                    """
                    INSERT INTO users
                        (id, email, password_hash, name, role, google_id,
                         avatar_url, is_guest, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (id) DO UPDATE SET
                        email         = EXCLUDED.email,
                        password_hash = EXCLUDED.password_hash,
                        name          = EXCLUDED.name,
                        role          = EXCLUDED.role,
                        google_id     = EXCLUDED.google_id,
                        avatar_url    = EXCLUDED.avatar_url,
                        is_guest      = EXCLUDED.is_guest,
                        updated_at    = EXCLUDED.updated_at
                    """,
                    uid,
                    email,
                    password_hash,
                    name,
                    role,
                    google_id,
                    avatar_url,
                    is_guest,
                    created_at,
                    updated_at,
                )
                logger.info("  ✓ user %s (%s)", uid, email or "<no email>")
                migrated += 1
            except Exception as exc:
                logger.error("  ✗ user %s — %s", uid, exc)
                skipped += 1

    return migrated, skipped


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate local JSON sessions and SQLite users to Postgres.\n"
            "Requires LSA_DATABASE_URL to be set."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sessions-dir",
        default=settings.session_data_dir,
        help=(
            "Path to the directory containing local JSON session files. "
            f"Default: {settings.session_data_dir!r} (LSA_SESSION_DATA_DIR)"
        ),
    )
    parser.add_argument(
        "--auth-db",
        default=settings.auth_db_path,
        help=(
            "Path to the SQLite auth database. "
            f"Default: {settings.auth_db_path!r} (LSA_AUTH_DB_PATH)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be migrated without writing anything to Postgres.",
    )
    parser.add_argument(
        "--skip-sessions",
        action="store_true",
        help="Skip session migration (only migrate users).",
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help="Skip user migration (only migrate sessions).",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    if not settings.database_url and not args.dry_run:
        logger.error("LSA_DATABASE_URL is not set — cannot connect to Postgres.")
        raise SystemExit(1)

    if args.dry_run:
        logger.info("=== DRY RUN — no data will be written ===")

    try:
        if not args.skip_sessions:
            logger.info("Loading local sessions from: %s", args.sessions_dir)
            summaries = _load_local_sessions(args.sessions_dir)
            logger.info("Found %d session file(s).", len(summaries))
            s_migrated, s_skipped = await _migrate_sessions(summaries, dry_run=args.dry_run)
            logger.info("Sessions: %d migrated, %d skipped/failed.", s_migrated, s_skipped)
        else:
            logger.info("Skipping session migration (--skip-sessions).")

        if not args.skip_users:
            logger.info("Loading SQLite users from: %s", args.auth_db)
            user_rows = _load_sqlite_users(args.auth_db)
            logger.info("Found %d user row(s).", len(user_rows))
            u_migrated, u_skipped = await _migrate_users(user_rows, dry_run=args.dry_run)
            logger.info("Users: %d migrated, %d skipped/failed.", u_migrated, u_skipped)
        else:
            logger.info("Skipping user migration (--skip-users).")
    finally:
        await close_pool()

    logger.info("Migration complete.")


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
