import json
from datetime import datetime, timedelta

from app.models import MetricsSnapshot, Nudge, ParticipantMetrics, SessionMetrics, SessionSummary
from app.observability.trace_recorder import SessionTraceRecorder
from app.observability.trace_store import SessionTraceStore


class _FakeClock:
    def __init__(self):
        self._start = datetime(2025, 1, 1, 12, 0, 0)
        self._offset_s = 0.0

    def now(self) -> datetime:
        return self._start + timedelta(seconds=self._offset_s)

    def monotonic(self) -> float:
        return self._offset_s

    def advance(self, seconds: float):
        self._offset_s += seconds


def _make_snapshot(session_id: str = "session-1") -> MetricsSnapshot:
    return MetricsSnapshot(
        session_id=session_id,
        timestamp=datetime(2025, 1, 1, 12, 5, 0),
        tutor=ParticipantMetrics(talk_time_percent=0.9, eye_contact_score=0.7),
        student=ParticipantMetrics(talk_time_percent=0.1, eye_contact_score=0.4),
        session=SessionMetrics(
            recent_tutor_talk_percent=0.9,
            engagement_score=62.0,
        ),
    )


def _make_summary(session_id: str = "session-1") -> SessionSummary:
    return SessionSummary(
        session_id=session_id,
        tutor_id="alice",
        session_type="practice",
        start_time=datetime(2025, 1, 1, 12, 0, 0),
        end_time=datetime(2025, 1, 1, 12, 5, 0),
        duration_seconds=300.0,
        talk_time_ratio={"tutor": 0.9, "student": 0.1},
        avg_eye_contact={"tutor": 0.7, "student": 0.4},
        avg_energy={"tutor": 0.5, "student": 0.4},
        total_interruptions=0,
        engagement_score=62.0,
    )


def test_trace_store_appends_ndjson_records(tmp_path):
    store = SessionTraceStore(str(tmp_path))

    store.append_record("session-1", {"kind": "event", "seq": 1})
    store.append_record("session-1", {"kind": "signal", "seq": 2})

    path = store.ndjson_path("session-1")
    assert path.exists()

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"kind": "event", "seq": 1}
    assert json.loads(lines[1]) == {"kind": "signal", "seq": 2}


def test_trace_recorder_sanitizes_webrtc_payloads_and_persists_trace(tmp_path):
    clock = _FakeClock()
    store = SessionTraceStore(str(tmp_path))
    recorder = SessionTraceRecorder(
        session_id="session-1",
        tutor_id="alice",
        session_type="practice",
        store=store,
        now_fn=clock.now,
        monotonic_fn=clock.monotonic,
        capture_mode="eval",
    )

    recorder.mark_started()
    recorder.record_event("tutor_connected", role="tutor")
    clock.advance(0.25)
    recorder.record_webrtc_signal(
        role="tutor",
        signal_type="offer",
        payload={"type": "offer", "sdp": "super-secret-sdp"},
    )
    clock.advance(0.25)
    recorder.record_visual_signal(
        role="student",
        face_present=True,
        gaze_on_camera=False,
        attention_state="SCREEN_ENGAGED",
        confidence=0.86,
    )
    clock.advance(0.25)
    recorder.record_audio_signal(
        role="student",
        speech_active=True,
        rms_db=-28.0,
        noise_floor_db=-42.0,
    )
    recorder.record_metrics_snapshot(_make_snapshot())
    recorder.record_nudge(
        Nudge(
            nudge_type="tutor_overtalk",
            message="Ask the student a question.",
        )
    )
    recorder.record_coaching_decision(
        candidate_nudges=["tutor_overtalk"],
        emitted_nudge="tutor_overtalk",
        metrics_index=0,
        trigger_features={"recent_tutor_talk_percent": 0.9},
        candidates_evaluated=["check_for_understanding", "tutor_overtalk"],
        fired_rule="tutor_overtalk",
    )

    trace = recorder.finalize(summary=_make_summary())

    assert trace.started_at == datetime(2025, 1, 1, 12, 0, 0)
    assert trace.ended_at == datetime(2025, 1, 1, 12, 0, 0, 750000)
    assert [event.seq for event in trace.events] == [1, 2]
    assert trace.events[1].t_ms == 250
    assert trace.events[1].data["signal_type"] == "offer"
    assert trace.events[1].data["payload_bytes"] > 0
    assert "payload" not in trace.events[1].data
    assert trace.visual_signals[0].t_ms == 500
    assert trace.audio_signals[0].t_ms == 750
    assert trace.coaching_decisions[0].metrics_index == 0
    assert trace.coaching_decisions[0].candidates_evaluated == ["check_for_understanding", "tutor_overtalk"]
    assert trace.coaching_decisions[0].fired_rule == "tutor_overtalk"
    assert trace.summary.session_type == "practice"
    assert trace.config_hash

    saved = store.load("session-1")
    assert saved is not None
    assert saved.summary.session_id == "session-1"

    serialized = saved.model_dump_json()
    assert "super-secret-sdp" not in serialized
