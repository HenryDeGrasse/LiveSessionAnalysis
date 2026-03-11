"""SQLite-backed user store.

Thread-safety: each call opens and closes its own connection, or the caller
can use the context manager for a batch.  SQLite with WAL mode handles
concurrent readers/writers at pilot scale.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, Optional

from app.auth.models import User
from app.auth.password import hash_password

# nanoid-like random IDs using the standard library only
import os
import base64


def _new_id() -> str:
    """Return a URL-safe random ID (~22 chars, 132 bits of entropy)."""
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    email        TEXT UNIQUE,
    password_hash TEXT,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'tutor',
    google_id    TEXT UNIQUE,
    avatar_url   TEXT,
    is_guest     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
)
"""


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        role=row["role"],
        google_id=row["google_id"],
        avatar_url=row["avatar_url"],
        is_guest=bool(row["is_guest"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        password_hash=row["password_hash"],
    )


class UserStore:
    """Provides CRUD operations for users backed by a SQLite database."""

    def __init__(self, db_path: str = "data/auth.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        import os as _os
        _os.makedirs(_os.path.dirname(self._db_path) if _os.path.dirname(self._db_path) else ".", exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_USERS_TABLE)
            conn.commit()

    # ── Public CRUD ───────────────────────────────────────────────────────

    _VALID_ROLES = frozenset({"tutor", "student", "admin"})

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

        Positional argument order matches the step spec:
            create_user(email, password_hash, name, role, google_id, is_guest)

        ``password_hash`` must be a pre-hashed value produced by
        ``app.auth.password.hash_password()``.  Callers are responsible for
        hashing the plaintext password before calling this method.

        ``avatar_url`` is keyword-only and not part of the core positional
        contract (use ``update_user`` to set it separately if needed).

        Raises ``ValueError`` if a user with the same email or google_id
        already exists, if ``name`` is empty, or if ``role`` is not one of
        'tutor', 'student', or 'admin'.
        """
        if not name or not name.strip():
            raise ValueError("name must not be empty")
        if role not in self._VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(self._VALID_ROLES)!r}, got {role!r}")
        user_id = _new_id()
        now = _now_iso()
        normalised_email = email.strip().lower() if email else None

        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO users
                            (id, email, password_hash, name, role, google_id,
                             avatar_url, is_guest, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            normalised_email,
                            password_hash,
                            name,
                            role,
                            google_id,
                            avatar_url,
                            int(is_guest),
                            now,
                            now,
                        ),
                    )
                    conn.commit()
            except sqlite3.IntegrityError as exc:
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
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[User]:
        """Return the User for *email*, including the stored ``password_hash``.

        The hash is stored on ``User.password_hash`` (excluded from API
        serialisation) so the login flow can call this single method and pass
        the result to ``verify_password`` without a second query.
        """
        normalised = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (normalised,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def get_password_hash(self, email: str) -> Optional[str]:
        """Return the stored password hash for *email*, or None."""
        normalised = email.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE email = ?", (normalised,)
            ).fetchone()
        return row["password_hash"] if row else None

    def get_by_google_id(self, google_id: str) -> Optional[User]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE google_id = ?", (google_id,)
            ).fetchone()
        return _row_to_user(row) if row else None

    def upsert_google_user(
        self,
        google_id: str,
        email: str,
        name: str,
        avatar_url: Optional[str] = None,
    ) -> User:
        """Insert or update the user identified by *google_id*.

        - If a user with this ``google_id`` already exists their ``name``,
          ``email``, and ``avatar_url`` are refreshed from the latest Google
          profile data so profiles don't go stale after renames or avatar
          changes.
        - If a user with the same email exists but no ``google_id``, the
          Google identity is linked to that account.
        - Otherwise a new user is created.
        """
        normalised_email = email.strip().lower()

        # 1. Try by google_id — update profile fields from Google each time
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

        # 2. Try to link an existing email account
        email_user = self.get_by_email(normalised_email)
        if email_user is not None:
            return self.update_user(
                email_user.id,
                google_id=google_id,
                name=name,
                avatar_url=avatar_url or email_user.avatar_url,
            ) or email_user

        # 3. Create new
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
            "email", "name", "role", "google_id", "avatar_url", "is_guest",
            "password",
        }
        updates: dict[str, object] = {}
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Field '{key}' is not updatable via update_user")
            if key == "password":
                updates["password_hash"] = hash_password(str(value))
            elif key == "email" and isinstance(value, str):
                updates["email"] = value.strip().lower()
            elif key == "role":
                if value not in self._VALID_ROLES:
                    raise ValueError(
                        f"role must be one of {sorted(self._VALID_ROLES)!r}, got {value!r}"
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
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]

        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute(
                        f"UPDATE users SET {set_clause} WHERE id = ?",  # noqa: S608
                        values,
                    )
                    conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Cannot update user: {exc}") from exc

        return self.get_by_id(user_id)
