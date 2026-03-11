"""JWT helpers for LSA user-level authentication.

Uses PyJWT (already a project dependency).

Token payload shape:
    {
        "sub":   "<user_id>",
        "email": "<email or null>",
        "role":  "tutor|student|admin",
        "name":  "<display name>",
        "iat":   <issued-at unix timestamp>,
        "exp":   <expiry unix timestamp>,
    }
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import settings


def create_access_token(
    user_id: str,
    email: str | None,
    role: str,
    name: str,
) -> str:
    """Return a signed JWT access token for the given user attributes."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role,
        "name": name,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify *token*, returning the payload dict.

    Raises ``jwt.ExpiredSignatureError`` if the token is expired.
    Raises ``jwt.InvalidTokenError`` (base class) for any other issue.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
