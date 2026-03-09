"""Protocol fuzz tests for WebSocket binary message handling.

Tests that malformed, truncated, or unexpected binary payloads
are handled gracefully without crashing the server.
"""
from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.session_manager import session_manager


@pytest.fixture(autouse=True)
def cleanup_sessions():
    """Clean up sessions after each test."""
    yield
    for sid in list(session_manager._sessions.keys()):
        session_manager.remove_session(sid)


def _create_session(client: TestClient):
    """Helper to create a session and return (session_id, tutor_token, student_token)."""
    resp = client.post("/api/sessions")
    data = resp.json()
    return data["session_id"], data["tutor_token"], data["student_token"]


class TestMalformedMessages:
    """Test that malformed binary messages don't crash the server."""

    def test_empty_payload(self):
        """Empty bytes should be silently ignored."""
        client = TestClient(app)
        sid, tutor_token, _ = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws:
            ws.send_bytes(b"")
            # Should not crash — connection stays alive

    def test_single_byte_payload(self):
        """A single byte (just the type header, no data) should be ignored."""
        client = TestClient(app)
        sid, tutor_token, _ = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws:
            ws.send_bytes(b"\x01")  # Video type, no payload
            # Should not crash

    def test_unknown_message_type(self):
        """Unknown message type byte should be silently dropped."""
        client = TestClient(app)
        sid, tutor_token, _ = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws:
            ws.send_bytes(b"\xFF" + b"some payload data")
            # Unknown type — should be ignored, not crash

    def test_invalid_jpeg_bytes(self):
        """Invalid JPEG data should not crash the video processor."""
        client = TestClient(app)
        sid, tutor_token, student_token = _create_session(client)
        # Connect both so session starts
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws_tutor:
            with client.websocket_connect(
                f"/ws/session/{sid}?token={student_token}"
            ) as ws_student:
                # Send garbage as a video frame
                ws_tutor.send_bytes(b"\x01" + b"not a jpeg at all")
                # Should handle gracefully

    def test_truncated_audio_pcm(self):
        """Audio chunk smaller than expected should not crash."""
        client = TestClient(app)
        sid, tutor_token, student_token = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws_tutor:
            with client.websocket_connect(
                f"/ws/session/{sid}?token={student_token}"
            ) as ws_student:
                # Send very short PCM (less than 30ms of 16kHz 16-bit mono = 960 bytes)
                ws_tutor.send_bytes(b"\x02" + b"\x00\x01\x02")
                # Should handle gracefully

    def test_large_payload(self):
        """Very large payload should be handled (or rejected) gracefully."""
        client = TestClient(app)
        sid, tutor_token, _ = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws:
            # Send 1MB of random bytes as video
            ws.send_bytes(b"\x01" + b"\x00" * (1024 * 1024))
            # Should not crash

    def test_zero_filled_video_frame(self):
        """All-zero bytes as video data should be handled gracefully."""
        client = TestClient(app)
        sid, tutor_token, student_token = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws_tutor:
            with client.websocket_connect(
                f"/ws/session/{sid}?token={student_token}"
            ) as ws_student:
                ws_tutor.send_bytes(b"\x01" + bytes(1024))
                # Should handle gracefully

    def test_valid_audio_chunk(self):
        """Valid-sized 16-bit PCM audio chunk should process without error."""
        client = TestClient(app)
        sid, tutor_token, student_token = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws_tutor:
            with client.websocket_connect(
                f"/ws/session/{sid}?token={student_token}"
            ) as ws_student:
                # 30ms of 16kHz 16-bit mono PCM = 480 samples * 2 bytes = 960 bytes
                silence_pcm = b"\x00" * 960
                ws_tutor.send_bytes(b"\x02" + silence_pcm)
                # Should process without error

    def test_rapid_fire_messages(self):
        """Many messages sent rapidly should not crash."""
        client = TestClient(app)
        sid, tutor_token, _ = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws:
            for _ in range(50):
                ws.send_bytes(b"\x01" + b"\xFF\xD8\xFF\xE0" + b"\x00" * 100)
            # Should handle all without crashing


class TestAuthenticationEdgeCases:
    """Test WebSocket authentication edge cases."""

    def test_missing_token_rejected(self):
        """Connection without token should be rejected."""
        client = TestClient(app)
        sid, _, _ = _create_session(client)
        # FastAPI requires the token query param — should fail
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/session/{sid}"):
                pass

    def test_wrong_token_rejected(self):
        """Connection with wrong token should be rejected."""
        client = TestClient(app)
        sid, _, _ = _create_session(client)
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/ws/session/{sid}?token=wrong-token"
            ):
                pass

    def test_duplicate_role_rejected(self):
        """Second connection with same role token should be rejected."""
        client = TestClient(app)
        sid, tutor_token, _ = _create_session(client)
        with client.websocket_connect(
            f"/ws/session/{sid}?token={tutor_token}"
        ) as ws1:
            with pytest.raises(Exception):
                with client.websocket_connect(
                    f"/ws/session/{sid}?token={tutor_token}"
                ) as ws2:
                    pass

    def test_nonexistent_session_rejected(self):
        """Connection to nonexistent session should be rejected."""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/ws/session/does-not-exist?token=any"
            ):
                pass
