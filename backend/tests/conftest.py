import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.main import app
from app.session_manager import session_manager
from app.livekit_worker import reset_livekit_analytics_workers
from app.session_runtime import reset_session_resources

# Disable LiveKit worker for unit tests — no LiveKit server is available.
# Individual test files can re-enable if they mock the connection.
settings.enable_livekit_analytics_worker = False


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def cleanup_sessions():
    """Clean up any sessions created during tests."""
    yield
    reset_livekit_analytics_workers()
    reset_session_resources()
    for sid in list(session_manager._sessions.keys()):
        session_manager.remove_session(sid)
