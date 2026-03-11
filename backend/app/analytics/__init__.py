from __future__ import annotations

"""Analytics package.

Provides :func:`get_session_store` which returns the appropriate
:class:`~app.analytics.session_store.SessionStore` implementation based on the
current configuration:

- When ``settings.storage_backend == 'postgres'`` **and**
  ``settings.database_url`` is set, a
  :class:`~app.analytics.pg_session_store.PgSessionStore` is returned.
- Otherwise the default file-based
  :class:`~app.analytics.session_store.SessionStore` is used (full
  backward-compatibility for local development and tests).
"""

from ..config import settings


def get_session_store():
    """Return the configured session store singleton.

    The instance is created on first call and cached for the lifetime of the
    process so that callers receive the same object regardless of how many
    times the factory is invoked.
    """
    return _get_or_create_store()


# ---------------------------------------------------------------------------
# Internal singleton cache
# ---------------------------------------------------------------------------

_store_instance = None


def _get_or_create_store():
    global _store_instance
    if _store_instance is None:
        _store_instance = _build_store()
    return _store_instance


def _build_store():
    if settings.storage_backend == "postgres" and settings.database_url:
        from .pg_session_store import PgSessionStore

        return PgSessionStore()
    from .session_store import SessionStore

    return SessionStore()


def _reset_store() -> None:
    """Reset the cached store singleton (for testing only)."""
    global _store_instance
    _store_instance = None
