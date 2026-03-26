"""Tests for AICoachingCopilot: interval logic, budget, dedup, validation."""
from __future__ import annotations

import json
import time

import pytest

from app.ai_coaching.copilot import AICoachingCopilot
from app.ai_coaching.llm_client import MockLLMClient
from app.transcription.buffer import TranscriptBuffer
from app.transcription.models import FinalUtterance


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_buffer(word_count: int = 30, num_utterances: int = 5) -> TranscriptBuffer:
    """Build a TranscriptBuffer pre-filled with enough words."""
    buf = TranscriptBuffer(window_seconds=300.0)
    words_per = max(1, word_count // num_utterances)
    for i in range(num_utterances):
        role = "student" if i % 2 == 0 else "tutor"
        text = " ".join(f"word{j}" for j in range(words_per))
        buf.add(FinalUtterance(
            role=role,
            text=text,
            start_time=float(i * 5),
            end_time=float(i * 5 + 4),
            utterance_id=f"utt-{i}",
        ))
    return buf


def _make_llm_response(
    *,
    action: str = "probe",
    topic: str = "fractions",
    observation: str = "Student seems unsure",
    suggestion: str = "Ask the student to explain their reasoning",
    suggested_prompt: str = "Can you tell me what you think?",
    priority: str = "medium",
    confidence: float = 0.85,
) -> str:
    return json.dumps({
        "action": action,
        "topic": topic,
        "observation": observation,
        "suggestion": suggestion,
        "suggested_prompt": suggested_prompt,
        "priority": priority,
        "confidence": confidence,
    })


# --------------------------------------------------------------------------- #
# Interval logic tests
# --------------------------------------------------------------------------- #


class TestIntervalLogic:
    """Baseline vs burst interval gating."""

    @pytest.mark.asyncio
    async def test_baseline_interval_blocks_early_call(self):
        """Calls within baseline interval should be suppressed."""
        llm = MockLLMClient()
        copilot = AICoachingCopilot(llm, baseline_interval_s=35.0)
        buf = _make_buffer()

        now = 1000.0
        # First call should succeed
        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert result is not None
        assert llm.call_count == 1

        # Call 10s later should be blocked (within 35s baseline)
        result2 = await copilot.maybe_evaluate(buf, elapsed_seconds=110, now=now + 10)
        assert result2 is None
        assert llm.call_count == 1  # no new LLM call

    @pytest.mark.asyncio
    async def test_baseline_interval_allows_after_elapsed(self):
        """Calls after baseline interval should succeed."""
        llm = MockLLMClient(response=_make_llm_response(topic="algebra"))
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=35.0, topic_cooldown_s=0.0
        )
        buf = _make_buffer()

        now = 1000.0
        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert llm.call_count == 1

        # Call 40s later should succeed (different suggestion text to avoid text-hash dedup)
        llm.response = _make_llm_response(
            topic="algebra", suggestion="A different algebra suggestion"
        )
        result = await copilot.maybe_evaluate(
            buf, elapsed_seconds=140, now=now + 40
        )
        assert result is not None
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_burst_mode_on_high_uncertainty(self):
        """High uncertainty triggers burst mode (shorter interval)."""
        llm = MockLLMClient(response=_make_llm_response(topic="geometry"))
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=35.0, burst_interval_s=12.0,
            topic_cooldown_s=0.0,
        )
        buf = _make_buffer()

        now = 1000.0
        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert llm.call_count == 1

        # 15s later with high uncertainty -> burst mode allows it
        llm.response = _make_llm_response(
            topic="geometry", suggestion="Different geometry suggestion"
        )
        result = await copilot.maybe_evaluate(
            buf,
            elapsed_seconds=115,
            uncertainty_score=0.8,
            now=now + 15,
        )
        assert result is not None
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_burst_mode_on_declining_engagement(self):
        """Declining engagement triggers burst mode."""
        llm = MockLLMClient(response=_make_llm_response(topic="calculus"))
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=35.0, burst_interval_s=12.0,
            topic_cooldown_s=0.0,
        )
        buf = _make_buffer()

        now = 1000.0
        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)

        # 15s later with declining engagement -> burst mode
        llm.response = _make_llm_response(
            topic="calculus", suggestion="Different calculus suggestion"
        )
        result = await copilot.maybe_evaluate(
            buf,
            elapsed_seconds=115,
            engagement_trend="declining",
            now=now + 15,
        )
        assert result is not None
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_burst_mode_on_rule_nudge(self):
        """Rule nudge firing triggers burst mode."""
        llm = MockLLMClient(response=_make_llm_response(topic="physics"))
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=35.0, burst_interval_s=12.0,
            topic_cooldown_s=0.0,
        )
        buf = _make_buffer()

        now = 1000.0
        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)

        llm.response = _make_llm_response(
            topic="physics", suggestion="Different physics suggestion"
        )
        result = await copilot.maybe_evaluate(
            buf,
            elapsed_seconds=115,
            rule_nudge_fired=True,
            now=now + 15,
        )
        assert result is not None
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_burst_interval_still_blocks_too_early(self):
        """Even in burst mode, calls within burst interval are blocked."""
        llm = MockLLMClient()
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=35.0, burst_interval_s=12.0
        )
        buf = _make_buffer()

        now = 1000.0
        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)

        # 5s later even with high uncertainty should be blocked (< 12s burst)
        result = await copilot.maybe_evaluate(
            buf,
            elapsed_seconds=105,
            uncertainty_score=0.9,
            now=now + 5,
        )
        assert result is None
        assert llm.call_count == 1


# --------------------------------------------------------------------------- #
# Budget tests
# --------------------------------------------------------------------------- #


class TestBudget:
    """Hard budget (calls per hour) enforcement."""

    @pytest.mark.asyncio
    async def test_budget_exhaustion_blocks_calls(self):
        """Once budget is exhausted, no more calls are made."""
        max_calls = 3
        llm = MockLLMClient()
        copilot = AICoachingCopilot(
            llm,
            baseline_interval_s=0.0,  # no interval gating for this test
            max_calls_per_hour=max_calls,
        )
        buf = _make_buffer()

        now = 1000.0
        for i in range(max_calls):
            result = await copilot.maybe_evaluate(
                buf, elapsed_seconds=100 + i, now=now + i
            )
            # Each call goes through (may be deduped but LLM is called)

        assert llm.call_count == max_calls

        # Next call should be blocked by budget
        result = await copilot.maybe_evaluate(
            buf, elapsed_seconds=200, now=now + max_calls + 1
        )
        assert result is None
        assert llm.call_count == max_calls  # no additional call

    @pytest.mark.asyncio
    async def test_budget_resets_after_hour(self):
        """Budget should reset after old timestamps age out."""
        max_calls = 2
        llm = MockLLMClient(response=_make_llm_response(topic="history"))
        copilot = AICoachingCopilot(
            llm,
            baseline_interval_s=0.0,
            max_calls_per_hour=max_calls,
            topic_cooldown_s=0.0,
        )
        buf = _make_buffer()

        now = 1000.0
        for i in range(max_calls):
            llm.response = _make_llm_response(
                topic=f"topic{i}", suggestion=f"Unique suggestion number {i}"
            )
            await copilot.maybe_evaluate(
                buf, elapsed_seconds=100 + i, now=now + i
            )
        assert llm.call_count == max_calls

        # 1 hour + 1 second later, budget should be restored
        future = now + 3601
        llm.response = _make_llm_response(
            topic="newtopic", suggestion="A brand new suggestion after reset"
        )
        result = await copilot.maybe_evaluate(
            buf, elapsed_seconds=4000, now=future
        )
        assert result is not None
        assert llm.call_count == max_calls + 1

    @pytest.mark.asyncio
    async def test_calls_remaining_reports_correctly(self):
        """calls_remaining should reflect current budget state."""
        llm = MockLLMClient()
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=0.0, max_calls_per_hour=5
        )
        buf = _make_buffer()

        now = 1000.0
        assert copilot.calls_remaining(now) == 5

        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert copilot.calls_remaining(now) == 4

    @pytest.mark.asyncio
    async def test_rejected_calls_count_against_budget(self):
        """Validator-rejected calls should still count against budget."""
        # Response with "the answer is" should be rejected
        bad_response = _make_llm_response(
            suggestion="The answer is 42, so tell them",
        )
        llm = MockLLMClient(response=bad_response)
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=0.0, max_calls_per_hour=5
        )
        buf = _make_buffer()

        now = 1000.0
        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert result is None  # rejected by validator
        assert copilot.rejected_calls == 1
        assert copilot.total_calls == 1
        assert copilot.calls_remaining(now) == 4  # still consumed budget


# --------------------------------------------------------------------------- #
# Minimum transcript words
# --------------------------------------------------------------------------- #


class TestMinTranscriptWords:
    """Minimum transcript word count gating."""

    @pytest.mark.asyncio
    async def test_insufficient_words_blocks_call(self):
        """Calls with too few transcript words should be blocked."""
        llm = MockLLMClient()
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=0.0, min_transcript_words=20
        )
        # Buffer with only 5 words
        buf = _make_buffer(word_count=5, num_utterances=1)

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is None
        assert llm.call_count == 0

    @pytest.mark.asyncio
    async def test_sufficient_words_allows_call(self):
        llm = MockLLMClient()
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=0.0, min_transcript_words=20
        )
        buf = _make_buffer(word_count=30)

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is not None
        assert llm.call_count == 1


# --------------------------------------------------------------------------- #
# Deduplication
# --------------------------------------------------------------------------- #


class TestDeduplication:
    """Suggestion dedup via text hash and per-topic cooldown."""

    @pytest.mark.asyncio
    async def test_same_suggestion_text_deduplicated(self):
        """Identical suggestion text should be suppressed."""
        response = _make_llm_response(
            topic="fractions",
            suggestion="Ask the student to explain their reasoning",
        )
        llm = MockLLMClient(response=response)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        now = 1000.0
        result1 = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert result1 is not None

        # Same suggestion text again → deduplicated
        result2 = await copilot.maybe_evaluate(buf, elapsed_seconds=110, now=now + 1)
        assert result2 is None
        # LLM was still called (budget consumed), but result suppressed
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_same_topic_within_cooldown_deduplicated(self):
        """Same topic within 5min cooldown should be suppressed."""
        response1 = _make_llm_response(
            topic="fractions",
            suggestion="Try asking what the numerator represents",
        )
        response2 = _make_llm_response(
            topic="fractions",
            suggestion="A completely different suggestion about fractions",
        )
        llm = MockLLMClient(response=response1)
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=0.0, topic_cooldown_s=300.0
        )
        buf = _make_buffer()

        now = 1000.0
        result1 = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert result1 is not None

        # Different text but same topic within cooldown
        llm.response = response2
        result2 = await copilot.maybe_evaluate(buf, elapsed_seconds=110, now=now + 60)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_same_topic_after_cooldown_allowed(self):
        """Same topic after cooldown should be allowed."""
        response1 = _make_llm_response(
            topic="fractions",
            suggestion="Try asking what the numerator represents",
        )
        response2 = _make_llm_response(
            topic="fractions",
            suggestion="A different suggestion about fractions",
        )
        llm = MockLLMClient(response=response1)
        copilot = AICoachingCopilot(
            llm, baseline_interval_s=0.0, topic_cooldown_s=300.0
        )
        buf = _make_buffer()

        now = 1000.0
        result1 = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert result1 is not None

        # After cooldown (301s later)
        llm.response = response2
        result2 = await copilot.maybe_evaluate(
            buf, elapsed_seconds=500, now=now + 301
        )
        assert result2 is not None

    @pytest.mark.asyncio
    async def test_different_topic_different_text_allowed(self):
        """Different topic and text should always be allowed."""
        response1 = _make_llm_response(
            topic="fractions", suggestion="Suggestion about fractions"
        )
        response2 = _make_llm_response(
            topic="algebra", suggestion="Suggestion about algebra"
        )
        llm = MockLLMClient(response=response1)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        now = 1000.0
        result1 = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)
        assert result1 is not None

        llm.response = response2
        result2 = await copilot.maybe_evaluate(buf, elapsed_seconds=110, now=now + 1)
        assert result2 is not None


# --------------------------------------------------------------------------- #
# Pedagogy constraint (validator integration)
# --------------------------------------------------------------------------- #


class TestValidatorIntegration:
    """Output validator should reject answer-leaking suggestions."""

    @pytest.mark.asyncio
    async def test_answer_leaking_suggestion_rejected(self):
        response = _make_llm_response(
            suggestion="The answer is 5, guide accordingly",
        )
        llm = MockLLMClient(response=response)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is None
        assert copilot.rejected_calls == 1

    @pytest.mark.asyncio
    async def test_answer_in_prompt_rejected(self):
        response = _make_llm_response(
            suggestion="Guide the student",
            suggested_prompt="The answer is 42",
        )
        llm = MockLLMClient(response=response)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is None
        assert copilot.rejected_calls == 1

    @pytest.mark.asyncio
    async def test_pedagogical_suggestion_passes(self):
        response = _make_llm_response(
            suggestion="Ask the student to explain their reasoning step by step",
            suggested_prompt="Can you walk me through how you got that?",
        )
        llm = MockLLMClient(response=response)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is not None
        assert result.suggestion == "Ask the student to explain their reasoning step by step"


# --------------------------------------------------------------------------- #
# Mock LLM integration
# --------------------------------------------------------------------------- #


class TestMockLLMIntegration:
    """Integration with MockLLMClient."""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        llm = MockLLMClient(should_fail=True)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is None
        assert llm.call_count == 1

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self):
        llm = MockLLMClient(response="not valid json {{{")
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_suggestion_field_returns_none(self):
        response = _make_llm_response(suggestion="")
        llm = MockLLMClient(response=response)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_suggestion_has_correct_fields(self):
        response = _make_llm_response(
            action="scaffold",
            topic="derivatives",
            observation="Student confused about chain rule",
            suggestion="Break the problem into inner and outer functions",
            suggested_prompt="What is the outer function here?",
            priority="high",
            confidence=0.92,
        )
        llm = MockLLMClient(response=response)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        result = await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert result is not None
        assert result.action == "scaffold"
        assert result.topic == "derivatives"
        assert result.observation == "Student confused about chain rule"
        assert result.suggestion == "Break the problem into inner and outer functions"
        assert result.suggested_prompt == "What is the outer function here?"
        assert result.priority == "high"
        assert result.confidence == 0.92

    @pytest.mark.asyncio
    async def test_pii_scrubbed_before_llm_call(self):
        """PII in transcript should be scrubbed before reaching the LLM."""
        llm = MockLLMClient()
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = TranscriptBuffer(window_seconds=300.0)
        # Add utterance with PII
        buf.add(FinalUtterance(
            role="student",
            text="My email is student@example.com and I need help with fractions "
                 "so let me add more words to meet the minimum word count requirement here",
            start_time=0.0,
            end_time=5.0,
            utterance_id="utt-pii",
        ))

        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=1000.0)
        assert llm.call_count == 1
        # The user prompt should have [EMAIL] instead of the actual email
        assert "student@example.com" not in (llm.last_user_prompt or "")
        assert "[EMAIL]" in (llm.last_user_prompt or "")

    @pytest.mark.asyncio
    async def test_recent_suggestions_passed_to_context(self):
        """Previously issued suggestions should be in the LLM context."""
        response1 = _make_llm_response(
            topic="topic1", suggestion="First suggestion about topic1"
        )
        response2 = _make_llm_response(
            topic="topic2", suggestion="Second suggestion about topic2"
        )
        llm = MockLLMClient(response=response1)
        copilot = AICoachingCopilot(llm, baseline_interval_s=0.0)
        buf = _make_buffer()

        now = 1000.0
        await copilot.maybe_evaluate(buf, elapsed_seconds=100, now=now)

        llm.response = response2
        await copilot.maybe_evaluate(buf, elapsed_seconds=110, now=now + 1)

        # The second call's user prompt should reference the first suggestion
        # (dedup section shows suggested_prompt preferentially, falling back to suggestion text)
        prompt = llm.last_user_prompt or ""
        assert "Already Suggested" in prompt
        assert ("First suggestion" in prompt or "Can you tell me what you think?" in prompt)
