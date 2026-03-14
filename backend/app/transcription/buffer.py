"""TranscriptBuffer – rolling window of finalized utterances.

Keeps a bounded deque of ``FinalUtterance`` objects trimmed to a configurable
time window.  Provides helpers that the AI coaching copilot and uncertainty
detector use to build context strings from recent conversation.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Dict, List, Optional

from app.transcription.models import FinalUtterance, SpeakerRole

_ROLE_LABELS: Dict[SpeakerRole, str] = {
    "tutor": "Tutor",
    "student": "Student",
}


class TranscriptBuffer:
    """Rolling window buffer of ``FinalUtterance`` objects.

    Parameters
    ----------
    window_seconds:
        Maximum age (in session-time seconds) of utterances to retain.
        Utterances whose *end_time* is older than ``newest_end_time -
        window_seconds`` are pruned on every ``add()``.
    """

    def __init__(self, window_seconds: float = 120.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._window: float = window_seconds
        self._buf: deque[FinalUtterance] = deque()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, utterance: FinalUtterance) -> None:
        """Append an utterance and prune stale entries."""
        self._buf.append(utterance)
        self._trim()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def recent_text(self, seconds: Optional[float] = None) -> str:
        """Return formatted conversation text from the last *seconds*.

        Format::

            [Tutor]: How are you doing with fractions?
            [Student]: I think I understand but I'm not sure about mixed numbers.

        If *seconds* is ``None`` the full window is returned.
        """
        utts = self._within(seconds)
        lines: List[str] = []
        for u in utts:
            label = _ROLE_LABELS.get(u.role, u.role.capitalize())
            lines.append(f"[{label}]: {u.text}")
        return "\n".join(lines)

    def student_recent_text(self, seconds: Optional[float] = None) -> str:
        """Return only student utterances from the last *seconds*."""
        utts = self._within(seconds)
        lines: List[str] = []
        for u in utts:
            if u.role == "student":
                lines.append(u.text)
        return "\n".join(lines)

    def word_count_by_role(self, seconds: Optional[float] = None) -> Dict[str, int]:
        """Return ``{"tutor": n, "student": m}`` word counts."""
        utts = self._within(seconds)
        counts: Dict[str, int] = {"tutor": 0, "student": 0}
        for u in utts:
            counts[u.role] = counts.get(u.role, 0) + len(u.text.split())
        return counts

    def last_topic_keywords(self, n: int = 5) -> List[str]:
        """Extract up to *n* naive topic keywords from recent text.

        This is a lightweight heuristic (stopword-filtered unique words by
        recency) that the full ``TopicExtractor`` will supersede later.
        """
        text = self.recent_text()
        if not text:
            return []
        # Strip role labels
        text = re.sub(r"\[(?:Tutor|Student)\]:\s*", "", text)
        words = text.lower().split()
        # Minimal stopword set
        stopwords = {
            "i", "me", "my", "we", "you", "your", "he", "she", "it", "they",
            "the", "a", "an", "is", "am", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will", "would",
            "shall", "should", "may", "might", "can", "could", "must",
            "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
            "into", "about", "that", "this", "but", "and", "or", "not", "no",
            "so", "if", "then", "than", "too", "very", "just", "how", "what",
            "when", "where", "which", "who", "whom", "why",
            "im", "its", "dont", "ive", "thats",
        }
        seen: set[str] = set()
        keywords: List[str] = []
        # Walk in reverse to favour recent words
        for w in reversed(words):
            clean = re.sub(r"[^a-z0-9]", "", w)
            if clean and clean not in stopwords and clean not in seen and len(clean) > 2:
                seen.add(clean)
                keywords.append(clean)
                if len(keywords) >= n:
                    break
        keywords.reverse()
        return keywords

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def window_seconds(self) -> float:
        return self._window

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trim(self) -> None:
        """Remove utterances outside the rolling window."""
        if not self._buf:
            return
        cutoff = self._buf[-1].end_time - self._window
        while self._buf and self._buf[0].end_time < cutoff:
            self._buf.popleft()

    def _within(self, seconds: Optional[float] = None) -> List[FinalUtterance]:
        """Return utterances whose end_time falls within the last *seconds*."""
        if not self._buf:
            return []
        if seconds is None:
            return list(self._buf)
        cutoff = self._buf[-1].end_time - seconds
        return [u for u in self._buf if u.end_time >= cutoff]
