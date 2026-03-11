"""Tests for GET /health (liveness) and GET /health/ready (readiness) endpoints.

The liveness probe must:
- Always return 200 quickly (no I/O).
- Include storage_backend, trace_storage, livekit_configured, sentry_enabled,
  db_configured, and the cached db_connected value.

The readiness probe must:
- Return 200 with db_connected=null when database_url is not set (local mode).
- Return 200 with db_connected=true when Postgres is reachable.
- Return 503 with db_connected=false when Postgres is configured but unreachable.
- Include the same status fields as the liveness probe.
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# asyncpg stub
#
# asyncpg is listed in requirements.txt but may not be installed in the test
# environment (e.g. CI without Postgres dev libs).  Inject a lightweight stub
# into sys.modules *before* any app code that imports it is loaded so that the
# `import asyncpg` inside app/db.py does not raise ModuleNotFoundError.
# ---------------------------------------------------------------------------
if "asyncpg" not in sys.modules:
    _asyncpg_stub = MagicMock()
    sys.modules["asyncpg"] = _asyncpg_stub

from app.config import settings
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /health — liveness probe
# ---------------------------------------------------------------------------


class TestHealthLiveness:
    def test_returns_200(self):
        c = _client()
        resp = c.get("/health")
        assert resp.status_code == 200

    def test_status_is_ok(self):
        c = _client()
        data = c.get("/health").json()
        assert data["status"] == "ok"

    def test_contains_required_fields(self):
        c = _client()
        data = c.get("/health").json()
        for field in (
            "status",
            "mediapipe_loaded",
            "storage_backend",
            "trace_storage",
            "livekit_configured",
            "sentry_enabled",
            "db_configured",
            "db_connected",
        ):
            assert field in data, f"Missing field: {field}"

    def test_storage_backend_reflects_settings(self):
        original = settings.storage_backend
        settings.storage_backend = "postgres"
        try:
            data = _client().get("/health").json()
            assert data["storage_backend"] == "postgres"
        finally:
            settings.storage_backend = original

    def test_trace_storage_reflects_settings(self):
        original = settings.trace_storage_backend
        settings.trace_storage_backend = "s3"
        try:
            data = _client().get("/health").json()
            assert data["trace_storage"] == "s3"
        finally:
            settings.trace_storage_backend = original

    def test_livekit_configured_false_when_not_set(self):
        original_url = settings.livekit_url
        original_key = settings.livekit_api_key
        original_secret = settings.livekit_api_secret
        settings.livekit_url = ""
        settings.livekit_api_key = ""
        settings.livekit_api_secret = ""
        try:
            data = _client().get("/health").json()
            assert data["livekit_configured"] is False
        finally:
            settings.livekit_url = original_url
            settings.livekit_api_key = original_key
            settings.livekit_api_secret = original_secret

    def test_livekit_configured_true_when_all_set(self):
        original_url = settings.livekit_url
        original_key = settings.livekit_api_key
        original_secret = settings.livekit_api_secret
        settings.livekit_url = "wss://livekit.example.com"
        settings.livekit_api_key = "APIKEY"
        settings.livekit_api_secret = "APISECRET"
        try:
            data = _client().get("/health").json()
            assert data["livekit_configured"] is True
        finally:
            settings.livekit_url = original_url
            settings.livekit_api_key = original_key
            settings.livekit_api_secret = original_secret

    def test_livekit_configured_false_when_partially_set(self):
        original_url = settings.livekit_url
        original_key = settings.livekit_api_key
        original_secret = settings.livekit_api_secret
        settings.livekit_url = "wss://livekit.example.com"
        settings.livekit_api_key = "APIKEY"
        settings.livekit_api_secret = ""  # missing secret
        try:
            data = _client().get("/health").json()
            assert data["livekit_configured"] is False
        finally:
            settings.livekit_url = original_url
            settings.livekit_api_key = original_key
            settings.livekit_api_secret = original_secret

    def test_sentry_enabled_false_when_dsn_empty(self):
        original = settings.sentry_dsn
        settings.sentry_dsn = ""
        try:
            data = _client().get("/health").json()
            assert data["sentry_enabled"] is False
        finally:
            settings.sentry_dsn = original

    def test_sentry_enabled_true_when_dsn_set(self):
        original = settings.sentry_dsn
        settings.sentry_dsn = "https://key@sentry.io/123"
        try:
            data = _client().get("/health").json()
            assert data["sentry_enabled"] is True
        finally:
            settings.sentry_dsn = original

    def test_db_configured_false_when_database_url_empty(self):
        original = settings.database_url
        settings.database_url = ""
        try:
            data = _client().get("/health").json()
            assert data["db_configured"] is False
        finally:
            settings.database_url = original

    def test_db_configured_true_when_database_url_set(self):
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@localhost:5432/mydb"
        try:
            data = _client().get("/health").json()
            assert data["db_configured"] is True
        finally:
            settings.database_url = original

    def test_db_connected_is_null_before_ready_check_runs(self):
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@localhost:5432/mydb"
        try:
            if hasattr(app.state, "db_connected"):
                app.state.db_connected = None
            data = _client().get("/health").json()
            assert data["db_connected"] is None
        finally:
            settings.database_url = original
            if hasattr(app.state, "db_connected"):
                app.state.db_connected = None

    def test_does_not_hit_database(self):
        """Liveness probe must not perform any DB I/O."""
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@unreachable-host:5432/db"
        try:
            with patch("app.db.get_pool", side_effect=RuntimeError("should not be called")):
                resp = _client().get("/health")
            # Must still return 200 — no DB call attempted
            assert resp.status_code == 200
        finally:
            settings.database_url = original


# ---------------------------------------------------------------------------
# GET /health/ready — readiness probe
# ---------------------------------------------------------------------------


class TestHealthReady:
    def test_returns_200_in_local_mode(self):
        """When database_url is unset, the check should pass with 200."""
        original = settings.database_url
        settings.database_url = ""
        try:
            resp = _client().get("/health/ready")
            assert resp.status_code == 200
        finally:
            settings.database_url = original

    def test_db_connected_is_null_in_local_mode(self):
        original = settings.database_url
        settings.database_url = ""
        try:
            data = _client().get("/health/ready").json()
            assert data["db_connected"] is None
        finally:
            settings.database_url = original

    def test_status_ok_in_local_mode(self):
        original = settings.database_url
        settings.database_url = ""
        try:
            data = _client().get("/health/ready").json()
            assert data["status"] == "ok"
        finally:
            settings.database_url = original

    def test_contains_required_fields(self):
        original = settings.database_url
        settings.database_url = ""
        try:
            data = _client().get("/health/ready").json()
            for field in (
                "status",
                "mediapipe_loaded",
                "db_connected",
                "db_configured",
                "storage_backend",
                "trace_storage",
                "livekit_configured",
                "sentry_enabled",
            ):
                assert field in data, f"Missing field: {field}"
        finally:
            settings.database_url = original

    def test_returns_200_when_postgres_reachable(self):
        """Simulate a healthy Postgres connection via a mocked pool."""
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@localhost:5432/mydb"
        try:
            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)

            mock_pool = MagicMock()
            mock_pool.acquire = MagicMock(return_value=mock_conn)

            with patch("app.db.get_pool", new=AsyncMock(return_value=mock_pool)):
                resp = _client().get("/health/ready")
            assert resp.status_code == 200
            assert resp.json()["db_connected"] is True
            assert resp.json()["status"] == "ok"
        finally:
            settings.database_url = original

    def test_returns_503_when_postgres_unreachable(self):
        """When Postgres is configured but unreachable, readiness should be 503."""
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@unreachable:5432/db"
        try:
            with patch(
                "app.db.get_pool",
                new=AsyncMock(side_effect=Exception("connection refused")),
            ):
                resp = _client().get("/health/ready")
            assert resp.status_code == 503
            data = resp.json()
            assert data["db_connected"] is False
            assert data["status"] == "degraded"
        finally:
            settings.database_url = original

    def test_ready_check_updates_cached_health_db_status(self):
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@localhost:5432/mydb"
        try:
            app.state.db_connected = None

            mock_conn = AsyncMock()
            mock_conn.fetchval = AsyncMock(return_value=1)
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=False)

            mock_pool = MagicMock()
            mock_pool.acquire = MagicMock(return_value=mock_conn)

            with patch("app.db.get_pool", new=AsyncMock(return_value=mock_pool)):
                ready_resp = _client().get("/health/ready")

            assert ready_resp.status_code == 200

            health_resp = _client().get("/health")
            assert health_resp.status_code == 200
            assert health_resp.json()["db_connected"] is True
        finally:
            settings.database_url = original
            app.state.db_connected = None

    def test_503_response_contains_all_status_fields(self):
        original = settings.database_url
        settings.database_url = "postgresql://user:pass@unreachable:5432/db"
        try:
            with patch(
                "app.db.get_pool",
                new=AsyncMock(side_effect=Exception("timeout")),
            ):
                data = _client().get("/health/ready").json()
            for field in (
                "status",
                "mediapipe_loaded",
                "db_connected",
                "db_configured",
                "storage_backend",
                "trace_storage",
                "livekit_configured",
                "sentry_enabled",
            ):
                assert field in data, f"Missing field in 503 body: {field}"
        finally:
            settings.database_url = original

    def test_storage_backend_reflects_settings(self):
        original_db = settings.database_url
        original_sb = settings.storage_backend
        settings.database_url = ""
        settings.storage_backend = "postgres"
        try:
            data = _client().get("/health/ready").json()
            assert data["storage_backend"] == "postgres"
        finally:
            settings.database_url = original_db
            settings.storage_backend = original_sb

    def test_livekit_configured_true_in_ready(self):
        original_db = settings.database_url
        original_url = settings.livekit_url
        original_key = settings.livekit_api_key
        original_secret = settings.livekit_api_secret
        settings.database_url = ""
        settings.livekit_url = "wss://livekit.example.com"
        settings.livekit_api_key = "KEY"
        settings.livekit_api_secret = "SECRET"
        try:
            data = _client().get("/health/ready").json()
            assert data["livekit_configured"] is True
        finally:
            settings.database_url = original_db
            settings.livekit_url = original_url
            settings.livekit_api_key = original_key
            settings.livekit_api_secret = original_secret
