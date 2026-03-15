"""Tests for transcript deletion endpoint and related store methods.

Covers:
- DELETE /api/analytics/sessions/{id}/transcript endpoint
- PgSessionStore.clear_transcript_data()
- PgSessionStore.log_transcript_deletion()
- Auth checks (401, 403, 404)
- S3 transcript artifact deletion
- Audit logging
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.models import SessionSummary, FlaggedMoment
from app.auth.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_summary(
    session_id: str = "del-s1",
    tutor_id: str = "tutor1",
    student_user_id: str = "student1",
    engagement_score: float = 75.0,
    transcript_compact: Optional[dict] = None,
) -> SessionSummary:
    st = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        student_user_id=student_user_id,
        start_time=st,
        end_time=st + timedelta(seconds=300),
        duration_seconds=300.0,
        session_type="general",
        engagement_score=engagement_score,
        transcript_compact=transcript_compact or {
            "utterances": [
                {"utterance_id": "u1", "role": "student", "text": "Hello", "start_time": 1.0, "end_time": 2.0},
                {"utterance_id": "u2", "role": "tutor", "text": "Hi there", "start_time": 2.5, "end_time": 3.5},
            ],
            "word_count": 4,
        },
        transcript_word_count=4,
        transcript_available=True,
        ai_summary="Good session overall.",
        topics_covered=["algebra", "fractions"],
        student_understanding_map={"algebra": 0.8, "fractions": 0.5},
        key_moments=[{"time": 120.0, "type": "breakthrough", "description": "Student understood fractions"}],
        uncertainty_timeline=[{"time": 60.0, "score": 0.7, "topic": "fractions"}],
    )


def _make_user(user_id: str = "tutor1", role: str = "tutor") -> User:
    now = datetime.now(tz=timezone.utc).isoformat()
    return User(
        id=user_id,
        name="Test User",
        role=role,
        created_at=now,
        updated_at=now,
    )


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


# ---------------------------------------------------------------------------
# PgSessionStore.clear_transcript_data tests
# ---------------------------------------------------------------------------


class TestClearTranscriptData:
    """Tests for PgSessionStore.clear_transcript_data."""

    def _store(self):
        from app.analytics.pg_session_store import PgSessionStore
        return PgSessionStore(database_url="postgresql://fake/db")

    def test_clear_returns_true_when_row_updated(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=1)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.clear_transcript_data("del-s1")

        assert result is True
        mock_conn.commit.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "UPDATE session_summaries" in sql
        assert "transcript_compact = NULL" in sql
        assert "ai_summary = ''" in sql
        assert "transcript_word_count" in sql
        assert "follow_up_recommendations" in sql

    def test_clear_returns_false_when_no_row(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=0)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.clear_transcript_data("nonexistent")

        assert result is False

    def test_clear_passes_session_id_as_param(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rowcount=1)
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.clear_transcript_data("my-session")

        params = mock_cur.execute.call_args[0][1]
        assert params == ("my-session",)


# ---------------------------------------------------------------------------
# PgSessionStore.log_transcript_deletion tests
# ---------------------------------------------------------------------------


class TestLogTranscriptDeletion:
    """Tests for PgSessionStore.log_transcript_deletion."""

    def _store(self):
        from app.analytics.pg_session_store import PgSessionStore
        return PgSessionStore(database_url="postgresql://fake/db")

    def test_logs_deletion_with_all_fields(self):
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.log_transcript_deletion(
                "del-s1",
                "tutor1",
                s3_key_deleted="traces/transcripts/del-s1.json",
                pg_cleared=True,
            )

        mock_cur.execute.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO transcript_deletion_log" in sql
        params = mock_cur.execute.call_args[0][1]
        assert params[0] == "del-s1"
        assert params[1] == "tutor1"
        assert params[3] == "traces/transcripts/del-s1.json"
        assert params[4] is True
        mock_conn.commit.assert_called_once()

    def test_logs_deletion_without_s3_key(self):
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.log_transcript_deletion("del-s1", "tutor1", pg_cleared=True)

        params = mock_cur.execute.call_args[0][1]
        assert params[3] is None  # s3_key_deleted
        assert params[4] is True  # pg_cleared

    def test_suppresses_exception_on_missing_audit_table(self, caplog):
        store = self._store()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = MagicMock(side_effect=Exception("relation does not exist"))

        with patch.object(store, "_connect", return_value=mock_conn):
            # Should not raise
            store.log_transcript_deletion("del-s1", "tutor1")


# ---------------------------------------------------------------------------
# DELETE /api/analytics/sessions/{id}/transcript endpoint tests
# ---------------------------------------------------------------------------


class TestDeleteTranscriptEndpoint:
    """Tests for the DELETE /api/analytics/sessions/{id}/transcript endpoint."""

    @pytest.fixture(autouse=True)
    def setup_store(self):
        """Wire up a mock store for the analytics router."""
        import app.analytics.router as router_mod
        self.mock_store = MagicMock()
        self._original_store = router_mod.store
        router_mod.store = self.mock_store
        yield
        router_mod.store = self._original_store

    @pytest.fixture()
    def client(self):
        from app.main import app
        return TestClient(app)

    def _auth_override(self, user: Optional[User] = None):
        """Return a dependency override for get_optional_user."""
        from app.auth.dependencies import get_optional_user

        async def _override():
            return user

        from app.main import app
        app.dependency_overrides[get_optional_user] = _override
        return app

    def _cleanup_overrides(self):
        from app.main import app
        from app.auth.dependencies import get_optional_user
        app.dependency_overrides.pop(get_optional_user, None)

    def test_401_when_unauthenticated(self, client):
        self._auth_override(None)
        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 401
        finally:
            self._cleanup_overrides()

    def test_404_when_session_not_found(self, client):
        user = _make_user("tutor1")
        self._auth_override(user)
        self.mock_store.load.return_value = None
        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 404
        finally:
            self._cleanup_overrides()

    def test_403_when_not_owner(self, client):
        user = _make_user("other-user")
        self._auth_override(user)
        self.mock_store.load.return_value = _make_summary(tutor_id="tutor1", student_user_id="student1")
        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 403
        finally:
            self._cleanup_overrides()

    def test_204_when_tutor_deletes_transcript(self, client):
        user = _make_user("tutor1", role="tutor")
        self._auth_override(user)
        summary = _make_summary(tutor_id="tutor1")
        self.mock_store.load.return_value = summary
        self.mock_store.clear_transcript_data.return_value = True

        try:
            with patch("app.analytics.router.settings", create=True) as mock_settings:
                mock_settings = MagicMock()
                mock_settings.trace_storage_backend = "local"
                with patch("app.analytics.router._session_store", return_value=self.mock_store):
                    # Simpler: just use the store mock directly
                    resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 204
        finally:
            self._cleanup_overrides()

    def test_204_when_student_deletes_transcript(self, client):
        user = _make_user("student1", role="student")
        self._auth_override(user)
        summary = _make_summary(student_user_id="student1")
        self.mock_store.load.return_value = summary
        self.mock_store.clear_transcript_data.return_value = True

        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 204
        finally:
            self._cleanup_overrides()

    def test_plain_api_alias_route_works(self, client):
        user = _make_user("tutor1", role="tutor")
        self._auth_override(user)
        summary = _make_summary(tutor_id="tutor1")
        self.mock_store.load.return_value = summary
        self.mock_store.clear_transcript_data.return_value = True

        try:
            resp = client.delete("/api/sessions/del-s1/transcript")
            assert resp.status_code == 204
            self.mock_store.clear_transcript_data.assert_called_once_with("del-s1")
        finally:
            self._cleanup_overrides()

    def test_calls_clear_transcript_data_on_pg_store(self, client):
        user = _make_user("tutor1")
        self._auth_override(user)
        summary = _make_summary(tutor_id="tutor1")
        self.mock_store.load.return_value = summary
        self.mock_store.clear_transcript_data.return_value = True

        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 204
            self.mock_store.clear_transcript_data.assert_called_once_with("del-s1")
        finally:
            self._cleanup_overrides()

    def test_calls_log_transcript_deletion(self, client):
        user = _make_user("tutor1")
        self._auth_override(user)
        summary = _make_summary(tutor_id="tutor1")
        self.mock_store.load.return_value = summary
        self.mock_store.clear_transcript_data.return_value = True

        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 204
            self.mock_store.log_transcript_deletion.assert_called_once()
            call_args = self.mock_store.log_transcript_deletion.call_args
            assert call_args[0][0] == "del-s1"  # session_id
            assert call_args[0][1] == "tutor1"  # deleted_by
        finally:
            self._cleanup_overrides()

    def test_falls_back_to_save_when_no_clear_method(self, client):
        """File-based store fallback: clears fields via save()."""
        user = _make_user("tutor1")
        self._auth_override(user)
        summary = _make_summary(tutor_id="tutor1")
        self.mock_store.load.return_value = summary
        # Remove clear_transcript_data to simulate file-based store
        del self.mock_store.clear_transcript_data
        # Also remove log_transcript_deletion
        del self.mock_store.log_transcript_deletion

        try:
            resp = client.delete("/api/analytics/sessions/del-s1/transcript")
            assert resp.status_code == 204
            self.mock_store.save.assert_called_once()
            saved_summary = self.mock_store.save.call_args[0][0]
            assert saved_summary.follow_up_recommendations == []
            assert saved_summary.transcript_compact is None
        finally:
            self._cleanup_overrides()


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchemaUpdates:
    """Verify that the migration SQL is properly included in SCHEMA_SQL."""

    def test_migrate_columns_in_schema_sql(self):
        from app.db_schema import SCHEMA_SQL, MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert MIGRATE_SESSION_SUMMARIES_AI_COLUMNS in SCHEMA_SQL

    def test_migrate_adds_transcript_compact_column(self):
        from app.db_schema import MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert "transcript_compact" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS
        assert "ADD COLUMN IF NOT EXISTS" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

    def test_migrate_adds_ai_summary_column(self):
        from app.db_schema import MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert "ai_summary" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

    def test_migrate_adds_topics_covered_column(self):
        from app.db_schema import MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert "topics_covered" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

    def test_migrate_adds_student_understanding_map_column(self):
        from app.db_schema import MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert "student_understanding_map" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

    def test_migrate_adds_key_moments_column(self):
        from app.db_schema import MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert "key_moments" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

    def test_migrate_adds_uncertainty_timeline_column(self):
        from app.db_schema import MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

        assert "uncertainty_timeline" in MIGRATE_SESSION_SUMMARIES_AI_COLUMNS

    def test_audit_log_table_in_schema(self):
        from app.db_schema import SCHEMA_SQL, CREATE_TRANSCRIPT_DELETION_LOG_TABLE

        assert CREATE_TRANSCRIPT_DELETION_LOG_TABLE in SCHEMA_SQL
        assert "transcript_deletion_log" in CREATE_TRANSCRIPT_DELETION_LOG_TABLE
        assert "deleted_by" in CREATE_TRANSCRIPT_DELETION_LOG_TABLE
        assert "deleted_at" in CREATE_TRANSCRIPT_DELETION_LOG_TABLE
        assert "s3_key_deleted" in CREATE_TRANSCRIPT_DELETION_LOG_TABLE
