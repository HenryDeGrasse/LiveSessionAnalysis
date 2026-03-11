"""Tests for S3TraceStore.

Tests that require a real S3/R2 bucket are skipped unless the environment
variable ``LSA_S3_BUCKET_NAME`` is set **and** valid credentials are available
via ``LSA_S3_ACCESS_KEY_ID`` / ``LSA_S3_SECRET_ACCESS_KEY``.

All other tests use a mocked boto3 client and run unconditionally.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from app.models import SessionSummary
from app.observability.s3_trace_store import S3TraceStore
from app.observability.trace_models import SessionTrace

# ---------------------------------------------------------------------------
# Skip guard for live S3 tests
# ---------------------------------------------------------------------------

_HAS_S3 = bool(
    os.environ.get("LSA_S3_BUCKET_NAME")
    and os.environ.get("LSA_S3_ACCESS_KEY_ID")
    and os.environ.get("LSA_S3_SECRET_ACCESS_KEY")
)

requires_s3 = pytest.mark.skipif(
    not _HAS_S3,
    reason="S3 credentials not set — skipping live S3/R2 tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_summary(session_id: str = "s3-s1") -> SessionSummary:
    now = datetime(2025, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    return SessionSummary(
        session_id=session_id,
        tutor_id="tutor42",
        start_time=now,
        end_time=now,
        duration_seconds=120.0,
        talk_time_ratio={"tutor": 0.7, "student": 0.3},
        avg_eye_contact={"tutor": 0.8, "student": 0.6},
        avg_energy={"tutor": 0.5, "student": 0.4},
        total_interruptions=0,
        engagement_score=80.0,
    )


def _make_trace(session_id: str = "s3-s1") -> SessionTrace:
    now = datetime(2025, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    return SessionTrace(
        session_id=session_id,
        tutor_id="tutor42",
        created_at=now,
        started_at=now,
        ended_at=now,
        duration_seconds=120.0,
        summary=_make_summary(session_id),
    )


def _make_mock_client() -> MagicMock:
    client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Unit tests (mocked boto3)
# ---------------------------------------------------------------------------


class TestS3TraceStoreUnit:
    """Tests that exercise the store logic without a real S3 endpoint."""

    def _store_with_mock(self) -> tuple[S3TraceStore, MagicMock]:
        store = S3TraceStore(
            bucket_name="test-bucket",
            endpoint_url="https://fake.r2.example.com",
            access_key_id="AKID",
            secret_access_key="SECRET",
            prefix="traces/",
        )
        mock_client = _make_mock_client()
        # Inject mock directly to bypass lazy boto3 creation
        store._S3TraceStore__client = mock_client
        return store, mock_client

    # ------------------------------------------------------------------
    # append_record / flush_ndjson
    # ------------------------------------------------------------------

    def test_append_record_buffers_lines(self):
        store, mock_client = self._store_with_mock()
        store.append_record("sess-1", {"kind": "event", "seq": 1})
        store.append_record("sess-1", {"kind": "signal", "seq": 2})

        assert "sess-1" in store._ndjson_buffer
        assert len(store._ndjson_buffer["sess-1"]) == 2
        # No S3 calls yet
        mock_client.put_object.assert_not_called()

    def test_flush_ndjson_uploads_lines_and_clears_buffer(self):
        store, mock_client = self._store_with_mock()
        store.append_record("sess-1", {"kind": "event", "seq": 1})
        store.append_record("sess-1", {"kind": "signal", "seq": 2})

        store.flush_ndjson("sess-1")

        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Key"] == "traces/sess-1.ndjson"
        assert call_kwargs["ContentType"] == "application/x-ndjson"

        body = call_kwargs["Body"].decode("utf-8")
        lines = [l for l in body.strip().splitlines() if l]
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"kind": "event", "seq": 1}
        assert json.loads(lines[1]) == {"kind": "signal", "seq": 2}

        # Buffer should be cleared
        assert "sess-1" not in store._ndjson_buffer

    def test_flush_ndjson_noop_when_no_buffer(self):
        store, mock_client = self._store_with_mock()
        store.flush_ndjson("no-such-session")
        mock_client.put_object.assert_not_called()

    # ------------------------------------------------------------------
    # save / load
    # ------------------------------------------------------------------

    def test_save_uploads_json_and_flushes_ndjson(self):
        store, mock_client = self._store_with_mock()
        trace = _make_trace("sess-2")

        # Buffer an NDJSON line before saving
        store.append_record("sess-2", {"kind": "event", "seq": 1})

        store.save(trace)

        # Should have two put_object calls: one for JSON, one for NDJSON
        assert mock_client.put_object.call_count == 2

        calls_by_key: Dict[str, Any] = {
            c.kwargs["Key"]: c.kwargs for c in mock_client.put_object.call_args_list
        }
        assert "traces/sess-2.json" in calls_by_key
        assert "traces/sess-2.ndjson" in calls_by_key

        json_body = calls_by_key["traces/sess-2.json"]["Body"].decode("utf-8")
        saved_trace = SessionTrace.model_validate_json(json_body)
        assert saved_trace.session_id == "sess-2"

        # NDJSON buffer cleared after flush
        assert "sess-2" not in store._ndjson_buffer

    def test_save_no_ndjson_when_buffer_empty(self):
        store, mock_client = self._store_with_mock()
        trace = _make_trace("sess-3")

        store.save(trace)

        # Only one put_object call (JSON only)
        assert mock_client.put_object.call_count == 1
        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Key"] == "traces/sess-3.json"

    def test_load_returns_trace_on_success(self):
        store, mock_client = self._store_with_mock()
        trace = _make_trace("sess-4")
        body_bytes = trace.model_dump_json(indent=2).encode("utf-8")

        mock_response = {"Body": MagicMock()}
        mock_response["Body"].read.return_value = body_bytes
        mock_client.get_object.return_value = mock_response

        loaded = store.load("sess-4")

        assert loaded is not None
        assert loaded.session_id == "sess-4"
        mock_client.get_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="traces/sess-4.json",
        )

    def test_load_returns_none_on_missing_object(self):
        store, mock_client = self._store_with_mock()
        mock_client.get_object.side_effect = Exception("NoSuchKey")

        result = store.load("does-not-exist")

        assert result is None

    def test_load_returns_none_on_invalid_json(self):
        store, mock_client = self._store_with_mock()
        mock_response = {"Body": MagicMock()}
        mock_response["Body"].read.return_value = b"not valid json"
        mock_client.get_object.return_value = mock_response

        result = store.load("bad-json")

        assert result is None

    def test_load_reraises_unexpected_client_errors(self):
        store, mock_client = self._store_with_mock()
        mock_client.get_object.side_effect = RuntimeError("access denied")

        with pytest.raises(RuntimeError, match="access denied"):
            store.load("sess-4")

    # ------------------------------------------------------------------
    # Key / path helpers
    # ------------------------------------------------------------------

    def test_key_sanitises_special_chars(self):
        store, _ = self._store_with_mock()
        key = store._json_key("session/with:special chars!")
        # Slashes, colons, spaces, and bangs should be replaced
        assert "/" not in key.removeprefix("traces/")
        assert ":" not in key
        assert " " not in key
        assert "!" not in key

    def test_path_returns_tempdir_path(self):
        store, _ = self._store_with_mock()
        p = store.path("sess-5")
        assert str(p).endswith("sess-5.json")

    def test_ndjson_path_returns_tempdir_path(self):
        store, _ = self._store_with_mock()
        p = store.ndjson_path("sess-5")
        assert str(p).endswith("sess-5.ndjson")

    def test_custom_prefix(self):
        store = S3TraceStore(
            bucket_name="bucket",
            prefix="evals/traces/",
        )
        store._S3TraceStore__client = _make_mock_client()
        assert store._json_key("s1") == "evals/traces/s1.json"
        assert store._ndjson_key("s1") == "evals/traces/s1.ndjson"

    def test_prefix_is_normalized_when_trailing_slash_is_missing(self):
        store = S3TraceStore(
            bucket_name="bucket",
            prefix="evals/traces",
        )
        store._S3TraceStore__client = _make_mock_client()
        assert store._json_key("s1") == "evals/traces/s1.json"
        assert store._ndjson_key("s1") == "evals/traces/s1.ndjson"

    def test_empty_prefix_writes_at_bucket_root(self):
        store = S3TraceStore(
            bucket_name="bucket",
            prefix="",
        )
        store._S3TraceStore__client = _make_mock_client()
        assert store._json_key("s1") == "s1.json"
        assert store._ndjson_key("s1") == "s1.ndjson"

    def test_multiple_sessions_have_independent_buffers(self):
        store, mock_client = self._store_with_mock()
        store.append_record("sess-A", {"kind": "a", "seq": 1})
        store.append_record("sess-B", {"kind": "b", "seq": 1})
        store.append_record("sess-A", {"kind": "a", "seq": 2})

        assert len(store._ndjson_buffer["sess-A"]) == 2
        assert len(store._ndjson_buffer["sess-B"]) == 1


# ---------------------------------------------------------------------------
# Factory and get_trace_store tests
# ---------------------------------------------------------------------------


class TestGetTraceStoreFactory:
    def test_local_backend_returns_session_trace_store(self):
        from app.observability import get_trace_store
        from app.observability.trace_store import SessionTraceStore

        with patch("app.observability.settings") as mock_settings:
            mock_settings.trace_storage_backend = "local"
            mock_settings.trace_dir = "/tmp/traces"
            result = get_trace_store()

        assert isinstance(result, SessionTraceStore)

    def test_s3_backend_returns_s3_trace_store(self):
        from app.observability import get_trace_store

        with patch("app.observability.settings") as mock_settings:
            mock_settings.trace_storage_backend = "s3"
            result = get_trace_store()

        assert isinstance(result, S3TraceStore)

    def test_unknown_backend_falls_back_to_local(self):
        from app.observability import get_trace_store
        from app.observability.trace_store import SessionTraceStore

        with patch("app.observability.settings") as mock_settings:
            mock_settings.trace_storage_backend = "unknown"
            mock_settings.trace_dir = "/tmp/traces"
            result = get_trace_store()

        assert isinstance(result, SessionTraceStore)


# ---------------------------------------------------------------------------
# Live integration tests (skipped without real credentials)
# ---------------------------------------------------------------------------


@requires_s3
class TestS3TraceStoreLive:
    """Integration tests against a real S3/R2 bucket."""

    def _make_store(self) -> S3TraceStore:
        return S3TraceStore()  # Uses settings / env vars

    def test_save_and_load_roundtrip(self):
        store = self._make_store()
        session_id = "live-test-session-001"
        trace = _make_trace(session_id)

        store.save(trace)
        loaded = store.load(session_id)

        assert loaded is not None
        assert loaded.session_id == session_id
        assert loaded.summary.engagement_score == pytest.approx(80.0)

    def test_append_and_flush_ndjson(self):
        store = self._make_store()
        session_id = "live-test-ndjson-001"

        store.append_record(session_id, {"kind": "event", "seq": 1})
        store.append_record(session_id, {"kind": "event", "seq": 2})
        store.flush_ndjson(session_id)

        # Buffer should be cleared
        assert session_id not in store._ndjson_buffer
