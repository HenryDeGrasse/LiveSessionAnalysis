import time
import pytest
from app.metrics_engine.engine import MetricsEngine
from app.models import Role


def test_initial_snapshot():
    engine = MetricsEngine("test-session")
    snapshot = engine.compute_snapshot()
    assert snapshot.session_id == "test-session"
    assert snapshot.tutor.eye_contact_score == 0.5
    assert snapshot.student.eye_contact_score == 0.5
    assert snapshot.session.interruption_count == 0
    assert snapshot.degraded is False


def test_gaze_updates():
    engine = MetricsEngine("test")
    now = time.time()
    # 8 out of 10 frames on camera
    for i in range(10):
        engine.update_gaze(Role.TUTOR, now + i, on_camera=(i < 8))
    snapshot = engine.compute_snapshot()
    assert snapshot.tutor.eye_contact_score == pytest.approx(0.8, abs=0.01)


def test_audio_updates_speaking_time():
    engine = MetricsEngine("test")
    now = time.time()
    # Tutor speaks for 7 chunks while student is silent
    for i in range(7):
        engine.update_audio(Role.TUTOR, now + i * 0.03, True, 0.5, 0.5)
        engine.update_audio(Role.STUDENT, now + i * 0.03, False, 0.0, 0.0)
    # Student speaks for 3 chunks while tutor is silent
    for i in range(3):
        t = now + (7 + i) * 0.03
        engine.update_audio(Role.TUTOR, t, False, 0.0, 0.0)
        engine.update_audio(Role.STUDENT, t, True, 0.5, 0.5)
    snapshot = engine.compute_snapshot()
    assert snapshot.tutor.talk_time_percent == pytest.approx(0.7, abs=0.05)
    assert snapshot.student.talk_time_percent == pytest.approx(0.3, abs=0.05)
    assert snapshot.session.silence_duration_current >= 0.0


def test_interruption_counting():
    engine = MetricsEngine("test")
    now = time.time()

    # Student talks first long enough to establish a turn.
    for i in range(12):
        t = now + i * 0.03
        engine.update_audio(Role.TUTOR, t, False, 0.0, speech_rate_proxy=0.0)
        engine.update_audio(Role.STUDENT, t, True, 0.5, speech_rate_proxy=0.5)

    # Tutor interrupts and overlap persists long enough to count.
    for i in range(15):
        t = now + (12 + i) * 0.03
        engine.update_audio(Role.TUTOR, t, True, 0.5, speech_rate_proxy=0.5)
        engine.update_audio(Role.STUDENT, t, True, 0.5, speech_rate_proxy=0.5)

    # Student yields.
    t = now + 27 * 0.03
    engine.update_audio(Role.TUTOR, t, True, 0.5, speech_rate_proxy=0.5)
    engine.update_audio(Role.STUDENT, t, False, 0.0, speech_rate_proxy=0.0)

    snapshot = engine.compute_snapshot()
    assert snapshot.session.interruption_count >= 1
    assert snapshot.session.recent_interruptions >= 1


def test_student_silence_duration_reflects_last_student_speech():
    engine = MetricsEngine("test")
    start = time.time() - 200

    for i in range(10):
        t = start + i * 0.03
        engine.update_audio(Role.TUTOR, t, True, 0.5, 0.4)
        engine.update_audio(Role.STUDENT, t, False, 0.0, 0.0)

    snapshot = engine.compute_snapshot()
    assert snapshot.session.silence_duration_current >= 179


def test_degradation_flags():
    engine = MetricsEngine("test")
    snapshot = engine.compute_snapshot(degraded=True, gaze_unavailable=True)
    assert snapshot.degraded is True
    assert snapshot.gaze_unavailable is True


def test_engagement_score_range():
    engine = MetricsEngine("test")
    snapshot = engine.compute_snapshot()
    assert 0 <= snapshot.session.engagement_score <= 100


def test_expression_updates_energy():
    engine = MetricsEngine("test")
    engine.update_expression(Role.TUTOR, 0.9)
    engine.update_expression(Role.STUDENT, 0.1)
    snapshot = engine.compute_snapshot()
    # Tutor should have higher energy than student
    assert snapshot.tutor.energy_score >= snapshot.student.energy_score


def test_full_pipeline_integration():
    """Test full pipeline: gaze + audio -> snapshot with all metrics."""
    engine = MetricsEngine("integration-test")
    now = time.time()

    # Simulate 10 seconds of session
    for i in range(100):  # 100 audio chunks = ~3 seconds at 30ms
        t = now + i * 0.03
        # Tutor speaks for first 70%, student for last 30%
        tutor_speak = i < 70
        student_speak = i >= 70
        engine.update_audio(
            Role.TUTOR if tutor_speak else Role.STUDENT,
            t, True, 0.5, 0.3,
        )
        # Gaze: tutor on camera 90%, student 60%
        if i % 10 == 0:
            engine.update_gaze(Role.TUTOR, t, on_camera=(i % 10 < 9))
            engine.update_gaze(Role.STUDENT, t, on_camera=(i % 10 < 6))

    snapshot = engine.compute_snapshot()
    assert snapshot.session_id == "integration-test"
    assert snapshot.tutor.talk_time_percent > 0
    assert snapshot.session.engagement_score >= 0
    assert isinstance(snapshot.session.engagement_trend, str)


def test_compute_engagement_balanced():
    """Balanced session should have reasonable engagement score."""
    engine = MetricsEngine("test")
    now = time.time()

    # Good eye contact, balanced talk time, moderate energy
    for i in range(20):
        engine.update_gaze(Role.STUDENT, now + i, on_camera=True)
        engine.update_audio(Role.TUTOR, now + i * 0.03, i % 2 == 0, 0.5, 0.5)
        engine.update_audio(Role.STUDENT, now + i * 0.03, i % 2 != 0, 0.5, 0.5)

    snapshot = engine.compute_snapshot()
    # Should be above minimum
    assert snapshot.session.engagement_score > 0


def test_processing_ms_passthrough():
    engine = MetricsEngine("test")
    snapshot = engine.compute_snapshot(processing_ms=123.45)
    assert snapshot.server_processing_ms == 123.45


def test_snapshot_exposes_live_overlap_and_monologue_metrics():
    engine = MetricsEngine("test")
    now = time.time()

    # Tutor monologue starts.
    engine.update_audio(Role.TUTOR, now, True, 0.5, 0.5)
    engine.update_audio(Role.STUDENT, now, False, 0.0, 0.0)

    # Student overlaps before either speaker fully yields.
    overlap_start = now + 0.35
    engine.update_audio(Role.TUTOR, overlap_start, True, 0.5, 0.5)
    engine.update_audio(Role.STUDENT, overlap_start, True, 0.5, 0.5)

    snapshot = engine.compute_snapshot()
    assert snapshot.session.active_overlap_duration_current >= 0.0
    assert snapshot.session.active_overlap_state in {
        "none",
        "candidate",
        "backchannel",
        "meaningful",
        "hard",
        "echo_like",
    }
    assert snapshot.session.tutor_monologue_duration_current >= 0.0


def test_snapshot_exposes_attention_state():
    engine = MetricsEngine("test")
    now = time.time()

    for i in range(6):
        engine.update_visual_observation(
            Role.STUDENT,
            now + i,
            face_detected=True,
            on_camera=False,
            horizontal_angle_deg=18.0,
            vertical_angle_deg=4.0,
        )

    snapshot = engine.compute_snapshot()
    assert snapshot.student.attention_state == "SCREEN_ENGAGED"
    assert snapshot.student.attention_state_confidence > 0.0
    assert snapshot.student.visual_attention_score > 0.0


def test_compute_snapshot_accepts_explicit_current_time_for_replay():
    engine = MetricsEngine("test")
    base = 1000.0

    for i in range(10):
        engine.update_gaze(Role.STUDENT, base + i * 0.5, on_camera=(i < 7))

    snapshot = engine.compute_snapshot(current_time=base + 4.5)
    assert snapshot.student.eye_contact_score == pytest.approx(0.7, abs=0.01)


def test_snapshot_exposes_windowed_talk_time_time_since_spoke_and_degradation_reason():
    engine = MetricsEngine("test")
    base = 1000.0

    # Tutor speaks for four chunks while the student is silent.
    for i in range(4):
        t = base + i * 0.03
        engine.update_audio(Role.TUTOR, t, True, 0.5, 0.5)
        engine.update_audio(Role.STUDENT, t, False, 0.0, 0.0)

    # Student then speaks for two chunks while tutor is silent.
    for i in range(2):
        t = base + (4 + i) * 0.03
        engine.update_audio(Role.TUTOR, t, False, 0.0, 0.0)
        engine.update_audio(Role.STUDENT, t, True, 0.5, 0.5)

    # Both participants go silent so time_since_spoke_seconds can advance.
    silence_start = base + 6 * 0.03
    engine.update_audio(Role.TUTOR, silence_start, False, 0.0, 0.0)
    engine.update_audio(Role.STUDENT, silence_start, False, 0.0, 0.0)

    snapshot = engine.compute_snapshot(
        degradation_reason="skip_expression",
        current_time=silence_start + 1.0,
    )

    assert snapshot.tutor.talk_time_pct_windowed > 0.0
    assert snapshot.student.time_since_spoke_seconds == pytest.approx(1.0, abs=0.05)
    assert snapshot.degradation_reason == "skip_expression"
