"""Async Postgres connection pool helper.

Usage
-----
Import ``get_pool`` and call it to obtain an *asyncpg* connection pool:

    from app.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT 1")

The pool is created lazily on the first call and is reused for the lifetime
of the process.  If ``settings.database_url`` is empty the function raises
``RuntimeError`` so callers can detect misconfiguration early.

Call ``close_pool()`` on application shutdown to drain the pool gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import asyncpg  # type: ignore[import-untyped]

from app.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_pool_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Return (and lazily create) the module-level lock.

    The lock must be created inside a running event loop, so we defer
    instantiation to first use rather than module import time.
    """
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


async def get_pool() -> asyncpg.Pool:
    """Return the shared asyncpg connection pool.

    Creates the pool on the first call using ``settings.database_url``.
    Raises ``RuntimeError`` if ``database_url`` is not configured.
    """
    global _pool

    if _pool is not None:
        return _pool

    async with _get_lock():
        # Double-checked locking: another coroutine may have created the pool
        # while we were waiting for the lock.
        if _pool is not None:
            return _pool

        db_url = settings.database_url
        if not db_url:
            raise RuntimeError(
                "LSA_DATABASE_URL is not set. "
                "Configure a Postgres connection string to use the Postgres backend."
            )

        logger.info("Creating asyncpg connection pool (dsn=<redacted>)")
        _pool = await asyncpg.create_pool(
            dsn=db_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("asyncpg connection pool ready")
        return _pool


async def close_pool() -> None:
    """Gracefully close the shared connection pool.

    Safe to call even if the pool was never created (no-op in that case).
    """
    global _pool

    if _pool is None:
        return

    async with _get_lock():
        if _pool is None:
            return
        logger.info("Closing asyncpg connection pool")
        await _pool.close()
        _pool = None
        logger.info("asyncpg connection pool closed")
