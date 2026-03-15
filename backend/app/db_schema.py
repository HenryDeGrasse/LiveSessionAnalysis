"""Raw SQL DDL for Postgres schema initialization.

Tables defined here mirror the current Pydantic models so that the
Postgres-backed stores can be created from a single source of truth.

Usage
-----
Import ``SCHEMA_SQL`` for the full idempotent CREATE TABLE sequence, or use
individual ``CREATE_*`` constants for targeted migrations.

    from app.db_schema import SCHEMA_SQL
    await conn.execute(SCHEMA_SQL)

All statements use ``CREATE TABLE IF NOT EXISTS`` so they are safe to run
multiple times (e.g. on application start-up or during tests).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
# Mirrors app.auth.models.User (and the SQLite schema in user_store.py).
# ``password_hash`` is stored server-side only and never serialised into API
# responses (the Pydantic model excludes it via ``Field(exclude=True)``).
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT        PRIMARY KEY,
    email         TEXT        UNIQUE,
    password_hash TEXT,
    name          TEXT        NOT NULL,
    role          TEXT        NOT NULL DEFAULT 'tutor',
    google_id     TEXT        UNIQUE,
    avatar_url    TEXT,
    is_guest      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL
);
"""

# ---------------------------------------------------------------------------
# session_summaries
# ---------------------------------------------------------------------------
# Mirrors the schema expected by app.analytics.pg_session_store.PgSessionStore.
# The full SessionSummary payload is stored in `data JSONB`; a small set of
# commonly-filtered scalar fields are promoted to first-class columns and
# indexed for efficient queries.
CREATE_SESSION_SUMMARIES_TABLE = """
CREATE TABLE IF NOT EXISTS session_summaries (
    session_id       TEXT        PRIMARY KEY,
    tutor_id         TEXT,
    student_user_id  TEXT,
    session_type     TEXT,
    start_time       TIMESTAMPTZ,
    end_time         TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION,
    engagement_score DOUBLE PRECISION,
    data             JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ss_tutor_id
    ON session_summaries (tutor_id);

CREATE INDEX IF NOT EXISTS idx_ss_student_id
    ON session_summaries (student_user_id);

CREATE INDEX IF NOT EXISTS idx_ss_start_time
    ON session_summaries (start_time DESC);
"""

# ---------------------------------------------------------------------------
# Migration: AI Conversational Intelligence columns on session_summaries
# ---------------------------------------------------------------------------
# These columns store post-session enrichment data produced by the AI
# Conversational Intelligence pipeline (transcript, AI summary, topics,
# understanding map, key moments, uncertainty timeline).
#
# All statements use ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` (Postgres 9.6+)
# so they are safe to run multiple times.
MIGRATE_SESSION_SUMMARIES_AI_COLUMNS = """
ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS transcript_compact JSONB DEFAULT NULL;

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS ai_summary TEXT DEFAULT '';

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS topics_covered JSONB DEFAULT '[]';

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS student_understanding_map JSONB DEFAULT '{}';

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS key_moments JSONB DEFAULT '[]';

ALTER TABLE session_summaries
    ADD COLUMN IF NOT EXISTS uncertainty_timeline JSONB DEFAULT '[]';
"""

# ---------------------------------------------------------------------------
# Audit log for transcript deletions
# ---------------------------------------------------------------------------
CREATE_TRANSCRIPT_DELETION_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS transcript_deletion_log (
    id              SERIAL      PRIMARY KEY,
    session_id      TEXT        NOT NULL,
    deleted_by      TEXT        NOT NULL,
    deleted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    s3_key_deleted  TEXT,
    pg_cleared      BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_tdl_session_id
    ON transcript_deletion_log (session_id);
"""

# ---------------------------------------------------------------------------
# Combined schema — apply in dependency order
# ---------------------------------------------------------------------------
SCHEMA_SQL = "\n".join([
    CREATE_USERS_TABLE,
    CREATE_SESSION_SUMMARIES_TABLE,
    MIGRATE_SESSION_SUMMARIES_AI_COLUMNS,
    CREATE_TRANSCRIPT_DELETION_LOG_TABLE,
])
