"""FastAPI dependency helpers for auth.

Usage:
    from app.auth.dependencies import get_current_user, get_optional_user

    @router.get("/protected")
    async def protected(user: User = Depends(get_current_user)):
        ...

    @router.get("/maybe-protected")
    async def maybe_protected(user: User | None = Depends(get_optional_user)):
        ...
"""

from __future__ import annotations

import logging
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt_utils import decode_access_token
from app.auth.models import User
logger = logging.getLogger(__name__)

# HTTPBearer extracts "Authorization: Bearer <token>"
# Both use auto_error=False so we control the exact error response (401 vs the
# default 403 that HTTPBearer raises when auto_error=True and the header is absent).
_bearer_optional = HTTPBearer(auto_error=False)
_bearer_required = HTTPBearer(auto_error=False)


def _get_store():
    """Return the configured user-store (delegates to the auth package factory)."""
    from app.auth import get_user_store

    return get_user_store()


def _resolve_user_from_credentials(
    credentials: Optional[HTTPAuthorizationCredentials],
    store,
    *,
    required: bool,
) -> Optional[User]:
    """Shared resolution logic used by both get_current_user and get_optional_user."""
    if credentials is None:
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = store.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_required),
) -> User:
    """Require a valid Bearer JWT; return the authenticated User or raise 401."""
    store = _get_store()
    user = _resolve_user_from_credentials(credentials, store, required=True)
    assert user is not None  # required=True guarantees this
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_optional),
) -> Optional[User]:
    """Return the authenticated User if a valid Bearer JWT is present, else None."""
    store = _get_store()
    return _resolve_user_from_credentials(credentials, store, required=False)
