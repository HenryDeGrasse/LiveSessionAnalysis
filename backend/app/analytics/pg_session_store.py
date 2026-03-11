from __future__ import annotations

"""Postgres-backed session store implementation.

Stores :class:`~app.models.SessionSummary` objects in a ``session_summaries``
table.  Key filterable fields are promoted to indexed columns for efficient
querying; the full summary payload lives in a ``data JSONB`` column so that
schema-less fields (timeline, nudge_details, etc.) are preserved without
requiring a migration for every model change.

Table DDL (created by the schema initialisation script):

    CREATE TABLE IF NOT EXISTS session_summaries (
        id               SERIAL PRIMARY KEY,
        session_id       TEXT UNIQUE NOT NULL,
        tutor_id         TEXT,
        student_user_id  TEXT,
        session_type     TEXT,
        start_time       TIMESTAMPTZ,
        end_time         TIMESTAMPTZ,
        duration_seconds FLOAT,
        engagement_score FLOAT,
        data             JSONB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ss_tutor_id     ON session_summaries(tutor_id);
    CREATE INDEX IF NOT EXISTS idx_ss_student_id   ON session_summaries(student_user_id);
    CREATE INDEX IF NOT EXISTS idx_ss_start_time   ON session_summaries(start_time);
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..models import SessionSummary
from ..config import settings

logger = logging.getLogger(__name__)


def _utc(dt: datetime) -> datetime:
    """Return *dt* as a UTC-aware datetime (assume UTC when naïve)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PgSessionStore:
    """Postgres-backed session persistence.

    Uses ``psycopg`` (v3 synchronous API) so that it can serve as a drop-in
    replacement for the synchronous file-based :class:`SessionStore`.

    A simple connection-per-call strategy is used (no pool) so that the store
    is safe to instantiate without any background threads or event loops.  A
    ``psycopg_pool.ConnectionPool`` can be added later when query throughput
    warrants it.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._dsn = database_url or settings.database_url
        if not self._dsn:
            raise ValueError(
                "PgSessionStore requires a database URL "
                "(settings.database_url / LSA_DATABASE_URL env var)"
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _connect(self):
        """Open and return a new psycopg connection."""
        import psycopg  # type: ignore[import]

        return psycopg.connect(self._dsn)

    # ------------------------------------------------------------------ #
    # Public interface (mirrors SessionStore)                              #
    # ------------------------------------------------------------------ #

    def save(self, summary: SessionSummary) -> None:
        """Insert or replace a session summary row."""
        data_json = summary.model_dump_json()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO session_summaries
                        (session_id, tutor_id, student_user_id, session_type,
                         start_time, end_time, duration_seconds,
                         engagement_score, data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    (
                        summary.session_id,
                        summary.tutor_id or None,
                        summary.student_user_id or None,
                        summary.session_type,
                        _utc(summary.start_time),
                        _utc(summary.end_time),
                        summary.duration_seconds,
                        summary.engagement_score,
                        data_json,
                    ),
                )
            conn.commit()

    def load(self, session_id: str) -> Optional[SessionSummary]:
        """Return the session summary for *session_id*, or ``None``."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM session_summaries WHERE session_id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        try:
            raw = row[0]
            # psycopg may return the JSONB column already parsed as a dict
            if isinstance(raw, dict):
                return SessionSummary(**raw)
            return SessionSummary(**json.loads(raw))
        except Exception as exc:
            logger.error("Failed to deserialise session %s: %s", session_id, exc)
            return None

    def list_sessions(
        self,
        tutor_id: Optional[str] = None,
        student_user_id: Optional[str] = None,
        last_n: Optional[int] = None,
    ) -> list[SessionSummary]:
        """Return sessions matching the given filters, sorted newest-first."""
        conditions: list[str] = []
        params: list = []

        if tutor_id:
            conditions.append("tutor_id = %s")
            params.append(tutor_id)
        if student_user_id:
            conditions.append("student_user_id = %s")
            params.append(student_user_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        limit_clause = f"LIMIT {int(last_n)}" if last_n is not None else ""

        query = f"""
            SELECT data
            FROM session_summaries
            {where}
            ORDER BY start_time DESC
            {limit_clause}
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        sessions: list[SessionSummary] = []
        for (raw,) in rows:
            try:
                if isinstance(raw, dict):
                    sessions.append(SessionSummary(**raw))
                else:
                    sessions.append(SessionSummary(**json.loads(raw)))
            except Exception as exc:
                logger.error("Failed to deserialise session row: %s", exc)
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session summary.  Returns ``True`` if a row was removed."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM session_summaries WHERE session_id = %s",
                    (session_id,),
                )
                deleted = cur.rowcount
            conn.commit()
        return deleted > 0

    def cleanup_expired(self, retention_days: int | None = None) -> int:
        """Delete session rows older than *retention_days*.

        Returns the number of rows deleted.
        """
        days = (
            retention_days
            if retention_days is not None
            else settings.session_retention_days
        )
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM session_summaries WHERE end_time < %s",
                    (cutoff,),
                )
                deleted = cur.rowcount
            conn.commit()
        return deleted
