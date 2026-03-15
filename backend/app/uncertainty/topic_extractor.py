"""Topic extraction from tutor questions using curated subject vocabulary.

Tutor utterances (especially questions) carry topic intent.  This module
extracts the current discussion topic by scanning recent tutor questions
for keywords from a curated vocabulary list — a simple, fast approach
that avoids TF-IDF noise on tiny transcript windows.
"""

from __future__ import annotations

from collections import deque
import re
from typing import Deque, Dict, List, Set


# Curated vocabulary hints — expand per subject area
SUBJECT_VOCABULARY: Dict[str, Set[str]] = {
    "math": {
        "derivative", "integral", "function", "equation", "slope",
        "limit", "variable", "coefficient", "polynomial", "quadratic",
        "factor", "exponent", "logarithm", "trigonometry", "sine",
        "cosine", "tangent", "theorem", "proof", "graph",
        "fraction", "decimal", "percent", "ratio", "proportion",
        "matrix", "vector", "algebra", "geometry", "calculus",
        "probability", "statistics", "mean", "median", "mode",
    },
    "science": {
        "hypothesis", "experiment", "molecule", "atom", "cell",
        "energy", "force", "velocity", "acceleration", "reaction",
        "element", "compound", "evolution", "photosynthesis",
        "gravity", "momentum", "wavelength", "frequency", "nucleus",
        "electron", "proton", "neutron", "organism", "ecosystem",
    },
}

_QUESTION_STARTERS = (
    "what", "why", "how", "can you", "could you", "do you",
    "does", "is ", "are ", "would", "explain", "tell me",
)
_WORD_RE = re.compile(r"\b[\w-]+\b")


class TutorQuestionTopicExtractor:
    """Extract current topic from tutor questions.

    Tutor utterances (especially questions) carry topic intent.
    Combine with a curated subject-vocabulary list for math/science.

    Usage::

        extractor = TutorQuestionTopicExtractor()
        extractor.update(["What is the derivative of x squared?"])
        print(extractor.current_topic)  # "derivative"
    """

    def __init__(self, max_questions: int = 10) -> None:
        self._recent_tutor_questions: Deque[str] = deque(maxlen=max_questions)
        self._current_topic: str = ""

    @property
    def current_topic(self) -> str:
        """Return the most recently extracted topic (comma-separated keywords)."""
        return self._current_topic

    def update(self, tutor_utterances: List[str]) -> None:
        """Extract topic from recent tutor utterances.

        Args:
            tutor_utterances: List of tutor utterance text strings.
                Only those identified as questions are kept.
        """
        for text in tutor_utterances:
            if self._is_question(text):
                self._recent_tutor_questions.append(text)

        # Find subject keywords in recent tutor questions.
        # Match whole words only so short vocabulary items like "mean" do not
        # accidentally match unrelated words such as "demeanor".
        found_keywords: List[str] = []
        for question in self._recent_tutor_questions:
            tokens = {token.lower() for token in _WORD_RE.findall(question)}
            for vocab in SUBJECT_VOCABULARY.values():
                for word in vocab:
                    if word in tokens and word not in found_keywords:
                        found_keywords.append(word)

        # Keep the last 3 matched keywords for a concise topic string.
        # Because we scan questions in insertion order, later questions win.
        self._current_topic = ", ".join(found_keywords[-3:]) if found_keywords else ""

    @staticmethod
    def _is_question(text: str) -> bool:
        """Heuristic: ends with '?' or starts with question words."""
        text = text.strip()
        if not text:
            return False
        if text.endswith("?"):
            return True
        lower = text.lower()
        return any(lower.startswith(w) for w in _QUESTION_STARTERS)
