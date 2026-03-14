"""Tests for post-session AI summary generation."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_coaching.llm_client import MockLLMClient
from app.ai_coaching.session_summary import (
    AISessionSummary,
    generate_ai_session_summary,
    _parse_summary_response,
    _build_transcript_prompt,
)
from app.main import app
from app.models import SessionSummary
from app.session_manager import session_manager
from app.transcription.models import FinalUtterance, WordTiming


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utt(
    role: str = "student",
    text: str = "hello",
    start: float = 0.0,
    end: float = 1.0,
    utterance_id: str = "u1",
) -> FinalUtterance:
    return FinalUtterance(
        role=role,
        text=text,
        start_time=start,
        end_time=end,
        utterance_id=utterance_id,
        words=[],
    )


VALID_SUMMARY_JSON = json.dumps({
    "topics_covered": ["fractions", "decimals"],
    "key_moments": [
        {
            "time": "2:30",
            "description": "Student had breakthrough on denominators",
            "significance": "Showed conceptual understanding",
        }
    ],
    "student_understanding_map": {
        "fractions": 0.7,
        "decimals": 0.5,
    },
    "tutor_strengths": ["Good use of scaffolding", "Patient explanations"],
    "tutor_growth_areas": ["Could ask more probing questions"],
    "recommended_follow_up": ["Review equivalent fractions", "Practice decimal conversion"],
    "session_narrative": "The session focused on fractions and decimals. The student showed growing understanding of denominators but needs more practice with decimal conversion.",
})


def _create_session() -> tuple[str, str]:
    resp = session_manager.create_session(
        tutor_id="tutor-1",
        student_user_id="student-1",
        session_type="math",
        session_title="Summary Test Session",
    )
    return resp.session_id, resp.tutor_token


# ---------------------------------------------------------------------------
# Tests: _parse_summary_response
# ---------------------------------------------------------------------------


class TestParseSummaryResponse:
    def test_valid_json(self):
        result = _parse_summary_response(VALID_SUMMARY_JSON)
        assert result is not None
        assert result.topics_covered == ["fractions", "decimals"]
        assert len(result.key_moments) == 1
        assert result.student_understanding_map["fractions"] == 0.7
        assert len(result.tutor_strengths) == 2
        assert len(result.tutor_growth_areas) == 1
        assert len(result.recommended_follow_up) == 2
        assert "fractions" in result.session_narrative

    def test_json_with_markdown_fences(self):
        wrapped = f"```json\n{VALID_SUMMARY_JSON}\n```"
        result = _parse_summary_response(wrapped)
        assert result is not None
        assert result.topics_covered == ["fractions", "decimals"]

    def test_invalid_json(self):
        result = _parse_summary_response("not json at all")
        assert result is None

    def test_non_dict_json(self):
        result = _parse_summary_response('["a", "b"]')
        assert result is None

    def test_empty_json_object(self):
        result = _parse_summary_response("{}")
        assert result is not None
        assert result.topics_covered == []
        assert result.session_narrative == ""

    def test_partial_fields(self):
        partial = json.dumps({
            "topics_covered": ["algebra"],
            "session_narrative": "Quick session on algebra.",
        })
        result = _parse_summary_response(partial)
        assert result is not None
        assert result.topics_covered == ["algebra"]
        assert result.tutor_strengths == []
        assert result.recommended_follow_up == []


# ---------------------------------------------------------------------------
# Tests: _build_transcript_prompt
# ---------------------------------------------------------------------------


class TestBuildTranscriptPrompt:
    def test_basic_prompt(self):
        utts = [
            _utt(role="tutor", text="What is 1/2 + 1/3?", start=10.0, end=12.0),
            _utt(role="student", text="Um, I think 2/5?", start=13.0, end=15.0),
        ]
        prompt = _build_transcript_prompt(utts, session_type="math", duration_seconds=300.0)
        assert "math" in prompt
        assert "5.0 minutes" in prompt
        assert "TUTOR" in prompt
        assert "STUDENT" in prompt
        assert "What is 1/2 + 1/3?" in prompt
        assert "Um, I think 2/5?" in prompt

    def test_empty_utterances(self):
        prompt = _build_transcript_prompt([])
        assert "Total utterances: 0" in prompt


# ---------------------------------------------------------------------------
# Tests: generate_ai_session_summary
# ---------------------------------------------------------------------------


class TestGenerateAISessionSummary:
    @pytest.mark.asyncio
    async def test_successful_generation(self):
        llm = MockLLMClient(response=VALID_SUMMARY_JSON)
        utts = [
            _utt(role="tutor", text="Let's talk about fractions", start=0.0, end=2.0),
            _utt(role="student", text="Okay, I find them confusing", start=3.0, end=5.0),
        ]
        result = await generate_ai_session_summary(
            utts, llm, session_type="math", duration_seconds=600.0,
        )
        assert result is not None
        assert result.topics_covered == ["fractions", "decimals"]
        assert llm.call_count == 1
        assert "math" in llm.last_user_prompt
        assert "fractions" in llm.last_user_prompt

    @pytest.mark.asyncio
    async def test_empty_utterances_returns_none(self):
        llm = MockLLMClient(response=VALID_SUMMARY_JSON)
        result = await generate_ai_session_summary([], llm)
        assert result is None
        assert llm.call_count == 0

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        llm = MockLLMClient(should_fail=True)
        utts = [_utt(text="hello")]
        result = await generate_ai_session_summary(utts, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_llm_response_returns_none(self):
        llm = MockLLMClient(response="not valid json")
        utts = [_utt(text="hello")]
        result = await generate_ai_session_summary(utts, llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_pii_scrubbing(self):
        llm = MockLLMClient(response=VALID_SUMMARY_JSON)
        utts = [
            _utt(
                role="tutor",
                text="My email is tutor@example.com and phone is 555-123-4567",
                start=0.0,
                end=3.0,
            ),
        ]
        result = await generate_ai_session_summary(utts, llm)
        assert result is not None
        # Verify PII was scrubbed in the prompt sent to the LLM
        assert "tutor@example.com" not in llm.last_user_prompt
        assert "555-123-4567" not in llm.last_user_prompt
        assert "[EMAIL]" in llm.last_user_prompt
        assert "[PHONE]" in llm.last_user_prompt


# ---------------------------------------------------------------------------
# Tests: AISessionSummary dataclass
# ---------------------------------------------------------------------------


class TestAISessionSummary:
    def test_default_values(self):
        summary = AISessionSummary()
        assert summary.topics_covered == []
        assert summary.key_moments == []
        assert summary.student_understanding_map == {}
        assert summary.tutor_strengths == []
        assert summary.tutor_growth_areas == []
        assert summary.recommended_follow_up == []
        assert summary.session_narrative == ""

    def test_custom_values(self):
        summary = AISessionSummary(
            topics_covered=["algebra"],
            session_narrative="Good session.",
            student_understanding_map={"algebra": 0.8},
        )
        assert summary.topics_covered == ["algebra"]
        assert summary.session_narrative == "Good session."
        assert summary.student_understanding_map["algebra"] == 0.8


class TestSummaryRouterPersistenceFallback:
    @pytest.mark.asyncio
    async def test_ai_summary_endpoint_uses_persisted_transcript_payload(self, monkeypatch):
        sid, tutor_token = _create_session()
        monkeypatch.setattr("app.ai_coaching.summary_router.settings.enable_ai_session_summary", True)
        monkeypatch.setattr("app.ai_coaching.summary_router.settings.ai_coaching_provider", "anthropic")
        monkeypatch.setattr("app.ai_coaching.summary_router.settings.anthropic_api_key", "test-key")

        persisted_summary = SessionSummary(
            session_id=sid,
            session_title="Summary Test Session",
            tutor_id="tutor-1",
            student_user_id="student-1",
            start_time=datetime(2026, 1, 1, 0, 0, 0),
            end_time=datetime(2026, 1, 1, 0, 10, 0),
            duration_seconds=600.0,
            transcript_word_count=4,
            transcript_compact={
                "session_id": sid,
                "word_count": 4,
                "utterances": [
                    {
                        "role": "tutor",
                        "text": "Let's review fractions",
                        "start_time": 0.0,
                        "end_time": 2.0,
                        "utterance_id": "u1",
                        "confidence": 0.98,
                    },
                    {
                        "role": "student",
                        "text": "I am unsure why denominators matter",
                        "start_time": 2.0,
                        "end_time": 5.0,
                        "utterance_id": "u2",
                        "confidence": 0.95,
                    },
                ],
            },
        )

        mock_store = type("Store", (), {
            "load": lambda self, session_id: persisted_summary if session_id == sid else None,
            "save": lambda self, summary: None,
        })()

        transport = ASGITransport(app=app)
        with patch("app.analytics.get_session_store", return_value=mock_store), patch(
            "app.ai_coaching.summary_router._build_llm_client",
            return_value=MockLLMClient(response=VALID_SUMMARY_JSON),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(f"/api/sessions/{sid}/ai-summary?token={tutor_token}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["summary"]["topics_covered"] == ["fractions", "decimals"]

    @pytest.mark.asyncio
    async def test_get_session_hides_transcript_compact(self, monkeypatch):
        monkeypatch.setattr("app.analytics.router.store", type("Store", (), {
            "load": lambda self, session_id: SessionSummary(
                session_id=session_id,
                session_title="Stored",
                tutor_id="tutor-1",
                student_user_id="student-1",
                start_time=datetime(2026, 1, 1, 0, 0, 0),
                end_time=datetime(2026, 1, 1, 0, 10, 0),
                duration_seconds=600.0,
                transcript_compact={"utterances": [{"text": "secret"}]},
            ) if session_id == "sess-hidden" else None,
            "save": lambda self, summary: None,
            "list_sessions": lambda self, **kwargs: [],
            "delete": lambda self, session_id: None,
        })())

        from app.analytics.router import get_session as get_session_endpoint
        from app.auth.models import User

        data = await get_session_endpoint(
            "sess-hidden",
            current_user=User(
                id="tutor-1",
                email="t@example.com",
                name="Tutor",
                role="tutor",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
        )

        assert "transcript_compact" not in data
        assert data["transcript_available"] is True
        assert data["transcript_segments"] == [
            {
                "utterance_id": "",
                "role": "student",
                "text": "secret",
                "start_time": 0.0,
                "end_time": 0.0,
                "confidence": 0.0,
                "sentiment": None,
                "student_index": 0,
            }
        ]
