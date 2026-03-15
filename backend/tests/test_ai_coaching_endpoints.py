"""Tests for AI coaching API endpoints: on-demand suggest + feedback."""
from __future__ import annotations

import json
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_coaching.copilot import AICoachingCopilot
from app.ai_coaching.feedback import (
    clear_feedback_store,
    get_feedback_store,
    get_suggestion_context,
)
from app.ai_coaching.llm_client import MockLLMClient
from app.main import app
from app.session_manager import session_manager
from app.session_runtime import get_or_create_resources
from app.transcription.buffer import TranscriptBuffer
from app.transcription.models import FinalUtterance


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _create_session() -> tuple[str, str]:
    """Create a session and return (session_id, tutor_token)."""
    resp = session_manager.create_session(
        tutor_id="tutor-1",
        student_user_id="",
        session_type="math",
        session_title="Test Session",
    )
    return resp.session_id, resp.tutor_token


def _attach_copilot(
    session_id: str,
    *,
    llm_response: str | None = None,
    should_fail: bool = False,
    max_calls_per_hour: int = 60,
) -> tuple[AICoachingCopilot, TranscriptBuffer]:
    """Attach a copilot and transcript buffer to the session room."""
    room = session_manager.get_session(session_id)
    assert room is not None

    llm = MockLLMClient(response=llm_response, should_fail=should_fail)
    copilot = AICoachingCopilot(
        llm,
        session_type="math",
        baseline_interval_s=0.0,  # No interval gating for tests
        burst_interval_s=0.0,
        max_calls_per_hour=max_calls_per_hour,
        min_transcript_words=1,  # Low threshold for tests
    )
    buf = TranscriptBuffer(window_seconds=300.0)
    # Add some transcript data
    buf.add(FinalUtterance(
        role="student",
        text="I don't understand how to add fractions with different denominators",
        start_time=0.0,
        end_time=5.0,
        utterance_id="utt-1",
    ))
    buf.add(FinalUtterance(
        role="tutor",
        text="Let's think about what a denominator means first",
        start_time=5.0,
        end_time=10.0,
        utterance_id="utt-2",
    ))

    room.ai_copilot = copilot  # type: ignore[attr-defined]
    room.transcript_buffer = buf  # type: ignore[attr-defined]
    room.started_at = time.time() - 60  # 1 minute ago

    return copilot, buf


def _valid_llm_response(**overrides: object) -> str:
    data = {
        "action": "probe",
        "topic": "fractions",
        "observation": "Student confused about denominators",
        "suggestion": "Ask student to draw a visual representation",
        "suggested_prompt": "Can you draw what one-third looks like?",
        "priority": "medium",
        "confidence": 0.85,
    }
    data.update(overrides)
    return json.dumps(data)


# --------------------------------------------------------------------------- #
# On-demand suggestion tests
# --------------------------------------------------------------------------- #


class TestOnDemandSuggest:
    """POST /api/sessions/{session_id}/suggest"""

    @pytest.mark.asyncio
    async def test_returns_valid_suggestion(self):
        """On-demand request returns a valid AI suggestion."""
        sid, tutor_token = _create_session()
        _attach_copilot(sid, llm_response=_valid_llm_response())

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "suggestion" in body
        assert body["suggestion"]["id"].startswith("ai-sug-")
        assert body["suggestion"]["action"] == "probe"
        assert body["suggestion"]["topic"] == "fractions"
        assert body["calls_remaining"] >= 0

        context = get_suggestion_context(body["suggestion"]["id"])
        assert context is not None
        assert context.session_id == sid
        assert context.context["source"] == "on_demand"
        assert context.context["suggestion"]["topic"] == "fractions"

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Returns 404 for unknown session."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/sessions/nonexistent/suggest?token=abc")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthorized_without_tutor_token(self):
        """Returns 403 without a valid tutor token."""
        sid, _tutor_token = _create_session()
        _attach_copilot(sid)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token=wrong-token"
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_student_token_rejected(self):
        """Student tokens cannot request suggestions."""
        sid, _tutor_token = _create_session()
        _attach_copilot(sid)
        room = session_manager.get_session(sid)
        student_token = room.student_tokens[0]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={student_token}"
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_budget_enforcement(self):
        """Returns 429 when the hourly budget is exhausted."""
        sid, tutor_token = _create_session()
        copilot, _buf = _attach_copilot(
            sid,
            llm_response=_valid_llm_response(),
            max_calls_per_hour=1,
        )

        # Exhaust the budget by making one call first
        now = time.time()
        copilot._call_timestamps.append(now)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )

        assert resp.status_code == 429
        assert "budget" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_no_copilot_returns_503(self):
        """Returns 503 when no copilot is attached to the session."""
        sid, tutor_token = _create_session()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_llm_failure_returns_no_suggestion(self):
        """When LLM fails, returns no_suggestion status (not an error)."""
        sid, tutor_token = _create_session()
        _attach_copilot(sid, should_fail=True)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_suggestion"

    @pytest.mark.asyncio
    async def test_on_demand_prompt_includes_explicit_help(self):
        """The on-demand prompt should include the explicit help addition."""
        sid, tutor_token = _create_session()
        room = session_manager.get_session(sid)

        llm = MockLLMClient(response=_valid_llm_response())
        copilot = AICoachingCopilot(
            llm,
            session_type="math",
            baseline_interval_s=0.0,
            burst_interval_s=0.0,
            max_calls_per_hour=60,
            min_transcript_words=1,
        )
        buf = TranscriptBuffer(window_seconds=300.0)
        buf.add(FinalUtterance(
            role="student",
            text="I need help with this problem",
            start_time=0.0,
            end_time=3.0,
            utterance_id="utt-prompt-test",
        ))
        room.ai_copilot = copilot  # type: ignore[attr-defined]
        room.transcript_buffer = buf  # type: ignore[attr-defined]
        room.started_at = time.time() - 30

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )

        assert resp.status_code == 200
        # Verify the LLM received the on-demand prompt addition
        assert llm.last_user_prompt is not None
        assert "tutor is explicitly asking for help" in llm.last_user_prompt

    @pytest.mark.asyncio
    async def test_uses_session_runtime_resources_when_room_attrs_absent(self):
        """Endpoint should work with runtime resources, not only ad-hoc room attrs."""
        sid, tutor_token = _create_session()
        room = session_manager.get_session(sid)
        assert room is not None

        llm = MockLLMClient(response=_valid_llm_response(topic="geometry"))
        copilot = AICoachingCopilot(
            llm,
            session_type="math",
            baseline_interval_s=0.0,
            burst_interval_s=0.0,
            max_calls_per_hour=60,
            min_transcript_words=1,
        )
        resources = get_or_create_resources(room)
        buf = TranscriptBuffer(window_seconds=300.0)
        buf.add(FinalUtterance(
            role="student",
            text="I need help with triangles",
            start_time=0.0,
            end_time=3.0,
            utterance_id="utt-runtime-test",
        ))
        resources["ai_copilot"] = copilot
        resources["transcript_buffer"] = buf
        room.started_at = time.time() - 30

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )

        assert resp.status_code == 200
        assert resp.json()["suggestion"]["topic"] == "geometry"


# --------------------------------------------------------------------------- #
# Feedback endpoint tests
# --------------------------------------------------------------------------- #


class TestSuggestionFeedback:
    """POST /api/sessions/{session_id}/suggestion-feedback"""

    @pytest.fixture(autouse=True)
    def _clear_feedback(self):
        clear_feedback_store()
        yield
        clear_feedback_store()

    @pytest.mark.asyncio
    async def test_feedback_persisted(self):
        """Feedback is stored in the feedback store."""
        sid, tutor_token = _create_session()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggestion-feedback?token={tutor_token}",
                json={
                    "suggestion_id": "sug-123",
                    "helpful": True,
                    "comment": "Very useful suggestion",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["suggestion_id"] == "sug-123"
        assert body["helpful"] is True

        # Verify persistence
        store = get_feedback_store()
        assert len(store) == 1
        assert store[0].session_id == sid
        assert store[0].suggestion_id == "sug-123"
        assert store[0].helpful is True
        assert store[0].comment == "Very useful suggestion"

    @pytest.mark.asyncio
    async def test_feedback_persists_suggestion_context_when_available(self):
        """Feedback should capture the original suggestion context for evals."""
        sid, tutor_token = _create_session()
        _attach_copilot(sid, llm_response=_valid_llm_response(topic="decimals"))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            suggest_resp = await ac.post(
                f"/api/sessions/{sid}/suggest?token={tutor_token}"
            )
            assert suggest_resp.status_code == 200
            suggestion_id = suggest_resp.json()["suggestion"]["id"]

            feedback_resp = await ac.post(
                f"/api/sessions/{sid}/suggestion-feedback?token={tutor_token}",
                json={
                    "suggestion_id": suggestion_id,
                    "helpful": True,
                    "comment": "Good timing",
                },
            )

        assert feedback_resp.status_code == 200
        store = get_feedback_store()
        assert len(store) == 1
        assert store[0].suggestion_context is not None
        assert store[0].suggestion_context["source"] == "on_demand"
        assert store[0].suggestion_context["suggestion"]["topic"] == "decimals"
        assert len(store[0].suggestion_context["recent_utterances"]) >= 1

    @pytest.mark.asyncio
    async def test_feedback_without_comment(self):
        """Feedback with no comment is accepted."""
        sid, tutor_token = _create_session()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggestion-feedback?token={tutor_token}",
                json={
                    "suggestion_id": "sug-456",
                    "helpful": False,
                },
            )

        assert resp.status_code == 200
        store = get_feedback_store()
        assert len(store) == 1
        assert store[0].helpful is False
        assert store[0].comment is None

    @pytest.mark.asyncio
    async def test_feedback_session_not_found(self):
        """Returns 404 for unknown session."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/sessions/nonexistent/suggestion-feedback?token=abc",
                json={"suggestion_id": "sug-1", "helpful": True},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_feedback_unauthorized(self):
        """Returns 403 without a valid tutor token."""
        sid, _tutor_token = _create_session()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/sessions/{sid}/suggestion-feedback?token=wrong",
                json={"suggestion_id": "sug-1", "helpful": True},
            )

        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_multiple_feedback_persisted(self):
        """Multiple feedback records are all persisted."""
        sid, tutor_token = _create_session()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            for i in range(3):
                resp = await ac.post(
                    f"/api/sessions/{sid}/suggestion-feedback?token={tutor_token}",
                    json={
                        "suggestion_id": f"sug-{i}",
                        "helpful": i % 2 == 0,
                    },
                )
                assert resp.status_code == 200

        store = get_feedback_store()
        assert len(store) == 3
        assert [r.suggestion_id for r in store] == ["sug-0", "sug-1", "sug-2"]
