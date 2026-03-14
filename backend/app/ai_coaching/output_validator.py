"""AI Output Validator for coaching suggestions.

Validates that AI-generated coaching suggestions do not leak direct
answers to students.  Two pattern sets are applied:

- ANSWER_PATTERNS: checked against both ``suggestion`` and
  ``suggested_prompt``.  These catch phrases like "the answer is",
  "the solution is", etc.
- PROMPT_ONLY_PATTERNS: checked only against ``suggested_prompt``.
  These catch expression-like answers ("= 5") and directive phrases
  ("tell them that").

If any pattern matches, the suggestion is rejected and ``validate()``
returns ``None``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Pattern definitions
# --------------------------------------------------------------------------- #

# Applied to BOTH suggestion and suggested_prompt
ANSWER_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bthe\s+answer\s+is\b", re.IGNORECASE), "the answer is"),
    (re.compile(r"\bthe\s+solution\s+is\b", re.IGNORECASE), "the solution is"),
    (re.compile(r"\bit\s+equals\b", re.IGNORECASE), "it equals"),
    (re.compile(r"\bthe\s+correct\s+answer\b", re.IGNORECASE), "the correct answer"),
    (re.compile(r"\byou\s+should\s+tell\s+them\b", re.IGNORECASE), "you should tell them"),
]

# Applied ONLY to suggested_prompt
PROMPT_ONLY_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"=\s*-?\d+(?:\.\d+)?(?:\s|$|[,;.!?])"), "= <number>"),
    (re.compile(r"\btell\s+them\s+that\b", re.IGNORECASE), "tell them that"),
]


@dataclass
class CoachingSuggestion:
    """A coaching suggestion to be validated."""

    suggestion: str
    suggested_prompt: Optional[str] = None


class AIOutputValidator:
    """Validates AI coaching output to prevent answer leakage."""

    def validate(self, suggestion: CoachingSuggestion) -> Optional[CoachingSuggestion]:
        """Validate a coaching suggestion.

        Returns the suggestion if it passes validation, or ``None`` if it
        contains answer-leaking patterns.
        """
        # Check ANSWER_PATTERNS against suggestion text
        for pattern, label in ANSWER_PATTERNS:
            if pattern.search(suggestion.suggestion):
                logger.warning(
                    "AI suggestion rejected: matched answer pattern '%s' in suggestion text",
                    label,
                )
                return None

        # Check ANSWER_PATTERNS against suggested_prompt (if present)
        if suggestion.suggested_prompt:
            for pattern, label in ANSWER_PATTERNS:
                if pattern.search(suggestion.suggested_prompt):
                    logger.warning(
                        "AI suggestion rejected: matched answer pattern '%s' in suggested_prompt",
                        label,
                    )
                    return None

            # Check PROMPT_ONLY_PATTERNS against suggested_prompt only
            for pattern, label in PROMPT_ONLY_PATTERNS:
                if pattern.search(suggestion.suggested_prompt):
                    logger.warning(
                        "AI suggestion rejected: matched prompt-only pattern '%s' in suggested_prompt",
                        label,
                    )
                    return None

        return suggestion
