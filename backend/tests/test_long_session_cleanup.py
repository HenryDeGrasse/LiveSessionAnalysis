"""Tests for long-session behavior and data retention/cleanup.

Covers:
- Session store cleanup_expired() enforcement
- Session data persistence and loading
- Energy baseline tracking over extended periods
- Speaking time windowed tracking accuracy
"""
from __future__ import annotations

import json
import os
import time
import tempfile
from datetime import datetime, timedelta

import pytest

from app.analytics.session_store import SessionStore
from app.analytics.summary import generate_summary
from app.config import settings
from app.metrics_engine.energy import EnergyTracker
from app.metrics_engine.speaking_time import SpeakingTimeTracker
from app.models import (
    MetricsSnapshot,
    ParticipantMetrics,
    SessionMetrics,
    Nudge,
    NudgePriority,
)


class TestRetentionCleanup:
    """Test data retention enforcement via cleanup_expired."""

    def test_cleanup_removes_old_sessions(self):
        """Sessions older than retention period should be deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(tmpdir)
            # Create a fake session file with an old end_time
            old_summary = {
                "session_id": "old-session",
                "tutor_id": "",
                "start_time": "2020-01-01T00:00:00",
                "end_time": "2020-01-01T01:00:00",
                "duration_seconds": 3600,
                "session_type": "general",
                "talk_time_ratio": {"tutor": 0.6, "student": 0.4},
                "avg_eye_contact": {"tutor": 0.7, "student": 0.5},
                "avg_energy": {"tutor": 0.6, "student": 0.5},
                "total_interruptions": 2,
                "engagement_score": 65.0,
                "flagged_moments": [],
                "timeline": {},
                "recommendations": [],
                "nudges_sent": 0,
                "degradation_events": 0,
            }
            with open(os.path.join(tmpdir, "old-session.json"), "w") as f:
                json.dump(old_summary, f)

            deleted = store.cleanup_expired(retention_days=30)
            assert deleted == 1
            assert not os.path.exists(os.path.join(tmpdir, "old-session.json"))

    def test_cleanup_keeps_recent_sessions(self):
        """Sessions within retention period should be kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(tmpdir)
            recent_summary = {
                "session_id": "recent-session",
                "tutor_id": "",
                "start_time": datetime.utcnow().isoformat(),
                "end_time": datetime.utcnow().isoformat(),
                "duration_seconds": 3600,
                "session_type": "general",
                "talk_time_ratio": {"tutor": 0.6, "student": 0.4},
                "avg_eye_contact": {"tutor": 0.7, "student": 0.5},
                "avg_energy": {"tutor": 0.6, "student": 0.5},
                "total_interruptions": 2,
                "engagement_score": 65.0,
                "flagged_moments": [],
                "timeline": {},
                "recommendations": [],
                "nudges_sent": 0,
                "degradation_events": 0,
            }
            with open(os.path.join(tmpdir, "recent-session.json"), "w") as f:
                json.dump(recent_summary, f)

            deleted = store.cleanup_expired(retention_days=30)
            assert deleted == 0
            assert os.path.exists(os.path.join(tmpdir, "recent-session.json"))

    def test_cleanup_mixed_old_and_new(self):
        """Only old sessions should be removed, recent ones kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(tmpdir)

            # Old session (full valid SessionSummary JSON)
            old = {
                "session_id": "old-one",
                "tutor_id": "",
                "start_time": "2020-06-01T00:00:00",
                "end_time": "2020-06-01T01:00:00",
                "duration_seconds": 3600,
            }
            with open(os.path.join(tmpdir, "old-one.json"), "w") as f:
                json.dump(old, f)

            # Recent session (full valid SessionSummary JSON)
            now_str = datetime.utcnow().isoformat()
            recent = {
                "session_id": "new-one",
                "tutor_id": "",
                "start_time": now_str,
                "end_time": now_str,
                "duration_seconds": 3600,
            }
            with open(os.path.join(tmpdir, "new-one.json"), "w") as f:
                json.dump(recent, f)

            deleted = store.cleanup_expired(retention_days=90)
            assert deleted == 1
            assert not os.path.exists(os.path.join(tmpdir, "old-one.json"))
            assert os.path.exists(os.path.join(tmpdir, "new-one.json"))

    def test_cleanup_handles_malformed_json(self):
        """Malformed JSON files should not crash cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(tmpdir)
            with open(os.path.join(tmpdir, "bad.json"), "w") as f:
                f.write("{not valid json")

            # Should not raise
            deleted = store.cleanup_expired(retention_days=30)
            assert deleted == 0

    def test_cleanup_handles_missing_end_time(self):
        """Files without end_time should not crash cleanup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(tmpdir)
            with open(os.path.join(tmpdir, "no-end.json"), "w") as f:
                json.dump({"session_id": "no-end"}, f)

            deleted = store.cleanup_expired(retention_days=30)
            assert deleted == 0

    def test_cleanup_uses_default_retention_days(self):
        """Should use settings.session_retention_days if not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(tmpdir)
            old = {
                "session_id": "ancient",
                "tutor_id": "",
                "start_time": "2000-01-01T00:00:00",
                "end_time": "2000-01-01T01:00:00",
                "duration_seconds": 3600,
            }
            with open(os.path.join(tmpdir, "ancient.json"), "w") as f:
                json.dump(old, f)

            # Default is 90 days — year 2000 is way beyond that
            deleted = store.cleanup_expired()
            assert deleted == 1


class TestEnergyBaseline:
    """Test energy tracker baseline behavior over extended periods."""

    def test_baseline_stabilizes_after_warmup(self):
        """Baseline should stabilize after sufficient data points."""
        tracker = EnergyTracker()
        # Feed 15 samples at 0.7 energy
        for _ in range(15):
            tracker.update_audio(rms_energy=0.7, speech_rate_proxy=0.5); tracker.update_expression(0.6)
        baseline = tracker.baseline
        assert baseline > 0.0
        assert abs(baseline - tracker.score) < 0.3

    def test_drop_from_baseline_detected(self):
        """A sudden drop from baseline should be measurable."""
        tracker = EnergyTracker(window_size=5)  # Small window so drop is visible fast
        # Build a high baseline (need 10+ for baseline calc)
        for _ in range(15):
            tracker.update_audio(rms_energy=0.8, speech_rate_proxy=0.7)
            tracker.update_expression(0.7)
        high_baseline = tracker.baseline
        assert high_baseline > 0.3

        # Drop energy — need enough samples to flush the rolling audio window
        for _ in range(10):
            tracker.update_audio(rms_energy=0.05, speech_rate_proxy=0.05)
            tracker.update_expression(0.05)

        drop = tracker.drop_from_baseline
        assert drop > 0.1

    def test_baseline_requires_minimum_samples(self):
        """Baseline should use default value before enough samples."""
        tracker = EnergyTracker()
        # Only a few samples
        for _ in range(3):
            tracker.update_audio(rms_energy=0.5, speech_rate_proxy=0.5); tracker.update_expression(0.5)
        # Default baseline is 0.5
        assert tracker.baseline == 0.5

    def test_session_average_tracks_history(self):
        """session_average should reflect actual history, not just current."""
        tracker = EnergyTracker()
        # High energy first
        for _ in range(10):
            tracker.update_audio(rms_energy=0.9, speech_rate_proxy=0.8); tracker.update_expression(0.8)
        # Low energy next
        for _ in range(10):
            tracker.update_audio(rms_energy=0.1, speech_rate_proxy=0.1); tracker.update_expression(0.1)

        avg = tracker.session_average
        # Should be between high and low, not just the current low value
        assert 0.2 < avg < 0.8


class TestSpeakingTimeWindowed:
    """Test windowed speaking time tracking for coaching rules."""

    def test_recent_tutor_ratio_empty(self):
        """Empty tracker should return 0.0."""
        tracker = SpeakingTimeTracker()
        assert tracker.recent_tutor_ratio() == 0.0

    def test_recent_tutor_ratio_tracks_window(self):
        """Recent ratio should only consider events within the window."""
        tracker = SpeakingTimeTracker(recent_window_seconds=10.0)
        now = time.time()

        # Add old events (should be pruned) — tutor only
        for i in range(5):
            tracker.update(
                now - 20 + i,
                tutor_speaking=True,
                student_speaking=False,
                chunk_duration_s=1.0,
            )

        # Add recent events — both speaking
        for i in range(5):
            tracker.update(
                now - 5 + i,
                tutor_speaking=True,
                student_speaking=True,
                chunk_duration_s=1.0,
            )

        ratio = tracker.recent_tutor_ratio(now)
        # Recent: 5s tutor + 5s student overlap → tutor ratio ~50%
        assert 0.3 < ratio < 0.7

    def test_recent_ratio_with_only_tutor_speaking(self):
        """If only tutor speaks recently, ratio should be ~1.0."""
        tracker = SpeakingTimeTracker(recent_window_seconds=60.0)
        now = time.time()

        for i in range(10):
            tracker.update(
                now - 10 + i,
                tutor_speaking=True,
                student_speaking=False,
                chunk_duration_s=1.0,
            )

        ratio = tracker.recent_tutor_ratio(now)
        assert ratio > 0.9

    def test_recent_student_ratio(self):
        """recent_student_ratio should complement tutor ratio."""
        tracker = SpeakingTimeTracker(recent_window_seconds=60.0)
        now = time.time()

        for i in range(10):
            tracker.update(
                now - 10 + i,
                tutor_speaking=False,
                student_speaking=True,
                chunk_duration_s=1.0,
            )

        assert tracker.recent_student_ratio(now) > 0.9
        assert tracker.recent_tutor_ratio(now) < 0.1


class TestSummaryWithNewFields:
    """Test that summary generation works with the updated models."""

    def test_summary_uses_last_snapshot_talk_ratio(self):
        """Talk ratio should come from last snapshot, not averaged."""
        snapshots = []
        for i in range(10):
            # Tutor talk increases over time
            tutor_pct = 0.3 + i * 0.05  # 0.3 → 0.75
            student_pct = 1.0 - tutor_pct
            snapshots.append(MetricsSnapshot(
                session_id="test",
                tutor=ParticipantMetrics(
                    eye_contact_score=0.7,
                    talk_time_percent=tutor_pct,
                    energy_score=0.6,
                    is_speaking=i % 2 == 0,
                ),
                student=ParticipantMetrics(
                    eye_contact_score=0.5,
                    talk_time_percent=student_pct,
                    energy_score=0.5,
                    is_speaking=i % 2 == 1,
                ),
                session=SessionMetrics(
                    interruption_count=i,
                    engagement_trend="stable",
                    engagement_score=60.0,
                ),
            ))

        summary = generate_summary("test", snapshots)
        # Should use the LAST snapshot's values, not averaged
        last_tutor = snapshots[-1].tutor.talk_time_percent
        assert abs(summary.talk_time_ratio["tutor"] - last_tutor) < 0.01

    def test_summary_with_nudges(self):
        """Summary should count nudges correctly."""
        snapshots = [MetricsSnapshot(
            session_id="test",
            tutor=ParticipantMetrics(
                eye_contact_score=0.7,
                talk_time_percent=0.5,
                energy_score=0.6,
                is_speaking=False,
            ),
            student=ParticipantMetrics(
                eye_contact_score=0.5,
                talk_time_percent=0.5,
                energy_score=0.5,
                is_speaking=False,
            ),
            session=SessionMetrics(
                interruption_count=0,
                engagement_trend="stable",
                engagement_score=70.0,
            ),
        )]
        nudges = [
            Nudge(
                nudge_type="student_silence",
                message="Test nudge",
                priority=NudgePriority.MEDIUM,
                trigger_metrics={"silence": 180},
            ),
            Nudge(
                nudge_type="low_eye_contact",
                message="Another nudge",
                priority=NudgePriority.LOW,
                trigger_metrics={"eye_contact": 0.2},
            ),
        ]
        summary = generate_summary("test", snapshots, nudges=nudges)
        assert summary.nudges_sent == 2
