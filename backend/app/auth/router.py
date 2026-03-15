"""Auth API router — /api/auth/*

Endpoints:
    POST /register     — email/password registration
    POST /login        — email/password login
    POST /google       — Google ID token exchange
    POST /guest        — anonymous guest account creation
    GET  /me           — return current user from JWT
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.auth.jwt_utils import create_access_token
from app.auth.models import (
    AuthResponse,
    GuestAuthRequest,
    GoogleAuthRequest,
    User,
    UserCreate,
    UserLogin,
)
from app.auth.password import hash_password, verify_password
from app.auth.user_store import UserStore
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def get_user_store():
    """Return the configured user-store (delegates to the auth package factory)."""
    from app.auth import get_user_store as _factory

    return _factory()


def _make_auth_response(user: User) -> AuthResponse:
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        name=user.name,
    )
    return AuthResponse(access_token=token, user=user)


# ── POST /register ────────────────────────────────────────────────────────────


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    """Register a new tutor or student with email and password."""
    password_hash = hash_password(body.password)
    try:
        user = store.create_user(
            email=body.email,
            password_hash=password_hash,
            name=body.name,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return _make_auth_response(user)


# ── POST /login ───────────────────────────────────────────────────────────────


@router.post("/login", response_model=AuthResponse)
async def login(
    body: UserLogin,
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    """Authenticate with email and password, return a JWT."""
    user = store.get_by_email(body.email)
    stored_hash = user.password_hash if user else None

    # Constant-time path: always call verify_password to avoid timing oracle
    dummy_hash = "pbkdf2_sha256:260000:" + "00" * 32 + ":" + "00" * 32
    if not verify_password(body.password, stored_hash or dummy_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if user is None or stored_hash is None:
        # Reached only when user doesn't exist (verify returned False above,
        # but we check again to satisfy the type checker and be explicit)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return _make_auth_response(user)


# ── POST /google ──────────────────────────────────────────────────────────────


@router.post("/google", response_model=AuthResponse)
async def google_auth(
    body: GoogleAuthRequest,
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    """Exchange a Google ID token for an LSA access token.

    The Google token is verified server-side using google-auth; the signature,
    expiry, and audience (client ID) are all checked.  If ``LSA_GOOGLE_CLIENT_ID``
    is not set, Google auth is disabled.
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication is not configured on this server",
        )

    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests

        id_info = google_id_token.verify_oauth2_token(
            body.google_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:
        logger.warning("Google token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token",
        ) from exc

    google_id: str = id_info["sub"]
    email: str = id_info.get("email", "")
    name: str = id_info.get("name", "") or email.split("@")[0] or "Google User"
    avatar_url: Optional[str] = id_info.get("picture")

    try:
        user = store.upsert_google_user(
            google_id=google_id,
            email=email,
            name=name,
            avatar_url=avatar_url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return _make_auth_response(user)


# ── POST /guest ───────────────────────────────────────────────────────────────


@router.post("/guest", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def guest_auth(
    body: GuestAuthRequest = GuestAuthRequest(),
    store: UserStore = Depends(get_user_store),
) -> AuthResponse:
    """Create an anonymous guest account (is_guest=True).

    The guest email is synthetic and never sent to the user.
    """
    guest_uuid = str(uuid.uuid4())
    guest_email = f"guest-{guest_uuid}@guest.local"
    display_name = body.display_name.strip() or "Guest"
    role = body.role

    user = store.create_user(
        email=guest_email,
        password_hash=None,
        name=display_name,
        role=role,
        is_guest=True,
    )
    return _make_auth_response(user)


# ── GET /me ───────────────────────────────────────────────────────────────────


@router.get("/me", response_model=User)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's profile."""
    return current_user
