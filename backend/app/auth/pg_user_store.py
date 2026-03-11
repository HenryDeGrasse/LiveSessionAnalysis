from __future__ import annotations

"""Postgres-backed user store implementation.

Stores :class:`~app.auth.models.User` objects in a ``users`` table.  The
schema mirrors the existing SQLite store so that both backends share the same
model and the same public interface.

Table DDL (created by the schema initialisation script):

    CREATE TABLE IF NOT EXISTS users (
        id            TEXT PRIMARY KEY,
        email         TEXT UNIQUE,
        password_hash TEXT,
        name          TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'tutor',
        google_id     TEXT UNIQUE,
        avatar_url    TEXT,
        is_guest      BOOLEAN DEFAULT FALSE,
        created_at    TIMESTAMPTZ NOT NULL,
        updated_at    TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_users_email     ON users(email);
    CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);
"""

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.auth.models import User
from app.auth.password import hash_password
from app.config import settings

logger = logging.getLogger(__name__)

_VALID_ROLES = frozenset({"tutor", "student", "admin"})


def _new_id() -> str:
    """Return a URL-safe random ID (~22 chars, 132 bits of entropy)."""
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_user(row: tuple) -> User:
    """Map a psycopg row tuple to a :class:`User`.

    Expected column order (matches every SELECT used below):
    id, email, password_hash, name, role, google_id, avatar_url, is_guest,
    created_at, updated_at
    """
    (
        user_id,
        email,
        password_hash,
        name,
        role,
        google_id,
        avatar_url,
        is_guest,
        created_at,
        updated_at,
    ) = row

    # Postgres TIMESTAMPTZ columns come back as datetime objects; normalise to
    # ISO string so both backends return the same User.created_at type.
    if isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    if isinstance(updated_at, datetime):
        updated_at = updated_at.isoformat()

    return User(
        id=user_id,
        email=email,
        password_hash=password_hash,
        name=name,
        role=role,
        google_id=google_id,
        avatar_url=avatar_url,
        is_guest=bool(is_guest),
        created_at=created_at,
        updated_at=updated_at,
    )


_SELECT_COLS = (
    "id, email, password_hash, name, role, google_id, avatar_url, "
    "is_guest, created_at, updated_at"
)


class PgUserStore:
    """Postgres-backed user persistence.

    Uses ``psycopg`` (v3 synchronous API) as a drop-in replacement for the
    SQLite-based :class:`~app.auth.user_store.UserStore`.

    A connection-per-call strategy is used (matching PgSessionStore) so no
    event loop or pool is required at construction time.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._dsn = database_url or settings.database_url
        if not self._dsn:
            raise ValueError(
                "PgUserStore requires a database URL "
                "(settings.database_url / LSA_DATABASE_URL env var)"
            )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _connect(self):
        """Open and return a new psycopg connection."""
        import psycopg  # type: ignore[import]

        return psycopg.connect(self._dsn)

    # ------------------------------------------------------------------ #
    # Public interface (mirrors UserStore)                                 #
    # ------------------------------------------------------------------ #

    def create_user(
        self,
        email: Optional[str] = None,
        password_hash: Optional[str] = None,
        name: str = "",
        role: str = "tutor",
        google_id: Optional[str] = None,
        is_guest: bool = False,
        *,
        avatar_url: Optional[str] = None,
    ) -> User:
        """Create and return a new user.

        ``password_hash`` must already be hashed via
        ``app.auth.password.hash_password()``.

        Raises :class:`ValueError` if a user with the same email or
        ``google_id`` already exists, if ``name`` is empty, or if ``role``
        is not valid.
        """
        if not name or not name.strip():
            raise ValueError("name must not be empty")
        if role not in _VALID_ROLES:
            raise ValueError(
                f"role must be one of {sorted(_VALID_ROLES)!r}, got {role!r}"
            )

        user_id = _new_id()
        now = _now_iso()
        normalised_email = email.strip().lower() if email else None

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO users
                            ({_SELECT_COLS})
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            user_id,
                            normalised_email,
                            password_hash,
                            name,
                            role,
                            google_id,
                            avatar_url,
                            is_guest,
                            now,
                            now,
                        ),
                    )
                conn.commit()
        except Exception as exc:
            # psycopg raises psycopg.errors.UniqueViolation (a subclass of
            # Exception); catch broadly and re-raise as ValueError to match
            # the SQLite UserStore contract.
            raise ValueError(f"User already exists: {exc}") from exc

        return User(
            id=user_id,
            email=normalised_email,
            name=name,
            role=role,  # type: ignore[arg-type]
            google_id=google_id,
            avatar_url=avatar_url,
            is_guest=is_guest,
            created_at=now,
            updated_at=now,
        )

    def get_by_id(self, user_id: str) -> Optional[User]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_SELECT_COLS} FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[User]:
        """Return the User for *email* including the stored ``password_hash``."""
        normalised = email.strip().lower()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_SELECT_COLS} FROM users WHERE email = %s",
                    (normalised,),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_password_hash(self, email: str) -> Optional[str]:
        """Return the stored password hash for *email*, or ``None``."""
        normalised = email.strip().lower()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM users WHERE email = %s",
                    (normalised,),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def get_by_google_id(self, google_id: str) -> Optional[User]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_SELECT_COLS} FROM users WHERE google_id = %s",
                    (google_id,),
                )
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def upsert_google_user(
        self,
        google_id: str,
        email: str,
        name: str,
        avatar_url: Optional[str] = None,
    ) -> User:
        """Insert or update the user identified by *google_id*.

        Mirrors the same three-step logic as the SQLite store:
        1. Update if already linked by ``google_id``.
        2. Link an existing email-only account.
        3. Create new user.
        """
        normalised_email = email.strip().lower()

        existing = self.get_by_google_id(google_id)
        if existing is not None:
            updates: dict[str, object] = {}
            if existing.name != name:
                updates["name"] = name
            if existing.email != normalised_email:
                updates["email"] = normalised_email
            if avatar_url and existing.avatar_url != avatar_url:
                updates["avatar_url"] = avatar_url
            if updates:
                updated = self.update_user(existing.id, **updates)
                return updated or existing
            return existing

        email_user = self.get_by_email(normalised_email)
        if email_user is not None:
            return (
                self.update_user(
                    email_user.id,
                    google_id=google_id,
                    name=name,
                    avatar_url=avatar_url or email_user.avatar_url,
                )
                or email_user
            )

        return self.create_user(
            name=name,
            role="tutor",
            email=normalised_email,
            google_id=google_id,
            avatar_url=avatar_url,
        )

    def update_user(self, user_id: str, **fields: object) -> Optional[User]:
        """Update arbitrary fields for *user_id* and return the updated User.

        Allowed fields: email, name, role, google_id, avatar_url, is_guest,
        password (will be hashed automatically).
        """
        allowed = {
            "email",
            "name",
            "role",
            "google_id",
            "avatar_url",
            "is_guest",
            "password",
        }
        updates: dict[str, object] = {}
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(
                    f"Field '{key}' is not updatable via update_user"
                )
            if key == "password":
                updates["password_hash"] = hash_password(str(value))
            elif key == "email" and isinstance(value, str):
                updates["email"] = value.strip().lower()
            elif key == "role":
                if value not in _VALID_ROLES:
                    raise ValueError(
                        f"role must be one of {sorted(_VALID_ROLES)!r}, got {value!r}"
                    )
                updates["role"] = value
            elif key == "name":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("name must not be empty or whitespace-only")
                updates["name"] = value
            else:
                updates[key] = value

        if not updates:
            return self.get_by_id(user_id)

        now = _now_iso()
        updates["updated_at"] = now
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + [user_id]

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE users SET {set_clause} WHERE id = %s",  # noqa: S608
                        values,
                    )
                conn.commit()
        except Exception as exc:
            raise ValueError(f"Cannot update user: {exc}") from exc

        return self.get_by_id(user_id)
