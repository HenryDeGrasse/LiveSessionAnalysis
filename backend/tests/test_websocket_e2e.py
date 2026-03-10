"""End-to-end WebSocket tests using FastAPI TestClient."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.session_manager import session_manager
from app.config import settings
from app.analytics import router as analytics_router
from app.analytics.session_store import SessionStore


@pytest.fixture(autouse=True)
def cleanup_sessions():
    """Clean up sessions after each test."""
    yield
    for sid in list(session_manager._sessions.keys()):
        session_manager.remove_session(sid)


class TestSessionCreation:
    def test_create_session_returns_tokens(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "tutor_token" in data
        assert "student_token" in data
        assert data["tutor_token"] != data["student_token"]

    def test_create_session_accepts_metadata(self):
        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={"tutor_id": "alice", "session_type": "practice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.tutor_id == "alice"
        assert room.session_type == "practice"
        assert room.media_provider.value == "livekit"
        assert data["media_provider"] == "livekit"
        assert data["livekit_room_name"] is not None

    def test_create_session_accepts_livekit_provider(self, monkeypatch):
        monkeypatch.setattr(settings, "enable_livekit", True)
        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={
                "tutor_id": "alice",
                "session_type": "practice",
                "media_provider": "livekit",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.media_provider.value == "livekit"
        assert data["media_provider"] == "livekit"
        assert data["livekit_room_name"] == room.livekit_room_name

    def test_create_session_rejects_livekit_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "enable_livekit", False)
        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={"media_provider": "livekit"},
        )
        assert resp.status_code == 400

    def test_session_info_after_creation(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()
        info_resp = client.get(
            f"/api/sessions/{data['session_id']}/info?token={data['tutor_token']}"
        )
        assert info_resp.status_code == 200
        info = info_resp.json()
        assert info["session_id"] == data["session_id"]
        assert info["tutor_connected"] is False
        assert info["student_connected"] is False
        assert info["ended"] is False
        assert info["role"] == "tutor"
        assert info["media_provider"] == "livekit"
        assert info["livekit_room_name"] is not None

    def test_end_session_with_valid_token(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()

        end_resp = client.post(
            f"/api/sessions/{data['session_id']}/end?token={data['tutor_token']}"
        )
        assert end_resp.status_code == 200
        payload = end_resp.json()
        assert payload["status"] == "ended"
        assert payload["ended"] is True
        assert payload["ended_by"] == "tutor"

        room = session_manager.get_session(data["session_id"])
        assert room is not None
        assert room.ended_at is not None

    def test_end_session_rejects_invalid_token(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()

        end_resp = client.post(
            f"/api/sessions/{data['session_id']}/end?token=bad-token"
        )
        assert end_resp.status_code == 403

    def test_livekit_token_rejects_non_livekit_session(self, monkeypatch):
        monkeypatch.setattr(settings, "enable_livekit", True)
        monkeypatch.setattr(settings, "livekit_url", "ws://127.0.0.1:7880")
        monkeypatch.setattr(settings, "livekit_api_key", "devkey")
        monkeypatch.setattr(settings, "livekit_api_secret", "secret")

        client = TestClient(app)
        resp = client.post("/api/sessions", json={"media_provider": "custom_webrtc"})
        data = resp.json()

        token_resp = client.post(
            f"/api/sessions/{data['session_id']}/livekit-token?token={data['tutor_token']}"
        )
        assert token_resp.status_code == 400

    def test_livekit_token_returns_join_payload(self, monkeypatch):
        monkeypatch.setattr(settings, "enable_livekit", True)
        monkeypatch.setattr(settings, "livekit_url", "ws://127.0.0.1:7880")
        monkeypatch.setattr(settings, "livekit_api_key", "devkey")
        monkeypatch.setattr(settings, "livekit_api_secret", "secret")

        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={"media_provider": "livekit"},
        )
        data = resp.json()

        token_resp = client.post(
            f"/api/sessions/{data['session_id']}/livekit-token?token={data['tutor_token']}"
        )
        assert token_resp.status_code == 200
        payload = token_resp.json()
        assert payload["url"] == "ws://127.0.0.1:7880"
        assert payload["room_name"] == data["livekit_room_name"]
        assert payload["identity"] == f"{data['session_id']}:tutor"
        assert payload["token"]
        assert payload["expires_at"] > 0

    def test_end_session_persists_empty_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "session_data_dir", str(tmp_path))
        monkeypatch.setattr(analytics_router, "store", SessionStore(str(tmp_path)))

        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={"tutor_id": "alice", "session_type": "practice"},
        )
        data = resp.json()

        end_resp = client.post(
            f"/api/sessions/{data['session_id']}/end?token={data['tutor_token']}"
        )
        assert end_resp.status_code == 200

        detail_resp = client.get(f"/api/analytics/sessions/{data['session_id']}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["tutor_id"] == "alice"
        assert detail["session_type"] == "practice"
        assert detail["media_provider"] == "livekit"
        assert detail["duration_seconds"] == 0

    def test_session_info_not_found(self):
        client = TestClient(app)
        resp = client.get("/api/sessions/nonexistent/info")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"


class TestWebSocketConnection:
    def test_connect_with_invalid_session(self):
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/session/fake?token=bad"):
                pass

    def test_connect_with_invalid_token(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/ws/session/{data['session_id']}?token=invalid"
            ):
                pass

    def test_tutor_connects_successfully(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()
        with client.websocket_connect(
            f"/ws/session/{data['session_id']}?token={data['tutor_token']}"
        ) as ws:
            # Connection established
            assert ws is not None

    def test_client_status_updates_participant_state(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()
        with client.websocket_connect(
            f"/ws/session/{data['session_id']}?token={data['tutor_token']}"
        ) as ws:
            ws.send_text(
                '{"type":"client_status","data":{"audio_muted":true,"video_enabled":false,"tab_hidden":true}}'
            )
            room = session_manager.get_session(data["session_id"])
            assert room is not None
            tutor_role = room.get_role_for_token(data["tutor_token"])
            assert tutor_role is not None

            deadline = time.time() + 0.2
            while time.time() < deadline:
                tutor = room.participants[tutor_role]
                if tutor.audio_muted and not tutor.video_enabled and tutor.tab_hidden:
                    break
                time.sleep(0.01)

            tutor = room.participants[tutor_role]
            assert tutor.audio_muted is True
            assert tutor.video_enabled is False
            assert tutor.tab_hidden is True

    def test_student_disconnect_and_reconnect_notifies_tutor(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()

        from app.config import settings
        original_interval = settings.metrics_emit_interval_seconds
        settings.metrics_emit_interval_seconds = 30.0

        try:
            with client.websocket_connect(
                f"/ws/session/{data['session_id']}?token={data['tutor_token']}"
            ) as tutor_ws:
                with client.websocket_connect(
                    f"/ws/session/{data['session_id']}?token={data['student_token']}"
                ):
                    ready = tutor_ws.receive_json()
                    assert ready["type"] == "participant_ready"
                    assert ready["data"]["role"] == "student"

                disconnected = tutor_ws.receive_json()
                assert disconnected["type"] == "participant_disconnected"
                assert disconnected["data"]["role"] == "student"

                with client.websocket_connect(
                    f"/ws/session/{data['session_id']}?token={data['student_token']}"
                ):
                    reconnected = tutor_ws.receive_json()
                    assert reconnected["type"] == "participant_reconnected"
                    assert reconnected["data"]["role"] == "student"

                    ready_again = tutor_ws.receive_json()
                    assert ready_again["type"] == "participant_ready"
                    assert ready_again["data"]["role"] == "student"
        finally:
            settings.metrics_emit_interval_seconds = original_interval

    # test_webrtc_signaling_relay_between_roles removed —
    # WebRTC signal relay was deleted; LiveKit handles all media transport.


class TestHealthEndpoint:
    def test_health_check(self):
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDebugEndpoints:
    def test_latency_requires_session_id(self):
        client = TestClient(app)
        resp = client.get("/api/debug/latency")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "session_id required"

    def test_latency_not_found(self):
        client = TestClient(app)
        resp = client.get("/api/debug/latency?session_id=nope")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"

    def test_stats_requires_session_id(self):
        client = TestClient(app)
        resp = client.get("/api/debug/stats")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "session_id required"

    def test_stats_for_valid_session(self):
        client = TestClient(app)
        resp = client.post("/api/sessions")
        data = resp.json()
        stats = client.get(
            f"/api/debug/stats?session_id={data['session_id']}"
        )
        assert stats.status_code == 200
        s = stats.json()
        assert "avg_processing_ms" in s
        assert "elapsed_seconds" in s
        assert "both_connected" in s


class TestAnalyticsEndpoints:
    def test_list_sessions_empty(self):
        client = TestClient(app)
        resp = client.get("/api/analytics/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_session_not_found(self):
        client = TestClient(app)
        resp = client.get("/api/analytics/sessions/nonexistent")
        assert resp.status_code == 404

    def test_recommendations_not_found(self):
        client = TestClient(app)
        resp = client.get("/api/analytics/sessions/nonexistent/recommendations")
        assert resp.status_code == 404

    def test_trends_without_tutor_id_returns_global_series(self):
        client = TestClient(app)
        resp = client.get("/api/analytics/trends")
        assert resp.status_code == 200
        assert "sessions" in resp.json()


class TestSessionTracing:
    def test_persists_privacy_safe_trace_on_session_end(self, tmp_path, monkeypatch):
        from app.observability.trace_store import SessionTraceStore

        monkeypatch.setattr(settings, "enable_session_tracing", True)
        monkeypatch.setattr(settings, "trace_dir", str(tmp_path))
        monkeypatch.setattr(settings, "metrics_emit_interval_seconds", 30.0)

        client = TestClient(app)
        resp = client.post(
            "/api/sessions",
            json={"tutor_id": "alice", "session_type": "practice"},
        )
        data = resp.json()

        with client.websocket_connect(
            f"/ws/session/{data['session_id']}?token={data['tutor_token']}"
        ) as tutor_ws:
            with client.websocket_connect(
                f"/ws/session/{data['session_id']}?token={data['student_token']}"
            ) as student_ws:
                # Drain all participant_ready messages (broadcast on both_connected)
                import time as _time
                _time.sleep(0.05)  # let broadcasts settle

                def _drain_ready(ws):
                    """Consume all participant_ready messages, return last."""
                    last = ws.receive_json()
                    assert last["type"] == "participant_ready"
                    return last

                _drain_ready(tutor_ws)
                _drain_ready(student_ws)

                end_resp = client.post(
                    f"/api/sessions/{data['session_id']}/end?token={data['tutor_token']}"
                )
                assert end_resp.status_code == 200

                def _drain_until(ws, target_type):
                    """Read messages until we get the target type."""
                    for _ in range(10):
                        msg = ws.receive_json()
                        if msg["type"] == target_type:
                            return msg
                    raise AssertionError(f"Never received {target_type}")

                tutor_end = _drain_until(tutor_ws, "session_end")
                student_end = _drain_until(student_ws, "session_end")
                assert tutor_end["type"] == "session_end"
                assert student_end["type"] == "session_end"

        store = SessionTraceStore(str(tmp_path))
        trace = store.load(data["session_id"])
        assert trace is not None
        assert trace.session_id == data["session_id"]
        assert trace.summary.tutor_id == "alice"
        assert trace.summary.session_type == "practice"
        assert trace.config_hash
        assert trace.build is not None

        event_types = [event.event_type for event in trace.events]
        assert "tutor_connected" in event_types
        assert "student_connected" in event_types
        assert "participant_ready" in event_types
        assert "session_end_requested" in event_types
        assert "session_end" in event_types
