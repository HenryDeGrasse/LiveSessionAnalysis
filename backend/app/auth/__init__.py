from __future__ import annotations

"""Auth package.

Provides :func:`get_user_store` which returns the appropriate user-store
implementation based on the current configuration:

- When ``settings.storage_backend == 'postgres'`` **and**
  ``settings.database_url`` is set, a
  :class:`~app.auth.pg_user_store.PgUserStore` is returned.
- Otherwise the default SQLite-backed
  :class:`~app.auth.user_store.UserStore` is used (full backward-compatibility
  for local development and tests).
"""

from ..config import settings


def get_user_store():
    """Return the configured user-store singleton.

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
        from .pg_user_store import PgUserStore

        return PgUserStore()
    from .user_store import UserStore

    return UserStore(db_path=settings.auth_db_path)


def _reset_store() -> None:
    """Reset the cached store singleton (for testing only)."""
    global _store_instance
    _store_instance = None
