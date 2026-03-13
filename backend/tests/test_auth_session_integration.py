"""Tests for auth-aware session creation and analytics access (Step 3).

Covers:
- Session creation with authenticated user auto-sets tutor_id
- Analytics list filtering by authenticated tutor user
- Analytics list filtering by authenticated student user
- Session detail returns 403 for authenticated user who doesn't own the session
- Session deletion enforces ownership and removes the stored record
- Recommendations returns 403 for non-owner
- Trends auto-scopes to authenticated user
- Backward compat: unauthenticated session creation still works
- Backward compat: unauthenticated analytics access still works
- student_user_id persists through to SessionSummary via generate_summary
- WebSocket first-message user_auth sets participant user_id
- WebSocket works without user_auth message (backward compat)
- SessionSummary.is_owner() helper
"""

from __future__ import annotations

import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_optional_user
from app.auth.jwt_utils import create_access_token
from app.auth.models import User
from app.config import settings
from app.main import app
from app.models import MetricsSnapshot, SessionSummary
from app.session_manager import session_manager
from app.analytics.session_store import SessionStore
from app.analytics.summary import generate_summary


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_user(
    user_id: str = "user-001",
    role: str = "tutor",
    name: str = "Test User",
    email: Optional[str] = "test@example.com",
) -> User:
    now = datetime.utcnow().isoformat()
    return User(
        id=user_id,
        email=email,
        name=name,
        role=role,
        is_guest=False,
        created_at=now,
        updated_at=now,
    )


def _make_token(user: User) -> str:
    return create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        name=user.name,
    )


def _make_summary(
    session_id: str,
    tutor_id: str = "",
    student_user_id: str = "",
) -> SessionSummary:
    now = datetime.utcnow()
    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        student_user_id=student_user_id,
        start_time=now,
        end_time=now,
        duration_seconds=60.0,
        engagement_score=70.0,
    )


@contextmanager
def _override_user(user: Optional[User]):
    """Context manager: override get_optional_user for a test scope."""
    async def _mock_user():
        return user

    app.dependency_overrides[get_optional_user] = _mock_user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_optional_user, None)


# ─────────────────────────────────────────────────────────────────────────────
# SessionSummary.is_owner
# ─────────────────────────────────────────────────────────────────────────────

class TestIsOwner:
    def test_tutor_is_owner(self):
        summary = _make_summary("s1", tutor_id="tutor-001")
        assert summary.is_owner("tutor-001") is True

    def test_student_is_owner(self):
        summary = _make_summary("s1", student_user_id="student-002")
        assert summary.is_owner("student-002") is True

    def test_other_user_is_not_owner(self):
        summary = _make_summary("s1", tutor_id="tutor-001", student_user_id="student-002")
        assert summary.is_owner("stranger-999") is False

    def test_empty_user_id_is_not_owner(self):
        summary = _make_summary("s1", tutor_id="tutor-001")
        assert summary.is_owner("") is False

    def test_both_empty_is_not_owner(self):
        summary = _make_summary("s1")
        assert summary.is_owner("any-user") is False


# ─────────────────────────────────────────────────────────────────────────────
# generate_summary passes through student_user_id
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateSummaryStudentUserId:
    def test_student_user_id_persisted_with_snapshots(self):
        now = datetime.utcnow()
        snapshot = MetricsSnapshot(session_id="s1", timestamp=now)
        result = generate_summary(
            "s1",
            [snapshot],
            tutor_id="tutor-001",
            student_user_id="student-002",
        )
        assert result.student_user_id == "student-002"

    def test_student_user_id_persisted_empty_snapshots(self):
        result = generate_summary(
            "s1",
            [],
            tutor_id="tutor-001",
            student_user_id="student-002",
        )
        assert result.student_user_id == "student-002"

    def test_student_user_id_defaults_to_empty(self):
        result = generate_summary("s1", [])
        assert result.student_user_id == ""


# ─────────────────────────────────────────────────────────────────────────────
# Session store: student_user_id filter
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionStoreStudentFilter:
    def test_filter_by_student_user_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            s_mine = _make_summary("s1", student_user_id="student-A")
            s_other = _make_summary("s2", student_user_id="student-B")
            s_no_student = _make_summary("s3", tutor_id="tutor-X")
            store.save(s_mine)
            store.save(s_other)
            store.save(s_no_student)

            results = store.list_sessions(student_user_id="student-A")
            ids = {r.session_id for r in results}
            assert ids == {"s1"}

    def test_filter_by_tutor_id_still_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-A"))
            store.save(_make_summary("s2", tutor_id="tutor-B"))

            results = store.list_sessions(tutor_id="tutor-A")
            assert len(results) == 1
            assert results[0].session_id == "s1"

    def test_no_filter_returns_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-A"))
            store.save(_make_summary("s2", student_user_id="student-B"))

            results = store.list_sessions()
            assert len(results) == 2


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/sessions — auth-aware creation
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionCreationAuth:
    def setup_method(self):
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()
        for sid in list(session_manager._sessions.keys()):
            session_manager.remove_session(sid)

    def test_authenticated_tutor_id_overrides_body(self):
        """Authenticated user's ID is used as tutor_id, ignoring body.tutor_id."""
        tutor = _make_user("auth-tutor-001", role="tutor")
        with _override_user(tutor):
            resp = self.client.post(
                "/api/sessions",
                json={"tutor_id": "ignored-name", "session_type": "practice"},
            )
        assert resp.status_code == 200
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.tutor_id == "auth-tutor-001"

    def test_authenticated_tutor_cannot_forge_student_user_id(self):
        """Authenticated tutor cannot inject student_user_id from the request body."""
        tutor = _make_user("auth-tutor-002", role="tutor")
        with _override_user(tutor):
            resp = self.client.post(
                "/api/sessions",
                json={"session_type": "general", "student_user_id": "forged-student"},
            )
        assert resp.status_code == 200
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.tutor_id == "auth-tutor-002"
        # Body student_user_id must be ignored — tutor cannot forge a student's identity
        assert room.student_user_id == ""

    def test_authenticated_student_cannot_forge_tutor_id(self):
        """Authenticated student cannot inject tutor_id from the request body."""
        student = _make_user("auth-student-001", role="student")
        with _override_user(student):
            resp = self.client.post(
                "/api/sessions",
                json={"session_type": "general", "tutor_id": "forged-tutor"},
            )
        assert resp.status_code == 200
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.student_user_id == "auth-student-001"
        # Body tutor_id must be ignored — student cannot forge a tutor's identity
        assert room.tutor_id == ""

    def test_unauthenticated_uses_body_tutor_id(self):
        """Backward compat: unauthenticated creation uses the body tutor_id."""
        with _override_user(None):
            resp = self.client.post(
                "/api/sessions",
                json={"tutor_id": "legacy-tutor", "session_type": "general"},
            )
        assert resp.status_code == 200
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.tutor_id == "legacy-tutor"

    def test_unauthenticated_no_body_works(self):
        """Unauthenticated creation without a body still works."""
        with _override_user(None):
            resp = self.client.post("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/sessions — auth-aware listing
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyticsListAuth:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_authenticated_tutor_sees_own_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))
            store.save(_make_summary("s2", tutor_id="tutor-002"))

            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions")
            assert resp.status_code == 200
            ids = {s["session_id"] for s in resp.json()}
            assert ids == {"s1"}

    def test_authenticated_student_sees_own_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", student_user_id="student-010"))
            store.save(_make_summary("s2", student_user_id="student-020"))
            store.save(_make_summary("s3", tutor_id="tutor-X"))

            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions")
            assert resp.status_code == 200
            ids = {s["session_id"] for s in resp.json()}
            assert ids == {"s1"}

    def test_unauthenticated_uses_explicit_tutor_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-legacy"))
            store.save(_make_summary("s2", tutor_id="tutor-other"))

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions?tutor_id=tutor-legacy")
            assert resp.status_code == 200
            ids = {s["session_id"] for s in resp.json()}
            assert ids == {"s1"}

    def test_unauthenticated_no_filter_returns_empty(self):
        """Unauthenticated requests without an explicit tutor_id scope must
        return [] rather than all sessions.  This closes the data-leak window
        that previously allowed the analytics pages to flash all stored sessions
        while NextAuth was still resolving the session on the client side."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-A"))
            store.save(_make_summary("s2", tutor_id="tutor-B"))

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions")
            assert resp.status_code == 200
            assert resp.json() == [], (
                "Unauthenticated requests with no tutor_id scope must return [] "
                "to prevent enumeration of all sessions."
            )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/sessions/{id} — ownership check
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyticsDetailAuth:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_tutor_owner_can_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))

            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            assert resp.status_code == 200

    def test_non_owner_gets_403(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))

            other = _make_user("stranger-999", role="tutor")

            with _override_user(other), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            assert resp.status_code == 403

    def test_student_owner_can_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", student_user_id="student-010"))

            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            assert resp.status_code == 200

    def test_unauthenticated_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="legacy-tutor"))

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            assert resp.status_code == 401

    def test_missing_session_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)

            # Auth check passes (user is authenticated), but session does not exist.
            tutor = _make_user("tutor-999", role="tutor")
            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/does-not-exist")
            assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/sessions/{id}/recommendations — ownership check
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyticsDeleteAuth:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_tutor_owner_can_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))

            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 204
            assert store.load("s1") is None

    def test_student_owner_can_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", student_user_id="student-010"))

            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 204
            assert store.load("s1") is None

    def test_non_owner_gets_403_for_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))

            other = _make_user("stranger-999", role="tutor")

            with _override_user(other), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 403
            assert store.load("s1") is not None

    def test_unauthenticated_is_rejected_for_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="legacy-tutor"))

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 401
            assert store.load("s1") is not None

    def test_missing_session_returns_404_for_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/does-not-exist")
            assert resp.status_code == 404


class TestRecommendationsAuth:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_owner_can_get_recommendations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))

            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/recommendations")
            assert resp.status_code == 200

    def test_non_owner_gets_403_for_recommendations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))

            other = _make_user("stranger-999", role="tutor")

            with _override_user(other), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/recommendations")
            assert resp.status_code == 403

    def test_unauthenticated_is_rejected_for_recommendations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1"))

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/recommendations")
            assert resp.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/analytics/trends — auth-aware scoping
# ─────────────────────────────────────────────────────────────────────────────

class TestTrendsAuth:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_authenticated_user_sees_only_own_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-001"))
            store.save(_make_summary("s2", tutor_id="tutor-002"))

            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/trends")
            assert resp.status_code == 200
            data = resp.json()
            # Should only have s1 in sessions
            session_ids = {s["session_id"] for s in data.get("sessions", [])}
            assert session_ids == {"s1"}

    def test_unauthenticated_uses_explicit_tutor_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            store.save(_make_summary("s1", tutor_id="tutor-legacy"))
            store.save(_make_summary("s2", tutor_id="tutor-other"))

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/trends?tutor_id=tutor-legacy")
            assert resp.status_code == 200
            data = resp.json()
            session_ids = {s["session_id"] for s in data.get("sessions", [])}
            assert session_ids == {"s1"}

    def test_trends_returns_200_with_no_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(data_dir=tmpdir)
            tutor = _make_user("tutor-empty", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/trends")
            assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket first-message user_auth
# ─────────────────────────────────────────────────────────────────────────────

class TestWebSocketUserAuth:
    def setup_method(self):
        self.client = TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()
        for sid in list(session_manager._sessions.keys()):
            session_manager.remove_session(sid)

    def _create_session(self) -> dict:
        # Use no-auth override so creation doesn't need a real DB user
        with _override_user(None):
            resp = self.client.post("/api/sessions", json={"session_type": "general"})
        assert resp.status_code == 200
        return resp.json()

    def test_user_auth_message_sets_participant_user_id(self):
        """Sending user_auth message sets user_id on the participant state.

        UserStore.get_by_id is mocked to return the user — confirming that
        the WS handler correctly loads the user from the DB before accepting
        the authentication.
        """
        data = self._create_session()
        session_id = data["session_id"]
        student_token_ws = data["student_token"]

        student = _make_user("student-ws-001", role="student")
        jwt_token = _make_token(student)

        with patch("app.auth.user_store.UserStore.get_by_id", return_value=student):
            with self.client.websocket_connect(
                f"/ws/session/{session_id}?token={student_token_ws}"
            ) as ws:
                ws.send_json({
                    "type": "user_auth",
                    "data": {"access_token": jwt_token},
                })
                import time as _time
                _time.sleep(0.05)

        room = session_manager.get_session(session_id)
        assert room is not None
        from app.models import Role
        student_participant = room.participants[Role.STUDENT]
        assert student_participant.user_id == "student-ws-001"
        # student_user_id should also be updated on the room
        assert room.student_user_id == "student-ws-001"

    def test_tutor_user_auth_sets_participant_user_id(self):
        """Sending user_auth as tutor sets tutor participant's user_id.

        UserStore.get_by_id is mocked to return the user — confirming that
        the WS handler does a DB check before accepting the auth token.
        """
        data = self._create_session()
        session_id = data["session_id"]
        tutor_token = data["tutor_token"]

        tutor = _make_user("tutor-ws-001", role="tutor")
        jwt_token = _make_token(tutor)

        with patch("app.auth.user_store.UserStore.get_by_id", return_value=tutor):
            with self.client.websocket_connect(
                f"/ws/session/{session_id}?token={tutor_token}"
            ) as ws:
                ws.send_json({
                    "type": "user_auth",
                    "data": {"access_token": jwt_token},
                })
                import time as _time
                _time.sleep(0.05)

        room = session_manager.get_session(session_id)
        assert room is not None
        from app.models import Role
        tutor_participant = room.participants[Role.TUTOR]
        assert tutor_participant.user_id == "tutor-ws-001"
        # room.student_user_id should NOT be set by a tutor auth
        assert room.student_user_id == ""

    def test_user_auth_nonexistent_user_is_rejected(self):
        """A valid JWT for a deleted/nonexistent user must NOT authenticate.

        This matches the HTTP endpoint behaviour: GET /api/auth/me returns 401
        for a valid token whose sub doesn't exist in the DB.  The WS handler
        must apply the same check — signing alone is not sufficient.
        """
        data = self._create_session()
        session_id = data["session_id"]
        student_token_ws = data["student_token"]

        # Create a valid JWT whose user_id will NOT be found in the DB
        ghost = _make_user("ghost-user-999", role="student")
        jwt_token = _make_token(ghost)

        # UserStore.get_by_id returns None → user doesn't exist in DB
        with patch("app.auth.user_store.UserStore.get_by_id", return_value=None):
            with self.client.websocket_connect(
                f"/ws/session/{session_id}?token={student_token_ws}"
            ) as ws:
                ws.send_json({
                    "type": "user_auth",
                    "data": {"access_token": jwt_token},
                })
                import time as _time
                _time.sleep(0.05)

        room = session_manager.get_session(session_id)
        assert room is not None
        from app.models import Role
        student_participant = room.participants[Role.STUDENT]
        # The ghost user's token must NOT have set user_id or student_user_id
        assert student_participant.user_id == ""
        assert room.student_user_id == ""

    def test_websocket_works_without_user_auth_backward_compat(self):
        """WebSocket session works without user_auth message (guest/legacy)."""
        data = self._create_session()
        session_id = data["session_id"]
        tutor_token = data["tutor_token"]

        # Just connect and send a client_status message — no user_auth
        with self.client.websocket_connect(
            f"/ws/session/{session_id}?token={tutor_token}"
        ) as ws:
            ws.send_json({
                "type": "client_status",
                "data": {"audio_muted": False},
            })
            import time as _time
            _time.sleep(0.05)

        room = session_manager.get_session(session_id)
        assert room is not None
        from app.models import Role
        tutor_participant = room.participants[Role.TUTOR]
        # No user_id set — backward compat
        assert tutor_participant.user_id == ""

    def test_user_auth_with_invalid_token_is_ignored(self):
        """Invalid JWT in user_auth is silently ignored — participant remains unauthenticated."""
        data = self._create_session()
        session_id = data["session_id"]
        tutor_token = data["tutor_token"]

        with self.client.websocket_connect(
            f"/ws/session/{session_id}?token={tutor_token}"
        ) as ws:
            ws.send_json({
                "type": "user_auth",
                "data": {"access_token": "not-a-valid-jwt"},
            })
            import time as _time
            _time.sleep(0.05)

        room = session_manager.get_session(session_id)
        assert room is not None
        from app.models import Role
        tutor_participant = room.participants[Role.TUTOR]
        assert tutor_participant.user_id == ""
