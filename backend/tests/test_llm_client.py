"""Tests for LLM client abstraction, prompt building, and context models."""

from __future__ import annotations

import json

import pytest

from app.ai_coaching.context import AICoachingContext, AISuggestion
from app.ai_coaching.llm_client import LLMClient, MockLLMClient
from app.ai_coaching.prompts import (
    SESSION_TYPE_GUIDANCE,
    build_system_prompt,
    build_user_prompt,
)
from app.transcription.models import FinalUtterance


# --------------------------------------------------------------------------- #
# MockLLMClient tests
# --------------------------------------------------------------------------- #


class TestMockLLMClient:
    """MockLLMClient returns configurable responses and records calls."""

    @pytest.mark.asyncio
    async def test_default_response_is_valid_json(self):
        client = MockLLMClient()
        result = await client.generate("system", "user")
        assert result is not None
        data = json.loads(result)
        assert "action" in data
        assert "suggestion" in data
        assert "confidence" in data

    @pytest.mark.asyncio
    async def test_custom_response(self):
        custom = '{"action": "encourage", "topic": "algebra"}'
        client = MockLLMClient(response=custom)
        result = await client.generate("sys", "usr")
        assert result == custom

    @pytest.mark.asyncio
    async def test_should_fail_returns_none(self):
        client = MockLLMClient(should_fail=True)
        result = await client.generate("sys", "usr")
        assert result is None

    @pytest.mark.asyncio
    async def test_records_call_count(self):
        client = MockLLMClient()
        assert client.call_count == 0
        await client.generate("s1", "u1")
        await client.generate("s2", "u2")
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_records_last_prompts(self):
        client = MockLLMClient()
        await client.generate("system_prompt_text", "user_prompt_text")
        assert client.last_system_prompt == "system_prompt_text"
        assert client.last_user_prompt == "user_prompt_text"

    def test_satisfies_protocol(self):
        """MockLLMClient should be a structural subtype of LLMClient."""
        client = MockLLMClient()
        assert isinstance(client, LLMClient)


# --------------------------------------------------------------------------- #
# Prompt building tests
# --------------------------------------------------------------------------- #


class TestBuildSystemPrompt:
    """build_system_prompt interpolates session type guidance."""

    def test_general_session_type(self):
        prompt = build_system_prompt("general")
        assert "general tutoring session" in prompt
        assert "pedagogy" in prompt.lower()
        assert "NEVER provide direct answers" in prompt

    def test_math_session_type(self):
        prompt = build_system_prompt("math")
        assert "math tutoring session" in prompt
        assert "scaffolding" in prompt

    def test_unknown_type_falls_back_to_general(self):
        prompt = build_system_prompt("underwater_basket_weaving")
        assert "general tutoring session" in prompt

    def test_json_schema_present(self):
        prompt = build_system_prompt()
        assert '"action"' in prompt
        assert '"topic"' in prompt
        assert '"suggestion"' in prompt
        assert '"confidence"' in prompt

    def test_all_session_types_have_guidance(self):
        for stype in SESSION_TYPE_GUIDANCE:
            prompt = build_system_prompt(stype)
            assert SESSION_TYPE_GUIDANCE[stype] in prompt


class TestBuildUserPrompt:
    """build_user_prompt formats context into a structured user prompt."""

    def _make_context(self, **kwargs) -> AICoachingContext:
        return AICoachingContext(**kwargs)

    def test_includes_elapsed_time(self):
        ctx = self._make_context(elapsed_seconds=300.0)
        prompt = build_user_prompt(ctx)
        assert "5.0 minutes" in prompt

    def test_includes_transcript(self):
        utterances = [
            FinalUtterance(
                role="tutor",
                text="What is 2 plus 2?",
                start_time=10.0,
                end_time=12.0,
            ),
            FinalUtterance(
                role="student",
                text="Um, I think it's 4?",
                start_time=13.0,
                end_time=15.0,
            ),
        ]
        ctx = self._make_context(recent_utterances=utterances)
        prompt = build_user_prompt(ctx)
        assert "[TUTOR] What is 2 plus 2?" in prompt
        assert "[STUDENT] Um, I think it's 4?" in prompt

    def test_empty_transcript(self):
        ctx = self._make_context()
        prompt = build_user_prompt(ctx)
        assert "no transcript available" in prompt

    def test_includes_uncertainty(self):
        ctx = self._make_context(
            uncertainty_score=0.75,
            uncertainty_topic="fractions",
        )
        prompt = build_user_prompt(ctx)
        assert "0.75" in prompt
        assert "fractions" in prompt

    def test_no_uncertainty_section_when_zero(self):
        ctx = self._make_context(uncertainty_score=0.0)
        prompt = build_user_prompt(ctx)
        assert "Uncertainty Signal" not in prompt

    def test_includes_talk_ratios(self):
        ctx = self._make_context(
            tutor_talk_ratio=0.65,
            student_talk_ratio=0.35,
        )
        prompt = build_user_prompt(ctx)
        assert "65%" in prompt
        assert "35%" in prompt

    def test_includes_recent_suggestions(self):
        sug = AISuggestion(
            action="probe",
            topic="algebra",
            observation="student hesitated",
            suggestion="Ask student to explain their approach",
        )
        ctx = self._make_context(recent_suggestions=[sug])
        prompt = build_user_prompt(ctx)
        assert "Previously Given Suggestions" in prompt
        assert "probe" in prompt
        assert "Ask student to explain their approach" in prompt


# --------------------------------------------------------------------------- #
# Context / AISuggestion dataclass tests
# --------------------------------------------------------------------------- #


class TestAISuggestion:
    """AISuggestion dataclass has correct defaults."""

    def test_defaults(self):
        s = AISuggestion(
            action="scaffold",
            topic="division",
            observation="student stuck",
            suggestion="Break problem into steps",
        )
        assert s.priority == "medium"
        assert s.confidence == 0.0
        assert s.suggested_prompt == ""

    def test_all_fields(self):
        s = AISuggestion(
            action="probe",
            topic="fractions",
            observation="uncertain tone",
            suggestion="Ask why",
            suggested_prompt="Why do you think that?",
            priority="high",
            confidence=0.9,
        )
        assert s.action == "probe"
        assert s.confidence == 0.9


class TestAICoachingContext:
    """AICoachingContext dataclass has correct defaults."""

    def test_defaults(self):
        ctx = AICoachingContext()
        assert ctx.session_id == ""
        assert ctx.session_type == "general"
        assert ctx.elapsed_seconds == 0.0
        assert ctx.recent_utterances == []
        assert ctx.uncertainty_score == 0.0
        assert ctx.recent_suggestions == []

    def test_custom_values(self):
        ctx = AICoachingContext(
            session_id="sess-123",
            session_type="math",
            elapsed_seconds=120.0,
            uncertainty_score=0.8,
        )
        assert ctx.session_id == "sess-123"
        assert ctx.session_type == "math"
