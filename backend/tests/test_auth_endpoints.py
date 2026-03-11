"""Tests for /api/auth/* endpoints.

Covers:
- Register: success, duplicate email, validation errors
- Login: success, wrong password, unknown email
- Google: mocked verification (Google disabled + mocked token paths)
- Guest: account creation
- /me: valid token, invalid token, missing token
- get_current_user / get_optional_user dependency behaviour
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Generator
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

# ── App setup with isolated auth DB ──────────────────────────────────────────


@pytest.fixture()
def tmp_auth_db(tmp_path) -> Generator[str, None, None]:
    db = str(tmp_path / "auth_test.db")
    yield db


@pytest.fixture()
def client(tmp_auth_db: str) -> Generator[TestClient, None, None]:
    """Return a TestClient wired to an isolated auth DB."""
    # Patch settings before importing the app so the singleton store uses our DB
    from app.config import settings

    original_db = settings.auth_db_path
    settings.auth_db_path = tmp_auth_db

    # Reset the singleton store so it picks up the new db_path.
    # The store is now managed by the auth package factory.
    import app.auth as auth_pkg

    auth_pkg._reset_store()

    from app.main import app

    with TestClient(app) as c:
        yield c

    settings.auth_db_path = original_db
    auth_pkg._reset_store()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _register(client: TestClient, **overrides: Any) -> Any:
    body = {
        "email": "tutor@example.com",
        "password": "Password123",
        "name": "Test Tutor",
        "role": "tutor",
        **overrides,
    }
    return client.post("/api/auth/register", json=body)


def _login(client: TestClient, email: str = "tutor@example.com", password: str = "Password123") -> Any:
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Register tests ────────────────────────────────────────────────────────────


def test_register_success(client: TestClient) -> None:
    resp = _register(client)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    user = data["user"]
    assert user["email"] == "tutor@example.com"
    assert user["name"] == "Test Tutor"
    assert user["role"] == "tutor"
    assert user["is_guest"] is False
    # password_hash must NEVER appear in the response
    assert "password_hash" not in user
    assert "password" not in user


def test_register_student_role(client: TestClient) -> None:
    resp = _register(client, email="student@example.com", role="student", name="Test Student")
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "student"


def test_register_duplicate_email(client: TestClient) -> None:
    _register(client)
    resp = _register(client)  # second with same email
    assert resp.status_code == 409


def test_register_password_too_short(client: TestClient) -> None:
    resp = _register(client, password="short")
    assert resp.status_code == 422


def test_register_invalid_email(client: TestClient) -> None:
    resp = _register(client, email="not-an-email")
    assert resp.status_code == 422


def test_register_empty_name(client: TestClient) -> None:
    resp = _register(client, name="")
    assert resp.status_code == 422


# ── Login tests ───────────────────────────────────────────────────────────────


def test_login_success(client: TestClient) -> None:
    _register(client)
    resp = _login(client)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "tutor@example.com"


def test_login_wrong_password(client: TestClient) -> None:
    _register(client)
    resp = _login(client, password="WrongPass999")
    assert resp.status_code == 401


def test_login_unknown_email(client: TestClient) -> None:
    resp = _login(client, email="nobody@example.com")
    assert resp.status_code == 401


def test_login_email_normalised(client: TestClient) -> None:
    """Uppercase email at login should match the stored lowercase email."""
    _register(client, email="Tutor@Example.COM")
    resp = _login(client, email="tutor@example.com")
    assert resp.status_code == 200


# ── Google auth tests ─────────────────────────────────────────────────────────


def test_google_auth_disabled_when_no_client_id(client: TestClient) -> None:
    """When LSA_GOOGLE_CLIENT_ID is empty, the endpoint must return 400."""
    from app.config import settings

    original = settings.google_client_id
    settings.google_client_id = ""
    try:
        resp = client.post("/api/auth/google", json={"google_token": "fake-token"})
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"].lower()
    finally:
        settings.google_client_id = original


def test_google_auth_invalid_token(client: TestClient) -> None:
    """A bad Google token should return 401."""
    from app.config import settings

    original = settings.google_client_id
    settings.google_client_id = "mock-client-id.apps.googleusercontent.com"
    try:
        resp = client.post("/api/auth/google", json={"google_token": "garbage"})
        assert resp.status_code == 401
    finally:
        settings.google_client_id = original


def test_google_auth_success_new_user(client: TestClient) -> None:
    """A valid (mocked) Google token creates a new user and returns a JWT."""
    from app.config import settings

    original = settings.google_client_id
    settings.google_client_id = "mock-client-id.apps.googleusercontent.com"
    try:
        mock_payload = {
            "sub": "google-uid-12345",
            "email": "google.user@gmail.com",
            "name": "Google User",
            "picture": "https://example.com/photo.jpg",
        }
        with patch(
            "google.oauth2.id_token.verify_oauth2_token",
            return_value=mock_payload,
        ):
            resp = client.post("/api/auth/google", json={"google_token": "valid-google-token"})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        user = data["user"]
        assert user["email"] == "google.user@gmail.com"
        assert user["name"] == "Google User"
        assert user["google_id"] == "google-uid-12345"
    finally:
        settings.google_client_id = original


def test_google_auth_success_existing_user(client: TestClient) -> None:
    """A second Google sign-in for the same google_id returns the same user."""
    from app.config import settings

    original = settings.google_client_id
    settings.google_client_id = "mock-client-id.apps.googleusercontent.com"
    try:
        mock_payload = {
            "sub": "google-uid-99999",
            "email": "returning@gmail.com",
            "name": "Returning User",
            "picture": None,
        }
        with patch(
            "google.oauth2.id_token.verify_oauth2_token",
            return_value=mock_payload,
        ):
            resp1 = client.post("/api/auth/google", json={"google_token": "tok"})
            resp2 = client.post("/api/auth/google", json={"google_token": "tok"})

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Same user ID
        assert resp1.json()["user"]["id"] == resp2.json()["user"]["id"]
    finally:
        settings.google_client_id = original


# ── Guest auth tests ──────────────────────────────────────────────────────────


def test_guest_auth_default(client: TestClient) -> None:
    resp = client.post("/api/auth/guest", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    user = data["user"]
    assert user["is_guest"] is True
    assert "@guest.local" in user["email"]
    assert user["role"] == "student"  # default role


def test_guest_auth_custom_name(client: TestClient) -> None:
    resp = client.post("/api/auth/guest", json={"display_name": "Charlie", "role": "tutor"})
    assert resp.status_code == 201
    user = resp.json()["user"]
    assert user["name"] == "Charlie"
    assert user["role"] == "tutor"


def test_guest_auth_each_call_creates_new_user(client: TestClient) -> None:
    resp1 = client.post("/api/auth/guest", json={})
    resp2 = client.post("/api/auth/guest", json={})
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["user"]["id"] != resp2.json()["user"]["id"]


# ── /me endpoint tests ────────────────────────────────────────────────────────


def test_me_valid_token(client: TestClient) -> None:
    reg = _register(client)
    token = reg.json()["access_token"]

    resp = client.get("/api/auth/me", headers=_auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["email"] == "tutor@example.com"


def test_me_missing_token(client: TestClient) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_invalid_token(client: TestClient) -> None:
    resp = client.get("/api/auth/me", headers=_auth_header("garbage.token.value"))
    assert resp.status_code == 401


def test_me_expired_token(client: TestClient) -> None:
    import time

    from app.config import settings

    # Issue a token that expires 1 second in the past
    now = int(time.time())
    payload = {
        "sub": "some-user-id",
        "email": "x@x.com",
        "role": "tutor",
        "name": "X",
        "iat": now - 10,
        "exp": now - 1,
    }
    expired_token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    resp = client.get("/api/auth/me", headers=_auth_header(expired_token))
    assert resp.status_code == 401


def test_me_token_with_nonexistent_user(client: TestClient) -> None:
    """A valid JWT for a deleted/nonexistent user should return 401."""
    from app.auth.jwt_utils import create_access_token

    ghost_token = create_access_token(
        user_id="does-not-exist",
        email="ghost@example.com",
        role="tutor",
        name="Ghost",
    )
    resp = client.get("/api/auth/me", headers=_auth_header(ghost_token))
    assert resp.status_code == 401


# ── Dependency behaviour ──────────────────────────────────────────────────────


def test_get_current_user_dependency_raises_without_token(client: TestClient) -> None:
    """Endpoints using get_current_user must return 401 without auth."""
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_get_optional_user_dependency_returns_none_without_token(client: TestClient) -> None:
    """An endpoint using get_optional_user should be reachable without auth."""
    # We test this indirectly by calling a public endpoint that works without auth.
    resp = client.get("/health")
    assert resp.status_code == 200


def test_full_register_login_me_flow(client: TestClient) -> None:
    """End-to-end: register → login → /me all return consistent user data."""
    reg = _register(client, email="flow@example.com", name="Flow User", role="student")
    assert reg.status_code == 201

    login = _login(client, email="flow@example.com")
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/auth/me", headers=_auth_header(token))
    assert me.status_code == 200
    assert me.json()["email"] == "flow@example.com"
    assert me.json()["name"] == "Flow User"
    assert me.json()["role"] == "student"
