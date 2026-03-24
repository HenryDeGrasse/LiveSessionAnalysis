"""AI Coaching Copilot – orchestrates LLM-based coaching suggestions.

The copilot is called periodically (via ``maybe_evaluate``) and decides
whether to invoke the LLM based on timing, budget, and content heuristics.

Key behaviours:
- **Baseline interval** (default 35s) between LLM calls.
- **Burst mode** (default 12s) triggered by high uncertainty, rule nudges,
  or declining engagement.
- **Hard budget** of 60 calls per hour (configurable).
- **Minimum transcript words** (20) before attempting a call.
- **PII scrubbing** of transcript text before sending to the LLM.
- **Suggestion deduplication** via normalised text hash + per-topic cooldown
  (300s default).
- **Output validation** via ``AIOutputValidator`` to enforce pedagogy
  constraints; rejected calls still count against the budget.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Dict, List, Optional

from app.ai_coaching.context import AICoachingContext, AISuggestion
from app.ai_coaching.llm_client import LLMClient
from app.ai_coaching.output_validator import AIOutputValidator, CoachingSuggestion
from app.ai_coaching.pii_scrubber import PIIScrubber
from app.ai_coaching.prompts import build_system_prompt, build_user_prompt
from app.transcription.buffer import TranscriptBuffer

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

_DEFAULT_BASELINE_INTERVAL_S = 35.0
_DEFAULT_BURST_INTERVAL_S = 12.0
_DEFAULT_MAX_CALLS_PER_HOUR = 60
_DEFAULT_MIN_TRANSCRIPT_WORDS = 20
_DEFAULT_CONTEXT_WINDOW_S = 90.0
_DEFAULT_TOPIC_COOLDOWN_S = 300.0
_DEFAULT_UNCERTAINTY_BURST_THRESHOLD = 0.6


def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation/whitespace for dedup hashing."""
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _text_hash(text: str) -> str:
    """SHA-256 hex digest of normalised text (first 16 chars)."""
    return hashlib.sha256(_normalize_text(text).encode()).hexdigest()[:16]


class AICoachingCopilot:
    """Orchestrates LLM-based coaching suggestions for a single session.

    Parameters
    ----------
    llm_client:
        An object satisfying the ``LLMClient`` protocol.
    session_type:
        Tutoring session category (``"math"``, ``"general"``, …).
    baseline_interval_s:
        Minimum seconds between LLM calls in normal mode.
    burst_interval_s:
        Minimum seconds between LLM calls in burst mode.
    max_calls_per_hour:
        Hard budget ceiling on LLM invocations per rolling hour.
    min_transcript_words:
        Minimum total words in the transcript before the first LLM call.
    context_window_s:
        How many seconds of transcript to include in the LLM prompt.
    topic_cooldown_s:
        Per-topic dedup cooldown in seconds.
    uncertainty_burst_threshold:
        Uncertainty score above which burst mode is activated.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        session_type: str = "general",
        *,
        baseline_interval_s: float = _DEFAULT_BASELINE_INTERVAL_S,
        burst_interval_s: float = _DEFAULT_BURST_INTERVAL_S,
        max_calls_per_hour: int = _DEFAULT_MAX_CALLS_PER_HOUR,
        min_transcript_words: int = _DEFAULT_MIN_TRANSCRIPT_WORDS,
        context_window_s: float = _DEFAULT_CONTEXT_WINDOW_S,
        topic_cooldown_s: float = _DEFAULT_TOPIC_COOLDOWN_S,
        uncertainty_burst_threshold: float = _DEFAULT_UNCERTAINTY_BURST_THRESHOLD,
    ) -> None:
        self._llm = llm_client
        self._session_type = session_type

        self._baseline_interval = baseline_interval_s
        self._burst_interval = burst_interval_s
        self._max_calls_per_hour = max_calls_per_hour
        self._min_transcript_words = min_transcript_words
        self._context_window = context_window_s
        self._topic_cooldown = topic_cooldown_s
        self._uncertainty_burst_threshold = uncertainty_burst_threshold

        self._pii_scrubber = PIIScrubber()
        self._validator = AIOutputValidator()

        # State
        self._last_call_time: float = 0.0
        self._call_timestamps: List[float] = []
        self._suggestion_hashes: Dict[str, float] = {}  # hash -> timestamp
        self._topic_last_seen: Dict[str, float] = {}  # topic -> timestamp
        self._recent_suggestions: List[AISuggestion] = []
        self._total_calls: int = 0
        self._rejected_calls: int = 0
        self._total_tokens: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def maybe_evaluate(
        self,
        transcript_buffer: TranscriptBuffer,
        *,
        elapsed_seconds: float = 0.0,
        uncertainty_score: float = 0.0,
        uncertainty_topic: str = "",
        tutor_talk_ratio: float = 0.0,
        student_talk_ratio: float = 0.0,
        engagement_score: float = 0.0,
        engagement_trend: str = "stable",
        rule_nudge_fired: bool = False,
        now: Optional[float] = None,
        backpressure_level: int = 0,
        on_demand: bool = False,
        # --- Rich behavioral signals ---
        student_attention_state: str = "",
        student_time_in_attention_state: float = 0.0,
        tutor_attention_state: str = "",
        time_since_student_spoke: float = 0.0,
        mutual_silence_seconds: float = 0.0,
        tutor_monologue_seconds: float = 0.0,
        tutor_turn_count: int = 0,
        student_turn_count: int = 0,
        student_response_latency: float = 0.0,
        recent_hard_interruptions: int = 0,
        tutor_cutoffs: int = 0,
        active_overlap_state: str = "none",
        student_energy_score: float = 0.0,
        student_energy_drop: float = 0.0,
        tutor_energy_score: float = 0.0,
        active_rule_nudge: str = "",
        active_rule_message: str = "",
    ) -> Optional[AISuggestion]:
        """Evaluate whether to call the LLM and return a suggestion if appropriate.

        Returns ``None`` when:
        - It is too soon since the last call (interval gating).
        - The hourly budget is exhausted.
        - The transcript has too few words.
        - The LLM returns an unparseable or invalid response.
        - The suggestion is a duplicate (text hash or topic cooldown).
        - Backpressure level >= L2 for auto-evaluation (on-demand still allowed).
        - Backpressure level >= L3 blocks all AI calls.
        """
        if now is None:
            now = time.time()

        # Backpressure gating: L3 blocks everything, L2 blocks auto-triggers
        if backpressure_level >= 3:
            logger.debug("AI copilot: blocked by backpressure L3")
            return None
        if backpressure_level >= 2 and not on_demand:
            logger.debug("AI copilot: auto-evaluation suspended at backpressure L2")
            return None

        # 1. Budget check
        if self._budget_exhausted(now):
            logger.debug("AI copilot: budget exhausted")
            return None

        # 2. Interval check (burst vs. baseline)
        burst = self._should_burst(
            uncertainty_score=uncertainty_score,
            engagement_trend=engagement_trend,
            rule_nudge_fired=rule_nudge_fired,
        )
        interval = self._burst_interval if burst else self._baseline_interval
        if now - self._last_call_time < interval:
            return None

        # 3. Minimum transcript words
        word_counts = transcript_buffer.word_count_by_role()
        total_words = sum(word_counts.values())
        if total_words < self._min_transcript_words:
            logger.debug(
                "AI copilot: insufficient transcript words (%d < %d)",
                total_words,
                self._min_transcript_words,
            )
            return None

        # 4. Build context
        recent_utterances = transcript_buffer._within(self._context_window)
        topic_keywords = transcript_buffer.last_topic_keywords(n=5)

        context = AICoachingContext(
            session_type=self._session_type,
            elapsed_seconds=elapsed_seconds,
            recent_utterances=recent_utterances,
            uncertainty_score=uncertainty_score,
            uncertainty_topic=uncertainty_topic,
            tutor_talk_ratio=tutor_talk_ratio,
            student_talk_ratio=student_talk_ratio,
            student_engagement_score=engagement_score,
            recent_suggestions=list(self._recent_suggestions[-5:]),
            # Behavioral signals
            student_attention_state=student_attention_state,
            student_time_in_attention_state=student_time_in_attention_state,
            tutor_attention_state=tutor_attention_state,
            # Turn-taking & silence
            time_since_student_spoke=time_since_student_spoke,
            mutual_silence_seconds=mutual_silence_seconds,
            tutor_monologue_seconds=tutor_monologue_seconds,
            tutor_turn_count=tutor_turn_count,
            student_turn_count=student_turn_count,
            student_response_latency=student_response_latency,
            # Interruptions
            recent_hard_interruptions=recent_hard_interruptions,
            tutor_cutoffs=tutor_cutoffs,
            active_overlap_state=active_overlap_state,
            # Energy
            student_energy_score=student_energy_score,
            student_energy_drop=student_energy_drop,
            tutor_energy_score=tutor_energy_score,
            # Engagement
            engagement_trend=engagement_trend,
            # Active coaching rule
            active_rule_nudge=active_rule_nudge,
            active_rule_message=active_rule_message,
            # Topics
            topic_keywords=topic_keywords,
        )

        # 5. PII-scrub the user prompt
        system_prompt = build_system_prompt(self._session_type)
        user_prompt = build_user_prompt(context)
        scrub_result = self._pii_scrubber.scrub(user_prompt)
        user_prompt = scrub_result.text

        # 6. Call LLM
        self._record_call(now)
        raw_response = await self._llm.generate(
            system_prompt, user_prompt, max_tokens=512
        )

        if raw_response is None:
            logger.warning("AI copilot: LLM returned None")
            return None

        # 7. Parse JSON response
        suggestion = self._parse_response(raw_response)
        if suggestion is None:
            logger.warning("AI copilot: failed to parse LLM response")
            return None

        # 8. Validate via AIOutputValidator
        coaching_suggestion = CoachingSuggestion(
            suggestion=suggestion.suggestion,
            suggested_prompt=suggestion.suggested_prompt or None,
        )
        validated = self._validator.validate(coaching_suggestion)
        if validated is None:
            logger.info("AI copilot: suggestion rejected by validator")
            self._rejected_calls += 1
            return None

        # 9. Dedup check
        if self._is_duplicate(suggestion, now):
            logger.debug("AI copilot: duplicate suggestion suppressed")
            return None

        # 10. Record and return
        self._record_suggestion(suggestion, now)
        return suggestion

    @property
    def total_calls(self) -> int:
        """Total LLM calls made (including rejected)."""
        return self._total_calls

    @property
    def rejected_calls(self) -> int:
        """Number of calls rejected by the validator."""
        return self._rejected_calls

    @property
    def total_tokens(self) -> int:
        """Total tokens reported by the LLM client, if available."""
        return self._total_tokens

    @property
    def recent_suggestions(self) -> List[AISuggestion]:
        """List of recently issued suggestions."""
        return list(self._recent_suggestions)

    def calls_remaining(self, now: Optional[float] = None) -> int:
        """Return the number of LLM calls remaining in the current hour."""
        if now is None:
            now = time.time()
        self._prune_call_timestamps(now)
        return max(0, self._max_calls_per_hour - len(self._call_timestamps))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _should_burst(
        self,
        *,
        uncertainty_score: float,
        engagement_trend: str,
        rule_nudge_fired: bool,
    ) -> bool:
        """Return True if burst mode should be activated."""
        if uncertainty_score >= self._uncertainty_burst_threshold:
            return True
        if rule_nudge_fired:
            return True
        if engagement_trend == "declining":
            return True
        return False

    def _budget_exhausted(self, now: float) -> bool:
        """Return True if the hourly call budget is used up."""
        self._prune_call_timestamps(now)
        return len(self._call_timestamps) >= self._max_calls_per_hour

    def _prune_call_timestamps(self, now: float) -> None:
        """Remove call timestamps older than 1 hour."""
        cutoff = now - 3600.0
        self._call_timestamps = [t for t in self._call_timestamps if t >= cutoff]

    def _record_call(self, now: float) -> None:
        """Record that an LLM call was made."""
        self._last_call_time = now
        self._call_timestamps.append(now)
        self._total_calls += 1

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Strip markdown code fences if present.

        Gemini and some other models wrap JSON in ```json ... ```.
        """
        stripped = raw.strip()
        # Strip ```json ... ``` or ``` ... ```
        fence_match = re.match(
            r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", stripped, re.DOTALL
        )
        if fence_match:
            return fence_match.group(1).strip()
        return stripped

    def _parse_response(self, raw: str) -> Optional[AISuggestion]:
        """Parse a raw LLM JSON response into an ``AISuggestion``."""
        try:
            data = json.loads(self._extract_json(raw))
        except json.JSONDecodeError:
            logger.debug("AI copilot: raw response not valid JSON: %s", raw[:200])
            return None

        if not isinstance(data, dict):
            return None

        # Required fields
        action = data.get("action", "")
        topic = data.get("topic", "")
        observation = data.get("observation", "")
        suggestion_text = data.get("suggestion", "")

        if not suggestion_text:
            return None

        return AISuggestion(
            action=str(action),
            topic=str(topic),
            observation=str(observation),
            suggestion=str(suggestion_text),
            suggested_prompt=str(data.get("suggested_prompt", "")),
            priority=str(data.get("priority", "medium")),
            confidence=float(data.get("confidence", 0.0)),
        )

    def _is_duplicate(self, suggestion: AISuggestion, now: float) -> bool:
        """Check if a suggestion is a duplicate by text hash or topic cooldown."""
        # Text hash dedup
        text_hash = _text_hash(suggestion.suggestion)
        if text_hash in self._suggestion_hashes:
            return True

        # Per-topic cooldown
        topic = _normalize_text(suggestion.topic)
        if topic and topic in self._topic_last_seen:
            if now - self._topic_last_seen[topic] < self._topic_cooldown:
                return True

        return False

    def _record_suggestion(self, suggestion: AISuggestion, now: float) -> None:
        """Record a suggestion for dedup and history tracking."""
        text_hash = _text_hash(suggestion.suggestion)
        self._suggestion_hashes[text_hash] = now

        topic = _normalize_text(suggestion.topic)
        if topic:
            self._topic_last_seen[topic] = now

        self._recent_suggestions.append(suggestion)
        # Keep only last 20 suggestions in memory
        if len(self._recent_suggestions) > 20:
            self._recent_suggestions = self._recent_suggestions[-20:]
