from __future__ import annotations

"""Unit tests for PgUserStore.

When LSA_DATABASE_URL is not set (i.e. in CI / local unit-test runs without a
real Postgres instance) the tests that require a live database are skipped.
Tests that only exercise the factory / selection logic run unconditionally.
"""

import os
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HAS_DB = bool(os.environ.get("LSA_DATABASE_URL"))

requires_db = pytest.mark.skipif(
    not _HAS_DB,
    reason="LSA_DATABASE_URL not set — skipping live Postgres tests",
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


# A representative row tuple matching _SELECT_COLS order:
# id, email, password_hash, name, role, google_id, avatar_url, is_guest,
# created_at, updated_at
_SAMPLE_ROW = (
    "user-id-1",
    "alice@example.com",
    "pbkdf2:hash",
    "Alice",
    "tutor",
    None,
    None,
    False,
    "2025-01-01T00:00:00+00:00",
    "2025-01-01T00:00:00+00:00",
)


# ---------------------------------------------------------------------------
# Factory / selection logic (no DB required)
# ---------------------------------------------------------------------------


class TestGetUserStoreFactory:
    """Tests for the get_user_store() factory in app.auth."""

    def setup_method(self):
        import app.auth as auth_pkg

        auth_pkg._reset_store()

    def teardown_method(self):
        import app.auth as auth_pkg

        auth_pkg._reset_store()

    def test_returns_sqlite_store_by_default(self):
        """With default settings (local backend, no database_url), returns UserStore."""
        from app.config import settings
        from app.auth.user_store import UserStore
        from app.auth import get_user_store

        with patch.object(settings, "storage_backend", "local"), patch.object(
            settings, "database_url", ""
        ):
            import app.auth as auth_pkg

            auth_pkg._reset_store()
            store = get_user_store()
        assert isinstance(store, UserStore)

    def test_returns_sqlite_store_when_postgres_backend_but_no_url(self):
        """When storage_backend=postgres but database_url is empty, falls back to SQLite."""
        from app.config import settings
        from app.auth.user_store import UserStore
        from app.auth import get_user_store

        with patch.object(settings, "storage_backend", "postgres"), patch.object(
            settings, "database_url", ""
        ):
            import app.auth as auth_pkg

            auth_pkg._reset_store()
            store = get_user_store()
        assert isinstance(store, UserStore)

    def test_returns_pg_store_when_postgres_backend_and_url_set(self):
        """When both storage_backend=postgres and database_url are set, returns PgUserStore."""
        from app.config import settings
        from app.auth.pg_user_store import PgUserStore
        from app.auth import get_user_store

        with patch.object(settings, "storage_backend", "postgres"), patch.object(
            settings, "database_url", "postgresql://fake/db"
        ):
            import app.auth as auth_pkg

            auth_pkg._reset_store()
            store = get_user_store()
        assert isinstance(store, PgUserStore)

    def test_singleton_returns_same_instance(self):
        """Second call to get_user_store() returns the same object."""
        from app.auth import get_user_store

        store1 = get_user_store()
        store2 = get_user_store()
        assert store1 is store2


# ---------------------------------------------------------------------------
# PgUserStore unit tests using mocked psycopg connections
# ---------------------------------------------------------------------------


class TestPgUserStoreMocked:
    """PgUserStore tests that mock out the psycopg connection layer."""

    def _store(self):
        from app.auth.pg_user_store import PgUserStore

        return PgUserStore(database_url="postgresql://fake/db")

    # -- constructor --------------------------------------------------------

    def test_raises_without_database_url(self):
        from app.auth.pg_user_store import PgUserStore

        with pytest.raises(ValueError, match="database URL"):
            PgUserStore(database_url="")

    # -- get_by_id ----------------------------------------------------------

    def test_get_by_id_returns_user_when_found(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[_SAMPLE_ROW])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_by_id("user-id-1")

        assert result is not None
        assert result.id == "user-id-1"
        assert result.email == "alice@example.com"
        assert result.name == "Alice"
        assert result.role == "tutor"

    def test_get_by_id_returns_none_when_not_found(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[])
        mock_cur.fetchone.return_value = None
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_by_id("nonexistent")

        assert result is None

    # -- get_by_email -------------------------------------------------------

    def test_get_by_email_normalises_email(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[_SAMPLE_ROW])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_by_email("ALICE@EXAMPLE.COM")

        assert result is not None
        # Verify the normalised email was passed to the query
        params = mock_cur.execute.call_args[0][1]
        assert params == ("alice@example.com",)

    def test_get_by_email_returns_password_hash(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[_SAMPLE_ROW])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_by_email("alice@example.com")

        assert result is not None
        assert result.password_hash == "pbkdf2:hash"

    # -- get_password_hash --------------------------------------------------

    def test_get_password_hash_returns_hash_when_found(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[("pbkdf2:hash",)])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_password_hash("alice@example.com")

        assert result == "pbkdf2:hash"

    def test_get_password_hash_returns_none_when_not_found(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[])
        mock_cur.fetchone.return_value = None
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_password_hash("nobody@example.com")

        assert result is None

    # -- get_by_google_id ---------------------------------------------------

    def test_get_by_google_id_returns_user(self):
        google_row = (
            "user-id-2",
            "bob@example.com",
            None,
            "Bob",
            "tutor",
            "google-sub-123",
            "https://avatar.example.com/bob.png",
            False,
            "2025-01-02T00:00:00+00:00",
            "2025-01-02T00:00:00+00:00",
        )
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[google_row])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.get_by_google_id("google-sub-123")

        assert result is not None
        assert result.google_id == "google-sub-123"
        assert result.avatar_url == "https://avatar.example.com/bob.png"

    # -- create_user --------------------------------------------------------

    def test_create_user_executes_insert(self):
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            user = store.create_user(
                email="carol@example.com",
                password_hash="hashed",
                name="Carol",
                role="tutor",
            )

        mock_cur.execute.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO users" in sql
        mock_conn.commit.assert_called_once()

        assert user.email == "carol@example.com"
        assert user.name == "Carol"
        assert user.role == "tutor"
        assert user.id  # generated

    def test_create_user_normalises_email(self):
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            user = store.create_user(
                email="CAROL@EXAMPLE.COM",
                name="Carol",
            )

        assert user.email == "carol@example.com"

    def test_create_user_raises_on_empty_name(self):
        store = self._store()
        with pytest.raises(ValueError, match="name must not be empty"):
            store.create_user(name="")

    def test_create_user_raises_on_invalid_role(self):
        store = self._store()
        with pytest.raises(ValueError, match="role must be one of"):
            store.create_user(name="Dave", role="superuser")

    def test_create_user_raises_on_duplicate(self):
        store = self._store()
        mock_cur = _make_mock_cursor()
        mock_conn = _make_mock_conn(mock_cur)
        mock_conn.__enter__.side_effect = Exception("UniqueViolation")

        with patch.object(store, "_connect", return_value=mock_conn):
            with pytest.raises(ValueError, match="User already exists"):
                store.create_user(email="dup@example.com", name="Dup")

    # -- update_user --------------------------------------------------------

    def test_update_user_executes_update_and_refetches(self):
        updated_row = (
            "user-id-1",
            "alice@example.com",
            "pbkdf2:hash",
            "Alice Updated",
            "tutor",
            None,
            None,
            False,
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T01:00:00+00:00",
        )
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[updated_row])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.update_user("user-id-1", name="Alice Updated")

        # UPDATE called, then SELECT (get_by_id)
        assert mock_cur.execute.call_count == 2
        update_sql = mock_cur.execute.call_args_list[0][0][0]
        assert "UPDATE users SET" in update_sql

        assert result is not None
        assert result.name == "Alice Updated"

    def test_update_user_raises_on_invalid_field(self):
        store = self._store()
        with pytest.raises(ValueError, match="not updatable"):
            store.update_user("user-id-1", secret_field="oops")

    def test_update_user_hashes_password(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[_SAMPLE_ROW])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            store.update_user("user-id-1", password="newpassword")

        update_sql = mock_cur.execute.call_args_list[0][0][0]
        params = mock_cur.execute.call_args_list[0][0][1]
        assert "password_hash" in update_sql
        # The first param should be a hashed value (not the plaintext)
        assert params[0] != "newpassword"
        assert params[0].startswith("pbkdf2") or len(params[0]) > 20

    def test_update_user_no_fields_returns_current(self):
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[_SAMPLE_ROW])
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.update_user("user-id-1")

        # Only SELECT called (get_by_id), no UPDATE
        assert mock_cur.execute.call_count == 1
        assert result is not None

    def test_update_user_raises_on_invalid_role(self):
        store = self._store()
        with pytest.raises(ValueError, match="role must be one of"):
            store.update_user("user-id-1", role="overlord")

    def test_update_user_raises_on_empty_name(self):
        store = self._store()
        with pytest.raises(ValueError, match="name must not be empty"):
            store.update_user("user-id-1", name="   ")

    # -- upsert_google_user -------------------------------------------------

    def test_upsert_google_user_updates_existing(self):
        """When user exists by google_id, profile fields are updated."""
        existing_row = (
            "user-id-2",
            "bob@example.com",
            None,
            "Bob Old",
            "tutor",
            "g-123",
            None,
            False,
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:00+00:00",
        )
        updated_row = (
            "user-id-2",
            "bob@example.com",
            None,
            "Bob New",
            "tutor",
            "g-123",
            "https://avatar.example/bob.jpg",
            False,
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T01:00:00+00:00",
        )
        store = self._store()

        # get_by_google_id returns existing; update_user get_by_id returns updated
        call_count = 0
        rows_seq = [[existing_row], [updated_row], [updated_row]]

        def mock_connect():
            nonlocal call_count
            idx = min(call_count, len(rows_seq) - 1)
            cur = _make_mock_cursor(rows=rows_seq[idx])
            conn = _make_mock_conn(cur)
            call_count += 1
            return conn

        with patch.object(store, "_connect", side_effect=mock_connect):
            result = store.upsert_google_user(
                google_id="g-123",
                email="bob@example.com",
                name="Bob New",
                avatar_url="https://avatar.example/bob.jpg",
            )

        assert result.name == "Bob New"

    def test_upsert_google_user_creates_new_when_not_found(self):
        """When no existing user, a new one is created."""
        store = self._store()
        mock_cur = _make_mock_cursor(rows=[])
        mock_cur.fetchone.return_value = None
        mock_conn = _make_mock_conn(mock_cur)

        with patch.object(store, "_connect", return_value=mock_conn):
            result = store.upsert_google_user(
                google_id="g-new",
                email="new@example.com",
                name="New User",
            )

        assert result.email == "new@example.com"
        assert result.google_id == "g-new"

    # -- row-to-user conversion ---------------------------------------------

    def test_row_to_user_handles_datetime_created_at(self):
        """Postgres TIMESTAMPTZ columns returned as datetime are converted to ISO strings."""
        from datetime import datetime, timezone
        from app.auth.pg_user_store import _row_to_user

        dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        row = (
            "uid",
            "x@example.com",
            None,
            "X",
            "tutor",
            None,
            None,
            False,
            dt,
            dt,
        )
        user = _row_to_user(row)
        assert isinstance(user.created_at, str)
        assert "2025" in user.created_at


# ---------------------------------------------------------------------------
# Live Postgres tests (skipped unless LSA_DATABASE_URL is set)
# ---------------------------------------------------------------------------


@requires_db
class TestPgUserStoreLive:
    """Integration tests against a real Postgres instance.

    These tests require LSA_DATABASE_URL to point to a running database with
    the users table already created (run the schema init script first).
    """

    @pytest.fixture(autouse=True)
    def store(self):
        from app.auth.pg_user_store import PgUserStore

        return PgUserStore()

    @pytest.fixture(autouse=True)
    def cleanup(self, store):
        yield
        # Best-effort cleanup of users created during tests
        for email in (
            "live-alice@example.com",
            "live-bob@example.com",
            "live-carol@example.com",
        ):
            user = store.get_by_email(email)
            if user:
                try:
                    conn = store._connect()
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM users WHERE id = %s", (user.id,))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

    def test_create_and_get_by_id(self, store):
        user = store.create_user(
            email="live-alice@example.com",
            name="Live Alice",
            role="tutor",
        )
        fetched = store.get_by_id(user.id)
        assert fetched is not None
        assert fetched.email == "live-alice@example.com"
        assert fetched.name == "Live Alice"

    def test_create_and_get_by_email(self, store):
        store.create_user(email="live-alice@example.com", name="Live Alice")
        fetched = store.get_by_email("LIVE-ALICE@EXAMPLE.COM")
        assert fetched is not None
        assert fetched.email == "live-alice@example.com"

    def test_get_by_id_nonexistent_returns_none(self, store):
        assert store.get_by_id("nonexistent-id-xyz") is None

    def test_get_by_email_nonexistent_returns_none(self, store):
        assert store.get_by_email("nobody@live.example.com") is None

    def test_create_duplicate_raises_value_error(self, store):
        store.create_user(email="live-alice@example.com", name="Live Alice")
        with pytest.raises(ValueError, match="User already exists"):
            store.create_user(email="live-alice@example.com", name="Live Alice 2")

    def test_update_user_name(self, store):
        user = store.create_user(email="live-alice@example.com", name="Live Alice")
        updated = store.update_user(user.id, name="Alice Updated")
        assert updated is not None
        assert updated.name == "Alice Updated"

    def test_get_password_hash_roundtrip(self, store):
        from app.auth.password import hash_password

        ph = hash_password("s3cr3t!")
        store.create_user(
            email="live-alice@example.com",
            name="Live Alice",
            password_hash=ph,
        )
        retrieved = store.get_password_hash("live-alice@example.com")
        assert retrieved == ph

    def test_upsert_google_user_creates_and_updates(self, store):
        user = store.upsert_google_user(
            google_id="live-g-1",
            email="live-bob@example.com",
            name="Live Bob",
        )
        assert user.email == "live-bob@example.com"

        # Upsert again with updated name
        updated = store.upsert_google_user(
            google_id="live-g-1",
            email="live-bob@example.com",
            name="Live Bob Updated",
        )
        assert updated.name == "Live Bob Updated"
        assert updated.id == user.id
