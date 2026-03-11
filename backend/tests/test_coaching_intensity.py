"""Tests for coaching intensity multipliers.

Verifies that the CoachingIntensity field on SessionCreateRequest is accepted
and stored, and that the Coach engine applies the correct intensity-based
multipliers to warmup, cooldown, and max-per-session thresholds.

Intensities:
- ``off``        – no nudges ever fire (multiplier is None → budget is 0).
- ``subtle``     – warmup and cooldown are doubled, max_per_session is lowered by 1.
- ``normal``     – defaults from settings used as-is.
- ``aggressive`` – warmup and cooldown are halved, max_per_session doubled.
"""

from __future__ import annotations

import app.coaching_system.coach as coach_module
import pytest
from fastapi.testclient import TestClient

from app.coaching_system.coach import Coach
from app.coaching_system.rules import CoachingRule
from app.config import INTENSITY_MULTIPLIERS, settings
from app.main import app
from app.models import (
    CoachingIntensity,
    MetricsSnapshot,
    NudgePriority,
    ParticipantMetrics,
    SessionMetrics,
    SessionCreateRequest,
    SessionCreateResponse,
)
from app.session_manager import session_manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _always_true_rule(name: str = "test_rule") -> CoachingRule:
    """Return a CoachingRule whose condition is always True."""
    return CoachingRule(
        name=name,
        nudge_type=f"nudge_{name}",
        condition=lambda s, e, p: True,
        message_template="Test nudge",
        priority=NudgePriority.MEDIUM,
        cooldown_seconds=0,
        min_session_elapsed=0,
    )


def _make_snapshot() -> MetricsSnapshot:
    return MetricsSnapshot(
        session_id="test",
        tutor=ParticipantMetrics(
            eye_contact_score=0.8,
            talk_time_percent=0.6,
            energy_score=0.7,
        ),
        student=ParticipantMetrics(
            eye_contact_score=0.7,
            talk_time_percent=0.4,
            energy_score=0.6,
            attention_state_confidence=0.9,
        ),
        session=SessionMetrics(engagement_trend="stable", engagement_score=70.0),
    )


# ---------------------------------------------------------------------------
# Test 1: 'off' intensity blocks all nudges
# ---------------------------------------------------------------------------

class TestOffIntensityBlocksAllNudges:
    def test_off_intensity_never_emits_nudges(self, monkeypatch):
        """Coach with intensity='off' must never emit any nudge, even for
        a rule that always triggers and even after warmup has elapsed."""
        rule = _always_true_rule()
        coach = Coach(rules=[rule], intensity="off")

        snapshot = _make_snapshot()
        # Large elapsed_seconds to ensure no warmup or interval would block us
        # under normal conditions.
        monkeypatch.setattr(coach_module.time, "time", lambda: 10_000.0)
        nudges = coach.check(snapshot, elapsed_seconds=9_999)
        assert nudges == [], "intensity='off' must block all nudges"

    def test_off_intensity_multiplier_is_none(self):
        """Verify that the multiplier for 'off' is None (sentinel for disabled)."""
        assert INTENSITY_MULTIPLIERS["off"] is None

    def test_off_coach_intensity_property(self):
        """Coach.intensity reflects the stored value."""
        coach = Coach(intensity="off")
        assert coach.intensity == "off"

    def test_off_intensity_suppressed_reason_recorded(self, monkeypatch):
        """Evaluation must record a suppressed_reason explaining why no nudge fired."""
        rule = _always_true_rule()
        coach = Coach(rules=[rule], intensity="off")
        snapshot = _make_snapshot()
        monkeypatch.setattr(coach_module.time, "time", lambda: 10_000.0)
        evaluation = coach.evaluate(snapshot, elapsed_seconds=9_999)
        assert len(evaluation.nudges) == 0
        assert len(evaluation.suppressed_reasons) > 0


# ---------------------------------------------------------------------------
# Test 2: 'subtle' doubles warmup (and cooldown), lowers budget
# ---------------------------------------------------------------------------

class TestSubtleDoublesWarmup:
    def test_subtle_suppresses_during_doubled_warmup(self, monkeypatch):
        """With intensity='subtle' the effective warmup is 2× settings.global_nudge_warmup_seconds.
        A call at exactly the normal warmup boundary should still be suppressed."""
        rule = _always_true_rule()
        coach = Coach(rules=[rule], intensity="subtle")
        snapshot = _make_snapshot()

        # elapsed = normal warmup (120s) — this should still be within the doubled warmup (240s)
        normal_warmup = settings.global_nudge_warmup_seconds  # 120
        monkeypatch.setattr(coach_module.time, "time", lambda: 10_000.0)
        nudges = coach.check(snapshot, elapsed_seconds=normal_warmup)
        assert nudges == [], (
            "intensity='subtle' should suppress during doubled warmup "
            f"(elapsed={normal_warmup}, effective_warmup={normal_warmup * 2})"
        )

    def test_subtle_fires_after_doubled_warmup(self, monkeypatch):
        """After 2× warmup has elapsed, 'subtle' should allow nudges to fire."""
        rule = _always_true_rule()
        coach = Coach(rules=[rule], intensity="subtle")
        snapshot = _make_snapshot()

        doubled_warmup = settings.global_nudge_warmup_seconds * 2  # 240
        monkeypatch.setattr(coach_module.time, "time", lambda: 10_000.0)
        nudges = coach.check(snapshot, elapsed_seconds=doubled_warmup + 1)
        assert len(nudges) == 1, (
            f"intensity='subtle' should allow nudge after doubled warmup "
            f"(elapsed={doubled_warmup + 1})"
        )

    def test_subtle_multiplier_is_two(self):
        """Verify the configured multiplier for 'subtle' is 2.0."""
        assert INTENSITY_MULTIPLIERS["subtle"] == 2.0

    def test_subtle_lowers_max_per_session(self, monkeypatch):
        """With intensity='subtle', max_per_session is reduced by 1 vs normal."""
        normal_max = settings.global_nudge_max_per_session  # 3
        subtle_expected_max = max(1, normal_max - 1)  # 2

        rule = _always_true_rule()
        # Use a large interval so the global interval gate doesn't block us;
        # we're only testing the budget cap.
        coach = Coach(rules=[rule], intensity="subtle")
        snapshot = _make_snapshot()

        doubled_warmup = settings.global_nudge_warmup_seconds * 2
        # Fire nudges, advancing time beyond the doubled interval each time.
        doubled_interval = settings.global_nudge_min_interval_seconds * 2  # 600
        base_time = 10_000.0
        fired = 0
        for i in range(subtle_expected_max + 2):  # Try to fire more than allowed
            t = base_time + i * (doubled_interval + 1)
            monkeypatch.setattr(coach_module.time, "time", lambda _t=t: _t)
            result = coach.check(snapshot, elapsed_seconds=doubled_warmup + t)
            fired += len(result)

        assert fired == subtle_expected_max, (
            f"intensity='subtle' should cap at {subtle_expected_max} nudges, got {fired}"
        )


# ---------------------------------------------------------------------------
# Test 3: 'aggressive' halves cooldown (fires sooner)
# ---------------------------------------------------------------------------

class TestAggressiveHalvesCooldown:
    def test_aggressive_fires_sooner_than_normal(self, monkeypatch):
        """With intensity='aggressive', cooldown is halved so nudges fire more often.
        Verify a second nudge fires at half the normal min-interval."""
        rule = _always_true_rule()
        normal_interval = settings.global_nudge_min_interval_seconds  # 300
        half_interval = normal_interval * 0.5  # 150

        coach = Coach(rules=[rule], intensity="aggressive")
        snapshot = _make_snapshot()
        warmup = settings.global_nudge_warmup_seconds * 0.5  # 60

        # First nudge at warmup + 1
        t1 = warmup + 1
        monkeypatch.setattr(coach_module.time, "time", lambda: t1)
        first = coach.check(snapshot, elapsed_seconds=t1)
        assert len(first) == 1, "Aggressive: first nudge should fire after half-warmup"

        # Attempt at half the normal interval — should pass because aggressive halves it
        t2 = t1 + half_interval + 1
        monkeypatch.setattr(coach_module.time, "time", lambda: t2)
        second = coach.check(snapshot, elapsed_seconds=t2)
        assert len(second) == 1, (
            f"Aggressive: second nudge should fire at half the normal interval "
            f"(t2={t2}, half_interval={half_interval})"
        )

    def test_aggressive_multiplier_is_half(self):
        """Verify the configured multiplier for 'aggressive' is 0.5."""
        assert INTENSITY_MULTIPLIERS["aggressive"] == 0.5

    def test_aggressive_doubles_max_per_session(self, monkeypatch):
        """With intensity='aggressive', max_per_session is doubled vs normal."""
        normal_max = settings.global_nudge_max_per_session  # 3
        aggressive_expected_max = normal_max * 2  # 6

        rule = _always_true_rule()
        coach = Coach(rules=[rule], intensity="aggressive")
        snapshot = _make_snapshot()

        half_warmup = settings.global_nudge_warmup_seconds * 0.5  # 60
        half_interval = settings.global_nudge_min_interval_seconds * 0.5  # 150
        base_time = 10_000.0
        fired = 0
        for i in range(aggressive_expected_max + 2):
            t = base_time + i * (half_interval + 1)
            monkeypatch.setattr(coach_module.time, "time", lambda _t=t: _t)
            result = coach.check(snapshot, elapsed_seconds=half_warmup + t)
            fired += len(result)

        assert fired == aggressive_expected_max, (
            f"intensity='aggressive' should cap at {aggressive_expected_max} nudges, got {fired}"
        )


# ---------------------------------------------------------------------------
# Test 4: 'normal' is the default and uses settings as-is
# ---------------------------------------------------------------------------

class TestNormalIsDefault:
    def test_normal_is_default_intensity(self):
        """Coach() with no intensity kwarg must default to 'normal'."""
        coach = Coach()
        assert coach.intensity == "normal"

    def test_normal_multiplier_is_one(self):
        """Verify the configured multiplier for 'normal' is 1.0."""
        assert INTENSITY_MULTIPLIERS["normal"] == 1.0

    def test_normal_and_explicit_normal_behave_identically(self, monkeypatch):
        """Coach(intensity='normal') must produce exactly the same suppression
        outcome as Coach() (no intensity argument)."""
        rule = _always_true_rule()
        coach_default = Coach(rules=[rule])
        coach_normal = Coach(rules=[_always_true_rule()], intensity="normal")
        snapshot = _make_snapshot()

        normal_warmup = settings.global_nudge_warmup_seconds  # 120

        # Both should be blocked during warmup
        monkeypatch.setattr(coach_module.time, "time", lambda: 10_000.0)
        assert coach_default.check(snapshot, elapsed_seconds=normal_warmup - 1) == []
        assert coach_normal.check(snapshot, elapsed_seconds=normal_warmup - 1) == []

        # Both should fire after warmup
        monkeypatch.setattr(coach_module.time, "time", lambda: 10_001.0)
        assert len(coach_default.check(snapshot, elapsed_seconds=normal_warmup + 1)) == 1
        assert len(coach_normal.check(snapshot, elapsed_seconds=normal_warmup + 1)) == 1

    def test_unknown_intensity_falls_back_to_normal(self):
        """An unrecognized intensity string must silently fall back to 'normal'."""
        coach = Coach(intensity="ultra_mega_extreme")
        assert coach.intensity == "normal"
        assert coach._intensity_multiplier == INTENSITY_MULTIPLIERS["normal"]


# ---------------------------------------------------------------------------
# Test 5: Session create endpoint accepts and stores coaching_intensity
# ---------------------------------------------------------------------------

class TestSessionCreateEndpointAcceptsIntensity:
    """Verify the /api/sessions endpoint accepts coaching_intensity and
    echoes it back in the response."""

    @pytest.fixture()
    def client(self):
        with TestClient(app) as c:
            yield c

    @pytest.mark.parametrize("intensity", ["off", "subtle", "normal", "aggressive"])
    def test_create_session_accepts_all_intensities(self, client, intensity):
        """All valid CoachingIntensity values must be accepted by the endpoint."""
        resp = client.post(
            "/api/sessions",
            json={"session_type": "general", "coaching_intensity": intensity},
        )
        assert resp.status_code == 200, (
            f"Expected 200 for intensity={intensity!r}, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert data["coaching_intensity"] == intensity

    def test_create_session_defaults_to_normal_when_omitted(self, client):
        """When coaching_intensity is absent from the request, it defaults to 'normal'."""
        resp = client.post("/api/sessions", json={"session_type": "general"})
        assert resp.status_code == 200
        assert resp.json()["coaching_intensity"] == "normal"

    def test_create_session_stores_intensity_in_session_room(self, client):
        """The coaching_intensity must be stored on the SessionRoom for later use."""
        resp = client.post(
            "/api/sessions",
            json={"session_type": "practice", "coaching_intensity": "aggressive"},
        )
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        room = session_manager.get_session(session_id)
        assert room is not None
        assert room.coaching_intensity == "aggressive"

    def test_create_session_rejects_invalid_intensity(self, client):
        """An unrecognized coaching_intensity value must return 422."""
        resp = client.post(
            "/api/sessions",
            json={"session_type": "general", "coaching_intensity": "maximum_overdrive"},
        )
        assert resp.status_code == 422

    def test_session_create_request_model_has_intensity_field(self):
        """SessionCreateRequest must expose coaching_intensity with NORMAL default."""
        req = SessionCreateRequest(tutor_id="t1")
        assert req.coaching_intensity == CoachingIntensity.NORMAL

    def test_session_create_response_model_includes_intensity(self):
        """SessionCreateResponse must carry coaching_intensity back to the caller."""
        from app.session_manager import SessionManager
        mgr = SessionManager()
        resp = mgr.create_session(coaching_intensity="subtle")
        assert resp.coaching_intensity == CoachingIntensity.SUBTLE
