"""Tests for auth models, password hashing, UserStore, and JWT helpers."""

from __future__ import annotations

import os
import time
import pytest
import tempfile

import jwt as pyjwt

from app.auth.password import hash_password, verify_password
from app.auth.user_store import UserStore
from app.auth.models import User, UserCreate, UserLogin, GuestAuthRequest
from app.auth.jwt import create_access_token, decode_access_token


# ── Password hashing ─────────────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        h = hash_password("mysecretpassword")
        assert "mysecretpassword" not in h

    def test_hash_has_expected_format(self):
        h = hash_password("test")
        parts = h.split(":")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"

    def test_verify_correct_password(self):
        h = hash_password("correcthorsebatterystaple")
        assert verify_password("correcthorsebatterystaple", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("correcthorsebatterystaple")
        assert verify_password("wrongpassword", h) is False

    def test_same_password_produces_different_hashes(self):
        """Each hash call uses a new random salt."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_verify_still_works_across_different_hashes(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert verify_password("same", h1) is True
        assert verify_password("same", h2) is True

    def test_verify_invalid_stored_value(self):
        assert verify_password("anything", "notahash") is False
        assert verify_password("anything", "") is False
        assert verify_password("anything", "a:b:c") is False


# ── UserStore ────────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    """Return a UserStore backed by a temporary SQLite database."""
    db_path = str(tmp_path / "test_auth.db")
    return UserStore(db_path=db_path)


class TestUserStore:
    def test_create_and_get_by_id(self, store: UserStore):
        user = store.create_user(
            name="Alice",
            email="alice@example.com",
            password_hash=hash_password("password1"),
        )
        fetched = store.get_by_id(user.id)
        assert fetched is not None
        assert fetched.id == user.id
        assert fetched.email == "alice@example.com"
        assert fetched.name == "Alice"
        assert fetched.is_guest is False

    def test_email_is_lowercased_on_create(self, store: UserStore):
        user = store.create_user(
            name="Bob",
            email="BOB@EXAMPLE.COM",
            password_hash=hash_password("password1"),
        )
        assert user.email == "bob@example.com"

    def test_get_by_email(self, store: UserStore):
        store.create_user(
            name="Carol",
            email="carol@example.com",
            password_hash=hash_password("password1"),
        )
        found = store.get_by_email("carol@example.com")
        assert found is not None
        assert found.name == "Carol"

    def test_get_by_email_case_insensitive(self, store: UserStore):
        store.create_user(
            name="Dan",
            email="dan@example.com",
            password_hash=hash_password("password1"),
        )
        found = store.get_by_email("DAN@EXAMPLE.COM")
        assert found is not None
        assert found.name == "Dan"

    def test_get_by_email_includes_password_hash(self, store: UserStore):
        """get_by_email must return the stored password_hash so login works
        without a second query via get_password_hash."""
        plain = "hunter2"
        ph = hash_password(plain)
        store.create_user(name="HashTest", email="hashtest@example.com", password_hash=ph)
        found = store.get_by_email("hashtest@example.com")
        assert found is not None
        assert found.password_hash is not None
        assert verify_password(plain, found.password_hash) is True

    def test_get_by_id_missing(self, store: UserStore):
        assert store.get_by_id("nonexistent") is None

    def test_get_by_email_missing(self, store: UserStore):
        assert store.get_by_email("nobody@example.com") is None

    def test_duplicate_email_raises(self, store: UserStore):
        store.create_user(
            name="Eve",
            email="eve@example.com",
            password_hash=hash_password("password1"),
        )
        with pytest.raises(ValueError, match="already exists"):
            store.create_user(
                name="EveAgain",
                email="eve@example.com",
                password_hash=hash_password("password2"),
            )

    def test_get_password_hash(self, store: UserStore):
        store.create_user(
            name="Frank",
            email="frank@example.com",
            password_hash=hash_password("mypassword"),
        )
        stored_hash = store.get_password_hash("frank@example.com")
        assert stored_hash is not None
        assert verify_password("mypassword", stored_hash) is True

    def test_get_password_hash_missing(self, store: UserStore):
        assert store.get_password_hash("nobody@example.com") is None

    def test_get_by_google_id(self, store: UserStore):
        user = store.create_user(
            name="Gina", email="gina@example.com", google_id="google-123"
        )
        found = store.get_by_google_id("google-123")
        assert found is not None
        assert found.id == user.id

    def test_get_by_google_id_missing(self, store: UserStore):
        assert store.get_by_google_id("nonexistent") is None

    def test_upsert_google_user_creates_new(self, store: UserStore):
        user = store.upsert_google_user(
            google_id="g-001",
            email="new@example.com",
            name="New User",
            avatar_url="https://example.com/avatar.jpg",
        )
        assert user.google_id == "g-001"
        assert user.email == "new@example.com"
        assert user.avatar_url == "https://example.com/avatar.jpg"

    def test_upsert_google_user_returns_same_id(self, store: UserStore):
        """The same user record is returned on each upsert (ID is stable)."""
        first = store.upsert_google_user(
            google_id="g-002", email="existing@example.com", name="First"
        )
        second = store.upsert_google_user(
            google_id="g-002", email="existing@example.com", name="First"
        )
        assert first.id == second.id

    def test_upsert_google_user_updates_profile_on_revisit(self, store: UserStore):
        """Profile fields (name, avatar) are refreshed from Google on each upsert.

        This prevents profiles from going stale when a user renames themselves
        or changes their profile picture in Google.
        """
        first = store.upsert_google_user(
            google_id="g-002b",
            email="refreshable@example.com",
            name="Old Name",
            avatar_url="https://example.com/old.jpg",
        )
        second = store.upsert_google_user(
            google_id="g-002b",
            email="refreshable@example.com",
            name="New Name",
            avatar_url="https://example.com/new.jpg",
        )
        assert first.id == second.id
        assert second.name == "New Name"
        assert second.avatar_url == "https://example.com/new.jpg"

    def test_upsert_google_user_links_existing_email(self, store: UserStore):
        # Create email/password user first
        email_user = store.create_user(
            name="Linked",
            email="linked@example.com",
            password_hash=hash_password("password1"),
        )
        # Now upsert with same email but different google_id
        google_user = store.upsert_google_user(
            google_id="g-003",
            email="linked@example.com",
            name="Linked",
        )
        assert google_user.id == email_user.id
        assert google_user.google_id == "g-003"

    def test_update_user_fields(self, store: UserStore):
        user = store.create_user(
            name="Harry",
            email="harry@example.com",
            password_hash=hash_password("password1"),
        )
        updated = store.update_user(user.id, name="Harry Updated")
        assert updated is not None
        assert updated.name == "Harry Updated"
        assert updated.id == user.id

    def test_update_user_password(self, store: UserStore):
        user = store.create_user(
            name="Iris",
            email="iris@example.com",
            password_hash=hash_password("oldpassword"),
        )
        store.update_user(user.id, password="newpassword")
        new_hash = store.get_password_hash("iris@example.com")
        assert new_hash is not None
        assert verify_password("newpassword", new_hash) is True
        assert verify_password("oldpassword", new_hash) is False

    def test_update_user_missing_id_returns_none(self, store: UserStore):
        result = store.update_user("nonexistent-id", name="Ghost")
        assert result is None

    def test_update_user_disallowed_field_raises(self, store: UserStore):
        user = store.create_user(
            name="Jack",
            email="jack@example.com",
            password_hash=hash_password("password1"),
        )
        with pytest.raises(ValueError, match="not updatable"):
            store.update_user(user.id, created_at="2020-01-01")

    def test_guest_user_creation(self, store: UserStore):
        guest = store.create_user(name="Guest123", is_guest=True)
        assert guest.is_guest is True
        assert guest.email is None
        fetched = store.get_by_id(guest.id)
        assert fetched is not None
        assert fetched.is_guest is True

    def test_guest_user_no_email_uniqueness_conflict(self, store: UserStore):
        """Multiple guests with no email should not conflict."""
        g1 = store.create_user(name="Guest A", is_guest=True)
        g2 = store.create_user(name="Guest B", is_guest=True)
        assert g1.id != g2.id

    def test_create_user_positional_order_matches_spec(self, store: UserStore):
        """Regression: create_user(email, password_hash, name, role, google_id, is_guest)
        must map positional args to the correct columns — not silently shift them."""
        ph = hash_password("password1")
        user = store.create_user(
            "positional@example.com",
            ph,
            "Positional User",
            "student",
            None,
            False,
        )
        # Verify each field landed in the right column
        assert user.email == "positional@example.com", (
            f"email wrong: got {user.email!r} — positional arg order is broken"
        )
        assert user.name == "Positional User", (
            f"name wrong: got {user.name!r} — positional arg order is broken"
        )
        assert user.role == "student", (
            f"role wrong: got {user.role!r} — positional arg order is broken"
        )
        assert user.google_id is None
        assert user.is_guest is False
        # password_hash must verify correctly (proves it wasn't swapped into wrong column)
        stored = store.get_password_hash("positional@example.com")
        assert stored is not None
        assert verify_password("password1", stored), (
            "password_hash was inserted into the wrong column"
        )

    def test_create_user_empty_name_raises(self, store: UserStore):
        """name must not be empty or whitespace-only."""
        with pytest.raises(ValueError, match="name must not be empty"):
            store.create_user(email="noname@example.com", name="")

    def test_create_user_invalid_role_raises_before_insert(self, store: UserStore):
        """An invalid role must be rejected with ValueError BEFORE any DB write.

        Previously the INSERT committed first and then Pydantic's User()
        constructor raised ValidationError, leaving a corrupted row in the DB.
        """
        with pytest.raises(ValueError, match="role must be one of"):
            store.create_user(
                email="bad@example.com",
                name="Bad",
                role="owner",
            )
        # The row must NOT be in the DB — a subsequent get must return None
        assert store.get_by_email("bad@example.com") is None

    def test_update_user_invalid_role_raises_before_update(self, store: UserStore):
        """update_user must reject invalid roles before writing to the DB."""
        user = store.create_user(name="Kira", email="kira@example.com", role="tutor")
        with pytest.raises(ValueError, match="role must be one of"):
            store.update_user(user.id, role="owner")
        # Role must remain unchanged
        refetched = store.get_by_id(user.id)
        assert refetched is not None
        assert refetched.role == "tutor"

    def test_update_user_whitespace_only_name_raises(self, store: UserStore):
        """update_user must reject whitespace-only names.

        Previously create_user blocked them but update_user let them through,
        allowing guest-upgrade flows to persist blank names.
        """
        user = store.create_user(name="Leo", email="leo@example.com")
        with pytest.raises(ValueError, match="name must not be empty"):
            store.update_user(user.id, name="   ")
        # Name must remain unchanged
        refetched = store.get_by_id(user.id)
        assert refetched is not None
        assert refetched.name == "Leo"


# ── JWT helpers ──────────────────────────────────────────────────────────────


class TestJWTHelpers:
    def test_create_and_decode_roundtrip(self):
        token = create_access_token(
            user_id="user-123",
            email="test@example.com",
            role="tutor",
            name="Test User",
        )
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert payload["role"] == "tutor"
        assert payload["name"] == "Test User"

    def test_token_with_none_email(self):
        token = create_access_token(
            user_id="guest-456",
            email=None,
            role="student",
            name="Anonymous",
        )
        payload = decode_access_token(token)
        assert payload["sub"] == "guest-456"
        assert payload["email"] is None

    def test_expired_token_raises(self, monkeypatch):
        # Patch jwt_expiry_hours to 0 by directly encoding with past expiry
        from datetime import datetime, timedelta, timezone
        import jwt as pyjwt
        from app.config import settings

        now = datetime.now(timezone.utc) - timedelta(hours=2)
        payload = {
            "sub": "user-789",
            "email": "exp@example.com",
            "role": "tutor",
            "name": "Expired",
            "iat": now,
            "exp": now + timedelta(seconds=1),  # already expired
        }
        expired_token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_access_token(expired_token)

    def test_invalid_signature_raises(self):
        token = create_access_token("u1", "u@e.com", "tutor", "U")
        # Tamper with signature
        parts = token.split(".")
        parts[-1] = parts[-1][::-1]
        bad_token = ".".join(parts)
        with pytest.raises(pyjwt.InvalidTokenError):
            decode_access_token(bad_token)

    def test_wrong_secret_raises(self):
        token = create_access_token("u2", "u2@e.com", "student", "U2")
        with pytest.raises(pyjwt.InvalidTokenError):
            pyjwt.decode(token, "wrong-secret", algorithms=["HS256"])


# ── Pydantic model validation ────────────────────────────────────────────────


class TestUserCreateValidation:
    def test_valid_create(self):
        uc = UserCreate(
            email="valid@example.com",
            password="goodpassword",
            name="Valid User",
        )
        assert uc.email == "valid@example.com"

    def test_email_normalised_to_lowercase(self):
        uc = UserCreate(email="UPPER@EXAMPLE.COM", password="goodpassword", name="Upper")
        assert uc.email == "upper@example.com"

    def test_short_password_rejected(self):
        with pytest.raises(Exception):
            UserCreate(email="x@x.com", password="short", name="X")

    def test_empty_name_rejected(self):
        with pytest.raises(Exception):
            UserCreate(email="x@x.com", password="goodpassword", name="   ")


class TestGuestAuthRequest:
    def test_default_display_name_is_empty(self):
        req = GuestAuthRequest()
        assert req.display_name == ""
        assert req.role == "student"

    def test_custom_display_name(self):
        req = GuestAuthRequest(display_name="AnonUser", role="tutor")
        assert req.display_name == "AnonUser"
        assert req.role == "tutor"
