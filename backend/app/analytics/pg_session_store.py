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
from typing import Any, Optional

from ..models import SessionSummary
from ..config import settings

logger = logging.getLogger(__name__)


def _utc(dt: datetime) -> datetime:
    """Return *dt* as a UTC-aware datetime (assume UTC when naïve)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _decode_json_value(value: Any) -> Any:
    """Decode JSON/JSONB values returned by psycopg.

    psycopg may return JSONB columns as already-parsed Python values or as raw
    JSON strings depending on connection configuration and test doubles.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


def _merge_summary_payload(
    raw_data: Any,
    *,
    transcript_compact: Any = None,
    ai_summary: Any = None,
    topics_covered: Any = None,
    student_understanding_map: Any = None,
    key_moments: Any = None,
    uncertainty_timeline: Any = None,
) -> SessionSummary:
    """Merge JSONB payload with promoted transcript/enrichment columns."""
    if isinstance(raw_data, dict):
        payload = dict(raw_data)
    else:
        payload = json.loads(raw_data)

    if transcript_compact is not None:
        payload["transcript_compact"] = _decode_json_value(transcript_compact)

    if ai_summary not in (None, ""):
        payload["ai_summary"] = ai_summary
    elif "ai_summary" not in payload:
        payload["ai_summary"] = None

    if topics_covered is not None:
        payload["topics_covered"] = _decode_json_value(topics_covered)
    else:
        payload.setdefault("topics_covered", [])

    if student_understanding_map is not None:
        payload["student_understanding_map"] = _decode_json_value(student_understanding_map)
    else:
        payload.setdefault("student_understanding_map", {})

    if key_moments is not None:
        payload["key_moments"] = _decode_json_value(key_moments)
    else:
        payload.setdefault("key_moments", [])

    if uncertainty_timeline is not None:
        payload["uncertainty_timeline"] = _decode_json_value(uncertainty_timeline)
    else:
        payload.setdefault("uncertainty_timeline", [])

    return SessionSummary(**payload)


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
                         engagement_score, data, transcript_compact, ai_summary,
                         topics_covered, student_understanding_map, key_moments,
                         uncertainty_timeline)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO UPDATE SET
                        tutor_id                   = EXCLUDED.tutor_id,
                        student_user_id            = EXCLUDED.student_user_id,
                        session_type               = EXCLUDED.session_type,
                        start_time                 = EXCLUDED.start_time,
                        end_time                   = EXCLUDED.end_time,
                        duration_seconds           = EXCLUDED.duration_seconds,
                        engagement_score           = EXCLUDED.engagement_score,
                        data                       = EXCLUDED.data,
                        transcript_compact         = EXCLUDED.transcript_compact,
                        ai_summary                 = EXCLUDED.ai_summary,
                        topics_covered             = EXCLUDED.topics_covered,
                        student_understanding_map  = EXCLUDED.student_understanding_map,
                        key_moments                = EXCLUDED.key_moments,
                        uncertainty_timeline       = EXCLUDED.uncertainty_timeline
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
                        json.dumps(summary.transcript_compact) if summary.transcript_compact is not None else None,
                        summary.ai_summary or "",
                        json.dumps(summary.topics_covered),
                        json.dumps(summary.student_understanding_map),
                        json.dumps(summary.key_moments),
                        json.dumps(summary.uncertainty_timeline),
                    ),
                )
            conn.commit()

    def load(self, session_id: str) -> Optional[SessionSummary]:
        """Return the session summary for *session_id*, or ``None``."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data, transcript_compact, ai_summary, topics_covered,
                           student_understanding_map, key_moments,
                           uncertainty_timeline
                    FROM session_summaries
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        try:
            return _merge_summary_payload(
                row[0],
                transcript_compact=row[1],
                ai_summary=row[2],
                topics_covered=row[3],
                student_understanding_map=row[4],
                key_moments=row[5],
                uncertainty_timeline=row[6],
            )
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
            SELECT data, transcript_compact, ai_summary, topics_covered,
                   student_understanding_map, key_moments,
                   uncertainty_timeline
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
        for row in rows:
            try:
                sessions.append(
                    _merge_summary_payload(
                        row[0],
                        transcript_compact=row[1],
                        ai_summary=row[2],
                        topics_covered=row[3],
                        student_understanding_map=row[4],
                        key_moments=row[5],
                        uncertainty_timeline=row[6],
                    )
                )
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

    # ------------------------------------------------------------------ #
    # Transcript-specific operations                                       #
    # ------------------------------------------------------------------ #

    def clear_transcript_data(self, session_id: str) -> bool:
        """Clear transcript and AI enrichment columns for a session.

        Sets ``transcript_compact``, ``ai_summary``, ``topics_covered``,
        ``student_understanding_map``, ``key_moments``, and
        ``uncertainty_timeline`` back to their default values.  Also zeros
        ``transcript_word_count`` and ``transcript_available`` inside the
        ``data`` JSONB column.

        Returns ``True`` if a row was updated, ``False`` if not found.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE session_summaries
                    SET transcript_compact = NULL,
                        ai_summary = '',
                        topics_covered = '[]'::jsonb,
                        student_understanding_map = '{}'::jsonb,
                        key_moments = '[]'::jsonb,
                        uncertainty_timeline = '[]'::jsonb,
                        data = COALESCE(data, '{}'::jsonb)
                            || '{"transcript_compact": null,
                                "transcript_word_count": 0,
                                "transcript_available": false,
                                "ai_summary": null,
                                "topics_covered": [],
                                "student_understanding_map": {},
                                "key_moments": [],
                                "uncertainty_timeline": [],
                                "follow_up_recommendations": []}'::jsonb
                    WHERE session_id = %s
                    """,
                    (session_id,),
                )
                updated = cur.rowcount
            conn.commit()
        return updated > 0

    def log_transcript_deletion(
        self,
        session_id: str,
        deleted_by: str,
        *,
        s3_key_deleted: str | None = None,
        pg_cleared: bool = False,
    ) -> None:
        """Record an audit entry in the transcript_deletion_log table.

        Falls back silently if the audit table does not exist (e.g. during
        local-only development without migration).
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO transcript_deletion_log
                            (session_id, deleted_by, deleted_at, s3_key_deleted, pg_cleared)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            session_id,
                            deleted_by,
                            datetime.now(tz=timezone.utc),
                            s3_key_deleted,
                            pg_cleared,
                        ),
                    )
                conn.commit()
        except Exception as exc:
            logger.warning(
                "Failed to log transcript deletion for session %s: %s",
                session_id,
                exc,
            )
