"""Integration-level tests for multi-participant support.

Covers:
- session_runtime.get_or_create_resources creates per-student processors
- LiveKitAnalyticsWorker._role_for_participant resolves extra student identities
- MetricsEngine populates per_student_metrics from audio updates with student_index
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.metrics_engine.engine import MetricsEngine
from app.models import Role
from app.session_manager import session_manager
from app.session_runtime import (
    _session_resources,
    get_or_create_resources,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_room(max_students: int = 3):
    resp = session_manager.create_session(max_students=max_students)
    room = session_manager.get_session(resp.session_id)
    assert room is not None
    room.started_at = 1.0
    return room


def _teardown(room):
    _session_resources.pop(room.session_id, None)
    session_manager.remove_session(room.session_id)


# ── test_session_runtime_creates_per_student_processors ──────────────────────


def test_session_runtime_creates_per_student_processors():
    """get_or_create_resources with max_students=3 creates video_student_1, audio_student_1,
    video_student_2, audio_student_2 in addition to the primary student processors."""
    room = _make_room(max_students=3)
    try:
        resources = get_or_create_resources(room)

        # Primary student processors must exist
        assert "video_student" in resources
        assert "audio_student" in resources

        # Extra student processors for index 1 and 2 must exist
        assert "video_student_1" in resources, "Missing video_student_1"
        assert "audio_student_1" in resources, "Missing audio_student_1"
        assert "video_student_2" in resources, "Missing video_student_2"
        assert "audio_student_2" in resources, "Missing audio_student_2"

        # Tutor processors must still be present
        assert "video_tutor" in resources
        assert "audio_tutor" in resources
    finally:
        _teardown(room)


# ── test_livekit_worker_resolves_extra_student_role ──────────────────────────


def test_livekit_worker_resolves_extra_student_role():
    """LiveKitAnalyticsWorker._role_for_participant returns (Role.STUDENT, 1)
    for an identity ending in ':student:1'."""
    # Import here to avoid pulling in livekit SDK at module level unless needed
    from app.livekit_worker import LiveKitAnalyticsWorker

    room = _make_room(max_students=2)
    try:
        worker = LiveKitAnalyticsWorker(session=room)
        sid = room.session_id

        # Build a fake participant mock for extra student (index 1)
        participant_1 = MagicMock()
        participant_1.identity = f"{sid}:student:1"

        result = worker._role_for_participant(participant_1)
        assert result == Role.STUDENT, (
            f"Expected Role.STUDENT, got {result!r}"
        )

        # Also verify _role_and_index_for_participant returns the full tuple
        result_with_index = worker._role_and_index_for_participant(participant_1)
        assert result_with_index == (Role.STUDENT, 1), (
            f"Expected (Role.STUDENT, 1), got {result_with_index!r}"
        )

        # Tutor identity
        tutor_participant = MagicMock()
        tutor_participant.identity = f"{sid}:tutor"
        assert worker._role_for_participant(tutor_participant) == Role.TUTOR
    finally:
        _teardown(room)


# ── test_metrics_engine_tracks_extra_students ─────────────────────────────────


def test_metrics_engine_tracks_extra_students():
    """Feeding audio updates with student_index=1 populates per_student_metrics in the snapshot."""
    engine = MetricsEngine("test-multi-participant-integration")

    # Feed audio for extra student at index 1
    engine.update_audio(Role.STUDENT, 1.0, True, 0.6, 0.4, student_index=1)
    engine.update_gaze(Role.STUDENT, 1.5, True, student_index=1)

    snapshot = engine.compute_snapshot()

    assert snapshot.per_student_metrics is not None, (
        "per_student_metrics should be populated when extra students have data"
    )
    assert "1" in snapshot.per_student_metrics, (
        "Student index 1 should appear as key '1' in per_student_metrics"
    )

    metrics = snapshot.per_student_metrics["1"]
    assert "eye_contact_score" in metrics
    assert "talk_time_percent" in metrics
    assert "is_speaking" in metrics

    # Primary student (index 0) should NOT appear in per_student_metrics
    # (it is in the main student_metrics field)
    assert "0" not in snapshot.per_student_metrics
