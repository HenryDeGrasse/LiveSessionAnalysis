import pytest
from app.session_manager import SessionManager, SessionRoom
from app.models import Role


def test_create_session():
    mgr = SessionManager()
    resp = mgr.create_session()
    assert resp.session_id
    assert resp.tutor_token
    assert resp.student_token
    assert resp.tutor_token != resp.student_token


def test_get_session():
    mgr = SessionManager()
    resp = mgr.create_session()
    room = mgr.get_session(resp.session_id)
    assert room is not None
    assert room.session_id == resp.session_id


def test_get_nonexistent_session():
    mgr = SessionManager()
    assert mgr.get_session("nonexistent") is None


def test_token_roles():
    mgr = SessionManager()
    resp = mgr.create_session()
    room = mgr.get_session(resp.session_id)
    assert room.get_role_for_token(resp.tutor_token) == Role.TUTOR
    assert room.get_role_for_token(resp.student_token) == Role.STUDENT
    assert room.get_role_for_token("invalid") is None


def test_both_connected():
    mgr = SessionManager()
    resp = mgr.create_session()
    room = mgr.get_session(resp.session_id)
    assert not room.both_connected()
    room.participants[Role.TUTOR].connected = True
    assert not room.both_connected()
    room.participants[Role.STUDENT].connected = True
    assert room.both_connected()


def test_degradation_levels():
    mgr = SessionManager()
    resp = mgr.create_session()
    room = mgr.get_session(resp.session_id)

    # Normal processing
    for _ in range(5):
        room.record_processing_time(100.0)
    assert room.check_degradation() == 0

    # Step 1: >250ms
    for _ in range(5):
        room.record_processing_time(300.0)
    assert room.check_degradation() == 1
    assert room.current_fps == 2

    # Step 2: >350ms
    for _ in range(5):
        room.record_processing_time(400.0)
    assert room.check_degradation() == 2
    assert room.current_fps == 1

    # Step 3: >450ms
    for _ in range(5):
        room.record_processing_time(500.0)
    assert room.check_degradation() == 3


def test_video_processing_rate_limit_drops_frames():
    room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
    room.current_fps = 1

    assert room.should_process_video_frame(Role.TUTOR, now=0.0) is True
    assert room.should_process_video_frame(Role.TUTOR, now=0.2) is False
    assert room.should_process_video_frame(Role.TUTOR, now=1.2) is True
    assert room.dropped_frames == 1


def test_latency_stage_stats_are_averaged():
    room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
    room.record_processing_time(100.0)
    room.record_processing_time(200.0)
    room.record_stage_times(10.0, 50.0, 5.0, 2.0)
    room.record_stage_times(20.0, 60.0, 7.0, 3.0)
    room.record_aggregation_time(1.5)
    room.record_aggregation_time(2.5)

    stats = room.get_latency_stats()
    assert stats.avg_processing_ms == pytest.approx(150.0)
    assert stats.avg_decode_ms == pytest.approx(15.0)
    assert stats.avg_facemesh_ms == pytest.approx(55.0)
    assert stats.avg_gaze_ms == pytest.approx(6.0)
    assert stats.avg_expression_ms == pytest.approx(2.5)
    assert stats.avg_aggregation_ms == pytest.approx(2.0)


def test_latency_percentiles_use_sorted_index_percentiles():
    """Percentiles use sorted indexes: p50 at n//2 and p95 at int(n * 0.95)."""
    room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
    samples = [
        200.0,
        10.0,
        180.0,
        20.0,
        160.0,
        30.0,
        140.0,
        40.0,
        120.0,
        50.0,
        100.0,
        60.0,
        80.0,
        70.0,
        90.0,
        110.0,
        130.0,
        150.0,
        170.0,
        190.0,
    ]

    for ms in samples:
        room.record_processing_time(ms)

    p50, p95 = room.latency_percentiles()
    assert p50 == pytest.approx(110.0)
    assert p95 == pytest.approx(200.0)


def test_latency_percentiles_fall_back_to_rolling_average_with_few_samples():
    room = SessionRoom(session_id="test", tutor_token="t", student_token="s")
    room.record_processing_time(100.0)
    room.record_processing_time(200.0)
    room._latency_history = [100.0]

    p50, p95 = room.latency_percentiles()
    assert room.rolling_avg_processing_ms() == pytest.approx(150.0)
    assert p50 == pytest.approx(150.0)
    assert p95 == pytest.approx(150.0)


def test_remove_session():
    mgr = SessionManager()
    resp = mgr.create_session()
    mgr.remove_session(resp.session_id)
    assert mgr.get_session(resp.session_id) is None


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_create_session_endpoint(client):
    response = client.post("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "tutor_token" in data
    assert "student_token" in data
