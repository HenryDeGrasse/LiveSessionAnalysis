"""Tests for the student-facing insights backend feature (Step 5).

Covers:
- generate_student_insights() returns correct structure and types
- Talk-time tips: low talk triggers encouragement tip
- Engagement tips: high engagement gives positive tip, low triggers nudge
- Attention tips: flagged moments trigger screen-presence tip
- Energy tips: low energy triggers rest tip
- Good session: no negative tips generated
- GET /sessions/{session_id}/student-insights — student owner can access
- GET /sessions/{session_id}/student-insights — 401 for unauthenticated
- GET /sessions/{session_id}/student-insights — 403 for tutor
- GET /sessions/{session_id}/student-insights — 403 for non-owner student
- GET /sessions/{session_id}/student-insights — 404 for missing session
- GET /sessions/{session_id} — student viewer receives student_insights key
- GET /sessions/{session_id} — tutor viewer does NOT receive student_insights key
"""

from __future__ import annotations

import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.analytics.recommendations import generate_student_insights
from app.auth.dependencies import get_optional_user
from app.auth.models import User
from app.main import app
from app.models import FlaggedMoment, SessionSummary


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_user(
    user_id: str = "user-001",
    role: str = "student",
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


def _make_summary(
    session_id: str = "s1",
    tutor_id: str = "tutor-001",
    student_user_id: str = "student-001",
    student_talk_ratio: float = 0.40,
    student_eye: float = 0.70,
    student_energy: float = 0.65,
    engagement_score: float = 72.0,
    flagged_moments: Optional[list] = None,
    duration: float = 1800.0,
) -> SessionSummary:
    now = datetime.utcnow()
    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        student_user_id=student_user_id,
        start_time=now,
        end_time=now + timedelta(seconds=duration),
        duration_seconds=duration,
        talk_time_ratio={"tutor": 1.0 - student_talk_ratio, "student": student_talk_ratio},
        avg_eye_contact={"student": student_eye},
        avg_energy={"student": student_energy},
        engagement_score=engagement_score,
        flagged_moments=flagged_moments or [],
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
# Unit tests for generate_student_insights()
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateStudentInsights:
    def test_returns_required_keys(self):
        insights = generate_student_insights(_make_summary())
        assert "engagement_percent" in insights
        assert "talk_time_percent" in insights
        assert "attention_score" in insights
        assert "tips" in insights

    def test_types_are_correct(self):
        insights = generate_student_insights(_make_summary())
        assert isinstance(insights["engagement_percent"], float)
        assert isinstance(insights["talk_time_percent"], float)
        assert isinstance(insights["attention_score"], float)
        assert isinstance(insights["tips"], list)
        for tip in insights["tips"]:
            assert isinstance(tip, str)

    def test_engagement_percent_matches_summary(self):
        summary = _make_summary(engagement_score=68.0)
        insights = generate_student_insights(summary)
        assert insights["engagement_percent"] == 68.0

    def test_talk_time_percent_scaled_to_100(self):
        summary = _make_summary(student_talk_ratio=0.35)
        insights = generate_student_insights(summary)
        assert insights["talk_time_percent"] == 35.0

    def test_attention_score_is_average_of_eye_and_energy(self):
        summary = _make_summary(student_eye=0.6, student_energy=0.4)
        insights = generate_student_insights(summary)
        # (0.6 + 0.4) / 2 * 100 = 50.0
        assert insights["attention_score"] == 50.0

    def test_low_talk_time_generates_participation_tip(self):
        summary = _make_summary(student_talk_ratio=0.10)
        insights = generate_student_insights(summary)
        assert any(
            "question" in tip.lower() or "participat" in tip.lower()
            for tip in insights["tips"]
        )

    def test_high_engagement_generates_positive_tip(self):
        summary = _make_summary(engagement_score=85.0)
        insights = generate_student_insights(summary)
        assert any("great" in tip.lower() for tip in insights["tips"])

    def test_low_engagement_generates_distraction_tip(self):
        summary = _make_summary(engagement_score=30.0)
        insights = generate_student_insights(summary)
        assert any(
            "distract" in tip.lower() or "engagement" in tip.lower() or "focus" in tip.lower()
            for tip in insights["tips"]
        )

    def test_attention_flags_generate_screen_tip(self):
        flag = FlaggedMoment(
            timestamp=60.0,
            metric_name="student_attention",
            value=0.0,
            direction="below",
            description="Student not visible",
        )
        summary = _make_summary(flagged_moments=[flag])
        insights = generate_student_insights(summary)
        assert any(
            "screen" in tip.lower() or "frame" in tip.lower() or "camera" in tip.lower()
            for tip in insights["tips"]
        )

    def test_low_energy_generates_rest_tip(self):
        summary = _make_summary(student_energy=0.15)
        insights = generate_student_insights(summary)
        assert any(
            "energy" in tip.lower() or "rest" in tip.lower() or "focus" in tip.lower()
            for tip in insights["tips"]
        )

    def test_good_session_no_negative_tips(self):
        summary = _make_summary(
            student_talk_ratio=0.40,
            student_eye=0.80,
            student_energy=0.75,
            engagement_score=82.0,
        )
        insights = generate_student_insights(summary)
        # No distraction/energy/attention flags → only positive or empty tips
        negative_keywords = ["distract", "low", "away", "rested", "screen"]
        negative_tips = [
            tip
            for tip in insights["tips"]
            if any(kw in tip.lower() for kw in negative_keywords)
        ]
        assert len(negative_tips) == 0

    def test_no_flagged_moments_no_attention_tip(self):
        summary = _make_summary(flagged_moments=[])
        insights = generate_student_insights(summary)
        attention_tips = [
            tip for tip in insights["tips"]
            if "away from the screen" in tip.lower()
        ]
        assert len(attention_tips) == 0


# ─────────────────────────────────────────────────────────────────────────────
# HTTP endpoint tests for GET /sessions/{id}/student-insights
# ─────────────────────────────────────────────────────────────────────────────


class TestStudentInsightsEndpoint:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def _store_with_summary(self, tmpdir, summary: SessionSummary):
        from app.analytics.session_store import SessionStore

        store = SessionStore(data_dir=tmpdir)
        store.save(summary)
        return store

    def test_student_owner_can_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", student_user_id="student-010")
            store = self._store_with_summary(tmpdir, summary)
            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/student-insights")
            assert resp.status_code == 200
            data = resp.json()
            assert "engagement_percent" in data
            assert "talk_time_percent" in data
            assert "attention_score" in data
            assert "tips" in data

    def test_unauthenticated_returns_401(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", student_user_id="student-010")
            store = self._store_with_summary(tmpdir, summary)

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/student-insights")
            assert resp.status_code == 401

    def test_tutor_is_forbidden(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", tutor_id="tutor-001", student_user_id="student-010")
            store = self._store_with_summary(tmpdir, summary)
            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/student-insights")
            assert resp.status_code == 403
            assert "student-only" in resp.json()["detail"].lower()

    def test_non_owner_student_is_forbidden(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", student_user_id="student-010")
            store = self._store_with_summary(tmpdir, summary)
            other_student = _make_user("student-999", role="student")

            with _override_user(other_student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1/student-insights")
            assert resp.status_code == 403

    def test_missing_session_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.analytics.session_store import SessionStore

            store = SessionStore(data_dir=tmpdir)
            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/no-such-session/student-insights")
            assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /sessions/{id}
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteSessionEndpoint:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def _store_with_summary(self, tmpdir, summary: SessionSummary):
        from app.analytics.session_store import SessionStore

        store = SessionStore(data_dir=tmpdir)
        store.save(summary)
        return store

    def test_owner_can_delete_session(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", tutor_id="tutor-001")
            store = self._store_with_summary(tmpdir, summary)
            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 204
            assert store.load("s1") is None

    def test_non_owner_gets_403(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", tutor_id="tutor-001")
            store = self._store_with_summary(tmpdir, summary)
            other_user = _make_user("tutor-999", role="tutor")

            with _override_user(other_user), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 403
            assert store.load("s1") is not None

    def test_unauthenticated_delete_returns_401(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", tutor_id="tutor-001")
            store = self._store_with_summary(tmpdir, summary)

            with _override_user(None), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/s1")
            assert resp.status_code == 401
            assert store.load("s1") is not None

    def test_delete_missing_session_returns_404(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from app.analytics.session_store import SessionStore

            store = SessionStore(data_dir=tmpdir)
            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.delete("/api/analytics/sessions/missing")
            assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# GET /sessions/{id} enrichment for student viewers
# ─────────────────────────────────────────────────────────────────────────────


class TestSessionDetailStudentInsightsEnrichment:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def _store_with_summary(self, tmpdir, summary: SessionSummary):
        from app.analytics.session_store import SessionStore

        store = SessionStore(data_dir=tmpdir)
        store.save(summary)
        return store

    def test_student_viewer_gets_student_insights_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", student_user_id="student-010")
            store = self._store_with_summary(tmpdir, summary)
            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            assert resp.status_code == 200
            data = resp.json()
            assert "student_insights" in data
            si = data["student_insights"]
            assert "engagement_percent" in si
            assert "talk_time_percent" in si
            assert "attention_score" in si
            assert "tips" in si

    def test_student_viewer_has_nudge_details_scrubbed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", student_user_id="student-010")
            store = self._store_with_summary(tmpdir, summary)
            student = _make_user("student-010", role="student")

            with _override_user(student), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            data = resp.json()
            assert data["nudge_details"] == []
            assert data["recommendations"] == []

    def test_tutor_viewer_does_not_get_student_insights(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = _make_summary("s1", tutor_id="tutor-001")
            store = self._store_with_summary(tmpdir, summary)
            tutor = _make_user("tutor-001", role="tutor")

            with _override_user(tutor), patch("app.analytics.router.store", store):
                client = TestClient(app)
                resp = client.get("/api/analytics/sessions/s1")
            assert resp.status_code == 200
            data = resp.json()
            assert "student_insights" not in data
