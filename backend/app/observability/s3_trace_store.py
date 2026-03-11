"""S3/R2-compatible trace store implementation.

Implements the same interface as :class:`SessionTraceStore` but writes trace
artifacts to an S3-compatible object storage service (e.g. Cloudflare R2).

Design notes
------------
* ``append_record()`` buffers NDJSON lines in memory rather than writing
  incrementally to S3.  Object-storage PUT operations are not append-friendly,
  so we accumulate lines and flush them to a single object on ``save()`` or on
  an explicit ``flush_ndjson()`` call.
* ``save()`` uploads the JSON trace and, if any buffered NDJSON lines exist,
  flushes them to a separate ``.ndjson`` object as well.
* The local ``path()`` / ``ndjson_path()`` methods are not meaningful for S3
  storage but are retained for interface compatibility; they return ``Path``
  objects pointing into a system temp directory.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings
from .trace_models import SessionTrace


class S3TraceStore:
    """Persist trace artifacts to S3-compatible object storage (e.g. Cloudflare R2)."""

    def __init__(
        self,
        *,
        bucket_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        prefix: Optional[str] = None,
        region_name: str = "auto",
    ) -> None:
        # Allow explicit constructor overrides for testing; fall back to settings.
        self._bucket = bucket_name or settings.s3_bucket_name
        self._endpoint = endpoint_url or settings.s3_endpoint_url or None
        configured_prefix = prefix if prefix is not None else settings.s3_trace_prefix
        self._prefix = self._normalize_prefix(configured_prefix)
        self._access_key_id = access_key_id or settings.s3_access_key_id or None
        self._secret_access_key = secret_access_key or settings.s3_secret_access_key or None
        self._region = region_name

        # NDJSON buffer: session_id -> list of JSON lines
        self._ndjson_buffer: Dict[str, List[str]] = {}

        # Lazy boto3 client — created on first use so that importing this
        # module does not hard-require boto3 or valid credentials.
        self.__client: Any = None

    # ------------------------------------------------------------------
    # boto3 client (lazy)
    # ------------------------------------------------------------------

    @property
    def _client(self) -> Any:
        if self.__client is None:
            import boto3  # type: ignore[import]

            kwargs: Dict[str, Any] = {
                "service_name": "s3",
                "region_name": self._region,
            }
            if self._endpoint:
                kwargs["endpoint_url"] = self._endpoint
            if self._access_key_id:
                kwargs["aws_access_key_id"] = self._access_key_id
            if self._secret_access_key:
                kwargs["aws_secret_access_key"] = self._secret_access_key

            self.__client = boto3.client(**kwargs)
        return self.__client

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _safe_session_id(self, session_id: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)

    def _normalize_prefix(self, prefix: str) -> str:
        normalized = prefix.strip("/")
        if not normalized:
            return ""
        return f"{normalized}/"

    def _json_key(self, session_id: str) -> str:
        return f"{self._prefix}{self._safe_session_id(session_id)}.json"

    def _ndjson_key(self, session_id: str) -> str:
        return f"{self._prefix}{self._safe_session_id(session_id)}.ndjson"

    # ------------------------------------------------------------------
    # Interface-compat path methods (return temp-dir paths, not used for I/O)
    # ------------------------------------------------------------------

    def path(self, session_id: str) -> Path:
        """Return a placeholder Path for interface compatibility (not used for I/O)."""
        return Path(tempfile.gettempdir()) / f"{self._safe_session_id(session_id)}.json"

    def ndjson_path(self, session_id: str) -> Path:
        """Return a placeholder Path for interface compatibility (not used for I/O)."""
        return Path(tempfile.gettempdir()) / f"{self._safe_session_id(session_id)}.ndjson"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def append_record(self, session_id: str, record: Dict[str, Any]) -> None:
        """Buffer an NDJSON record for later upload.

        Records are flushed to S3 during :meth:`save` or by an explicit
        :meth:`flush_ndjson` call.
        """
        line = json.dumps(record, sort_keys=True)
        self._ndjson_buffer.setdefault(session_id, []).append(line)

    def flush_ndjson(self, session_id: str) -> None:
        """Upload any buffered NDJSON lines to S3 and clear the buffer.

        If there are no buffered lines this is a no-op.
        """
        lines = self._ndjson_buffer.get(session_id)
        if not lines:
            return
        body = "\n".join(lines) + "\n"
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._ndjson_key(session_id),
            Body=body.encode("utf-8"),
            ContentType="application/x-ndjson",
        )
        self._ndjson_buffer.pop(session_id, None)

    def save(self, trace: SessionTrace) -> None:
        """Upload the serialised trace JSON to S3 and flush any NDJSON buffer."""
        body = trace.model_dump_json(indent=2).encode("utf-8")
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._json_key(trace.session_id),
            Body=body,
            ContentType="application/json",
        )
        self.flush_ndjson(trace.session_id)

    def _is_missing_object_error(self, exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            error = response.get("Error")
            if isinstance(error, dict):
                code = str(error.get("Code", ""))
                if code in {"NoSuchKey", "404", "NotFound"}:
                    return True
        return any(token in str(exc) for token in ("NoSuchKey", "404", "NotFound"))

    def load(self, session_id: str) -> Optional[SessionTrace]:
        """Download and deserialise a trace from S3.

        Returns ``None`` if the object does not exist or cannot be parsed.
        Unexpected transport/auth errors are re-raised so production issues are
        visible instead of being silently mistaken for a missing trace.
        """
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=self._json_key(session_id),
            )
            body = response["Body"].read().decode("utf-8")
            return SessionTrace.model_validate_json(body)
        except Exception as exc:
            if self._is_missing_object_error(exc):
                return None
            if isinstance(exc, (ValueError, TypeError)):
                return None
            raise
