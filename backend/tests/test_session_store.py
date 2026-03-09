from __future__ import annotations

import json
import os
import shutil
import tempfile
import pytest
from datetime import datetime, timedelta
from app.analytics.session_store import SessionStore
from app.models import SessionSummary, FlaggedMoment


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def store(temp_dir):
    return SessionStore(data_dir=temp_dir)


def _make_summary(
    session_id: str = "s1",
    tutor_id: str = "tutor1",
    engagement_score: float = 75.0,
    start_time: datetime | None = None,
    duration: float = 300.0,
    session_type: str = "general",
) -> SessionSummary:
    st = start_time or datetime.utcnow()
    return SessionSummary(
        session_id=session_id,
        tutor_id=tutor_id,
        start_time=st,
        end_time=st + timedelta(seconds=duration),
        duration_seconds=duration,
        session_type=session_type,
        talk_time_ratio={"tutor": 0.6, "student": 0.4},
        avg_eye_contact={"tutor": 0.8, "student": 0.5},
        avg_energy={"tutor": 0.7, "student": 0.6},
        total_interruptions=2,
        engagement_score=engagement_score,
        flagged_moments=[
            FlaggedMoment(
                timestamp=120.0,
                metric_name="eye_contact",
                value=0.1,
                direction="below",
                description="Student eye contact dropped",
            )
        ],
        timeline={"engagement": [70.0, 75.0, 80.0]},
        nudges_sent=3,
    )


class TestSessionStoreSaveLoad:
    def test_save_and_load(self, store):
        summary = _make_summary()
        store.save(summary)
        loaded = store.load("s1")
        assert loaded is not None
        assert loaded.session_id == "s1"
        assert loaded.engagement_score == 75.0

    def test_load_nonexistent_returns_none(self, store):
        assert store.load("nonexistent") is None

    def test_save_overwrites(self, store):
        store.save(_make_summary(engagement_score=50.0))
        store.save(_make_summary(engagement_score=90.0))
        loaded = store.load("s1")
        assert loaded.engagement_score == 90.0

    def test_file_created_on_disk(self, store, temp_dir):
        store.save(_make_summary())
        assert os.path.exists(os.path.join(temp_dir, "s1.json"))

    def test_valid_json_on_disk(self, store, temp_dir):
        store.save(_make_summary())
        with open(os.path.join(temp_dir, "s1.json")) as f:
            data = json.load(f)
        assert data["session_id"] == "s1"


class TestSessionStoreList:
    def test_list_empty(self, store):
        assert store.list_sessions() == []

    def test_list_multiple(self, store):
        for i in range(3):
            store.save(_make_summary(session_id=f"s{i}"))
        sessions = store.list_sessions()
        assert len(sessions) == 3

    def test_list_returns_sorted_by_start_time(self, store):
        base = datetime(2025, 1, 1)
        store.save(_make_summary(session_id="old", start_time=base))
        store.save(
            _make_summary(
                session_id="new", start_time=base + timedelta(hours=1)
            )
        )
        sessions = store.list_sessions()
        # Most recent first
        assert sessions[0].session_id == "new"
        assert sessions[1].session_id == "old"


class TestSessionStoreByTutor:
    def test_filter_by_tutor(self, store):
        store.save(_make_summary(session_id="s1", tutor_id="alice"))
        store.save(_make_summary(session_id="s2", tutor_id="bob"))
        store.save(_make_summary(session_id="s3", tutor_id="alice"))
        alice_sessions = store.list_sessions(tutor_id="alice")
        assert len(alice_sessions) == 2
        assert all(s.tutor_id == "alice" for s in alice_sessions)

    def test_filter_with_limit(self, store):
        for i in range(5):
            store.save(
                _make_summary(
                    session_id=f"s{i}",
                    tutor_id="alice",
                    start_time=datetime(2025, 1, 1) + timedelta(hours=i),
                )
            )
        sessions = store.list_sessions(tutor_id="alice", last_n=3)
        assert len(sessions) == 3
        # Should be the 3 most recent
        assert sessions[0].session_id == "s4"


class TestSessionStoreDelete:
    def test_delete_existing(self, store):
        store.save(_make_summary())
        assert store.delete("s1") is True
        assert store.load("s1") is None

    def test_delete_nonexistent(self, store):
        assert store.delete("nope") is False


class TestSessionStoreEdgeCases:
    def test_session_id_with_special_chars(self, store):
        """Session IDs should be sanitized for filesystem safety."""
        summary = _make_summary(session_id="test-123_abc")
        store.save(summary)
        loaded = store.load("test-123_abc")
        assert loaded is not None

    def test_corrupted_file_returns_none(self, store, temp_dir):
        """Corrupted JSON should not crash, should return None."""
        path = os.path.join(temp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("not valid json{{{")
        assert store.load("bad") is None

    def test_preserves_flagged_moments(self, store):
        summary = _make_summary()
        store.save(summary)
        loaded = store.load("s1")
        assert len(loaded.flagged_moments) == 1
        assert loaded.flagged_moments[0].metric_name == "eye_contact"

    def test_preserves_timeline(self, store):
        summary = _make_summary()
        store.save(summary)
        loaded = store.load("s1")
        assert loaded.timeline["engagement"] == [70.0, 75.0, 80.0]

    def test_preserves_session_type(self, store):
        summary = _make_summary(session_type="practice")
        store.save(summary)
        loaded = store.load("s1")
        assert loaded.session_type == "practice"
