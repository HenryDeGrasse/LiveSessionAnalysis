from __future__ import annotations

"""Unit tests for PgSessionStore.

When LSA_DATABASE_URL is not set (i.e. in CI / local unit-test runs without a
real Postgres instance) the tests that require a live database are skipped.
Tests that only exercise the factory / selection logic run unconditionally.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest

from app.models import SessionSummary, FlaggedMoment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HAS_DB = bool(os.environ.get("LSA_DATABASE_URL"))

requires_db = pytest.mark.skipif(
    not _HAS_DB,
    reason="LSA_DATABASE_URL not set — skipping live Postgres tests",
)


def _make_summary(
    session_id: str = "pg-s1",
    tutor_id: str = "tutor1",
    student_user_id: str = "student1",
    engagement_score: float = 75.0,
    start_time: Optional[datetime] = None,
    duration: float = 300.0,
    session_type: str = "general",
) -> SessionSummary:
    st = start_time or datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        student_user_id=student_user_id,
        start_time=st,
        end_time=st + timedelta(seconds=duration),
        duration_seconds=duration,
        session_type=session_type,
        talk_time_ratio={"tutor": 0.6, "student": 0.4},
        avg_eye_contact={"tutor": 0.8, "student": 0.5},
        avg_energy={"tutor": 0.7, "student": 0.6},
        total_interruptions=2,
        engagement_score=engagement_score,
        flagged_moments=[
            FlaggedMoment(
                timestamp=120.0,
                metric_name="eye_contact",
                value=0.1,
                direction="below",
                description="Student eye contact dropped",
            )
        ],
        timeline={"engagement": [70.0, 75.0, 80.0]},
        nudges_sent=3,
    )


# ---------------------------------------------------------------------------
# Factory / selection logic (no DB required)
# ---------------------------------------------------------------------------


class TestGetSessionStoreFactory:
    """Tests for the get_session_store() factory function."""

    def setup_method(self):
        # Reset the singleton between tests
        import app.analytics as analytics_pkg
        analytics_pkg._reset_store()

    def teardown_method(self):
        import app.analytics as analytics_pkg
        analytics_pkg._reset_store()

    def test_returns_file_store_by_default(self):
        """With default settings (local backend, no database_url), returns SessionStore."""
        from app.config import settings
        from app.analytics.session_store import SessionStore
        from app.analytics import get_session_store

        with patch.object(settings, "storage_backend", "local"), \
             patch.object(settings, "database_url", ""):
            import app.analytics as analytics_pkg
            analytics_pkg._reset_store()
            store = get_session_store()
        assert isinstance(store, SessionStore)

    def test_returns_file_store_when_postgres_backend_but_no_url(self):
        """When storage_backend=postgres but database_url is empty, falls back to file store."""
        from app.config import settings
        from app.analytics.session_store import SessionStore
        from app.analytics import get_session_store

        with patch.object(settings, "storage_backend", "postgres"), \
             patch.object(settings, "database_url", ""):
            import app.analytics as analytics_pkg
            analytics_pkg._reset_store()
            store = get_session_store()
        assert isinstance(store, SessionStore)

    def test_returns_pg_store_when_postgres_backend_and_url_set(self):
        """When both storage_backend=postgres and database_url are set, returns PgSessionStore."""
        from app.config import settings
        from app.analytics.pg_session_store import PgSessionStore
        from app.analytics import get_session_store

        with patch.object(settings, "storage_backend", "postgres"), \
             patch.object(settings, "database_url", "postgresql://fake/db"):
            import app.analytics as analytics_pkg
            analytics_pkg._reset_store()
            store = get_session_store()
        assert isinstance(store, PgSessionStore)

    def test_singleton_returns_same_instance(self):
        """Second call to get_session_store() returns the same object."""
        from app.analytics import get_session_store

        store1 = get_session_store()
        store2 = get_session_store()
        assert store1 is store2


# ---------------------------------------------------------------------------
# PgSessionStore unit tests using mocked psycopg connections
# ---------------------------------------------------------------------------


def _make_mock_cursor(rows=None, rowcount=0):
    cur = MagicMock()
    if rows is not None:
        cur.fetchone.return_value = rows[0] if rows else None
        cur.fetchall.return_value = rows
    cur.rowcount = rowcount
    return cur


def _make_mock_conn(cursor):
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


class TestPgSessionStoreMocked:
    """PgSessionStore tests that mock out the psycopg connection layer."""

    def _store(self):
        from app.analytics.pg_session_store import PgSessionStore
        return PgSessionStore(database_url="postgresql://fake/db")

    # -- save -----------------------------------------------------------

    def test_save_executes_upsert(self):
        summary = _make_summary()
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.save(summary)

        mock_cur.execute.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO session_summaries" in sql
        assert "ON CONFLICT" in sql
        mock_conn.commit.assert_called_once()

    def test_save_includes_correct_params(self):
        summary = _make_summary(
            session_id="pg-s1",
            tutor_id="tutor1",
            student_user_id="student1",
            engagement_score=88.5,
        )
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.save(summary)

        params = mock_cur.execute.call_args[0][1]
        assert params[0] == "pg-s1"         # session_id
        assert params[1] == "tutor1"         # tutor_id
        assert params[2] == "student1"       # student_user_id
        assert params[7] == 88.5             # engagement_score
        # data param (index 8) should be valid JSON containing session_id
        data = json.loads(params[8])
        assert data["session_id"] == "pg-s1"

    # -- load -----------------------------------------------------------

    def test_load_returns_summary_when_row_found(self):
        summary = _make_summary()
        raw_json = summary.model_dump_json()

        store = self._store()
        mock_cur = _make_mock_cursor(rows=[(raw_json,)])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.load("pg-s1")

        assert result is not None
        assert result.session_id == "pg-s1"
        assert result.engagement_score == 75.0

    def test_load_returns_none_when_no_row(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[])
        mock_cur.fetchone.return_value = None
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.load("nonexistent")

        assert result is None

    def test_load_handles_dict_from_psycopg(self):
        """psycopg may return JSONB columns as Python dicts directly."""
        summary = _make_summary()
        raw_dict = summary.model_dump()

        store = self._store()
        mock_cur = _make_mock_cursor(rows=[(raw_dict,)])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.load("pg-s1")

        assert result is not None
        assert result.session_id == "pg-s1"

    def test_load_returns_none_on_corrupt_data(self, caplog):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[("not-valid-json{{",)])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.load("bad")

        assert result is None

    # -- list_sessions --------------------------------------------------

    def test_list_sessions_no_filters(self):
        summaries = [_make_summary(session_id=f"s{i}") for i in range(3)]
        rows = [(s.model_dump_json(),) for s in summaries]

        store = self._store()
        mock_cur = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.list_sessions()

        assert len(result) == 3

    def test_list_sessions_with_tutor_filter(self):
        summary = _make_summary(tutor_id="alice")
        rows = [(summary.model_dump_json(),)]

        store = self._store()
        mock_cur = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.list_sessions(tutor_id="alice")

        sql = mock_cur.execute.call_args[0][0]
        params = mock_cur.execute.call_args[0][1]
        assert "tutor_id = %s" in sql
        assert "alice" in params

    def test_list_sessions_with_limit(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.list_sessions(last_n=5)

        sql = mock_cur.execute.call_args[0][0]
        assert "LIMIT 5" in sql

    def test_list_sessions_without_limit(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.list_sessions()

        sql = mock_cur.execute.call_args[0][0]
        assert "LIMIT" not in sql

    def test_list_sessions_skips_bad_rows(self, caplog):
        rows = [("not-json{{",), (_make_summary(session_id="good").model_dump_json(),)]

        store = self._store()
        mock_cur = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.list_sessions()

        assert len(result) == 1
        assert result[0].session_id == "good"

    # -- delete ---------------------------------------------------------

    def test_delete_returns_true_when_row_deleted(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=1)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.delete("pg-s1")

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_delete_returns_false_when_no_row(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=0)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.delete("nonexistent")

        assert result is False

    # -- cleanup_expired ------------------------------------------------

    def test_cleanup_expired_uses_retention_days_setting(self):
        from app.config import settings

        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=3)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn), \
             patch.object(settings, "session_retention_days", 30):
            deleted = store.cleanup_expired()

        assert deleted == 3
        sql = mock_cur.execute.call_args[0][0]
        assert "DELETE FROM session_summaries" in sql
        assert "end_time < %s" in sql

    def test_cleanup_expired_accepts_custom_days(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=1)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            deleted = store.cleanup_expired(retention_days=7)

        assert deleted == 1

    # -- constructor ----------------------------------------------------

    def test_raises_without_database_url(self):
        from app.analytics.pg_session_store import PgSessionStore

        with pytest.raises(ValueError, match="database URL"):
            PgSessionStore(database_url="")


# ---------------------------------------------------------------------------
# Live Postgres tests (skipped unless LSA_DATABASE_URL is set)
# ---------------------------------------------------------------------------


@requires_db
class TestPgSessionStoreLive:
    """Integration tests against a real Postgres instance.

    These tests require LSA_DATABASE_URL to point to a running database with
    the session_summaries table already created (run the schema init script
    first).
    """

    @pytest.fixture(autouse=True)
    def store(self):
        from app.analytics.pg_session_store import PgSessionStore

        return PgSessionStore()

    @pytest.fixture(autouse=True)
    def cleanup(self, store):
        yield
        # Best-effort cleanup of any sessions we created
        for sid in ("live-s1", "live-s2", "live-s3"):
            try:
                store.delete(sid)
            except Exception:
                pass

    def test_save_and_load_roundtrip(self, store):
        summary = _make_summary(session_id="live-s1")
        store.save(summary)
        loaded = store.load("live-s1")
        assert loaded is not None
        assert loaded.session_id == "live-s1"
        assert loaded.engagement_score == 75.0

    def test_load_nonexistent_returns_none(self, store):
        assert store.load("no-such-session-xyz") is None

    def test_save_upserts(self, store):
        store.save(_make_summary(session_id="live-s1", engagement_score=50.0))
        store.save(_make_summary(session_id="live-s1", engagement_score=99.0))
        loaded = store.load("live-s1")
        assert loaded is not None
        assert loaded.engagement_score == 99.0

    def test_list_and_filter_by_tutor(self, store):
        store.save(_make_summary(session_id="live-s1", tutor_id="live-alice"))
        store.save(_make_summary(session_id="live-s2", tutor_id="live-bob"))
        result = store.list_sessions(tutor_id="live-alice")
        sids = [s.session_id for s in result]
        assert "live-s1" in sids
        assert "live-s2" not in sids

    def test_delete_removes_row(self, store):
        store.save(_make_summary(session_id="live-s3"))
        assert store.delete("live-s3") is True
        assert store.load("live-s3") is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete("no-such-session-xyz") is False
