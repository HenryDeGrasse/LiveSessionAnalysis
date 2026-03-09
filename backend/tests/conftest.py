import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.session_manager import session_manager


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
    for sid in list(session_manager._sessions.keys()):
        session_manager.remove_session(sid)
