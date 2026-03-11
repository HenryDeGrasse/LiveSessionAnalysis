"""Privacy-safe local observability helpers for session tracing."""
from __future__ import annotations

from typing import Union

from ..config import settings
from .trace_store import SessionTraceStore
from .s3_trace_store import S3TraceStore

TraceStore = Union[SessionTraceStore, S3TraceStore]


def get_trace_store() -> TraceStore:
    """Return the configured trace store based on ``LSA_TRACE_STORAGE_BACKEND``.

    * ``"local"`` (default) — :class:`SessionTraceStore` writing to the local
      file-system path defined by ``LSA_TRACE_DIR``.
    * ``"s3"`` — :class:`S3TraceStore` writing to an S3-compatible object store
      (e.g. Cloudflare R2) configured via the ``LSA_S3_*`` environment variables.
    """
    if settings.trace_storage_backend == "s3":
        return S3TraceStore()
    return SessionTraceStore()
