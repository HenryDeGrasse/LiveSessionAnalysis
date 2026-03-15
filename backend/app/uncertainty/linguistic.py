"""Linguistic uncertainty detection via text analysis.

LinguisticUncertaintyDetector analyses transcript text to identify hedging
phrases, filler words, question-in-statement patterns, self-corrections,
and response brevity — fusing them into a 0-1 uncertainty score.

Per-speaker filler calibration: the detector maintains a rolling baseline
of filler density per speaker so that habitually disfluent speakers are
not perpetually flagged as uncertain.
"""

from __future__ import annotations

import re
from collections import deque
from statistics import median
from typing import Deque, Dict, List, Tuple

from .models import LinguisticUncertaintyResult, UncertaintySignal

# --------------------------------------------------------------------------- #
# Hedging phrases with associated weights (higher = more uncertain)
# --------------------------------------------------------------------------- #

HEDGING_PHRASES: List[Tuple[str, float]] = [
    # Sorted longest-first to ensure greedy matching
    ("i'm not really sure", 0.75),
    ("i don't really know", 0.80),
    ("i'm not sure", 0.70),
    ("i don't know", 0.80),
    ("i'm not certain", 0.70),
    ("not entirely sure", 0.70),
    ("i might be wrong", 0.65),
    ("don't quote me", 0.60),
    ("correct me if", 0.55),
    ("if i remember", 0.55),
    ("i would say", 0.35),
    ("kind of", 0.30),
    ("sort of", 0.30),
    ("i guess", 0.50),
    ("i think", 0.40),
    ("i feel like", 0.40),
    ("i believe", 0.35),
    ("i suppose", 0.50),
    ("it seems", 0.35),
    ("maybe", 0.45),
    ("perhaps", 0.45),
    ("probably", 0.35),
    ("possibly", 0.45),
    ("not sure", 0.60),
    ("might be", 0.40),
    ("could be", 0.35),
]


def _compile_phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)


HEDGING_PATTERNS: List[Tuple[str, re.Pattern[str], float]] = [
    (phrase, _compile_phrase_pattern(phrase), weight)
    for phrase, weight in HEDGING_PHRASES
]

# --------------------------------------------------------------------------- #
# Filler words — excludes personality-dependent 'like' / 'you know'
# --------------------------------------------------------------------------- #

FILLER_WORDS = frozenset({"um", "uh", "er", "ah", "hmm", "umm", "uhh", "ehm"})

# --------------------------------------------------------------------------- #
# Self-correction markers
# --------------------------------------------------------------------------- #

SELF_CORRECTION_PATTERNS: List[Tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bwait\b", re.IGNORECASE), 0.50),
    (re.compile(r"\bactually no\b", re.IGNORECASE), 0.70),
    (re.compile(r"\bnever\s?mind\b", re.IGNORECASE), 0.65),
    (re.compile(r"\bi mean\b", re.IGNORECASE), 0.35),
    (re.compile(r"\bsorry\s*,?\s*i meant\b", re.IGNORECASE), 0.55),
    (re.compile(r"\blet me rephrase\b", re.IGNORECASE), 0.45),
    (re.compile(r"\bno\s*,?\s*wait\b", re.IGNORECASE), 0.60),
]

# --------------------------------------------------------------------------- #
# Fusion weights
# --------------------------------------------------------------------------- #

W_HEDGING = 0.30
W_FILLER = 0.20
W_QUESTION = 0.20
W_SELF_CORRECTION = 0.15
W_BREVITY = 0.15

# Brevity thresholds (word count)
BREVITY_SHORT_THRESHOLD = 3  # ≤3 words is very brief
BREVITY_MEDIUM_THRESHOLD = 8  # ≤8 words is somewhat brief


class LinguisticUncertaintyDetector:
    """Analyses transcript text for linguistic uncertainty signals.

    Maintains per-speaker filler density baselines using a rolling window
    so that speakers with naturally high filler rates are not permanently
    scored as uncertain.

    Usage::

        detector = LinguisticUncertaintyDetector()
        result = detector.analyze("um i think it might be five?", speaker_id="student-1")
        print(result.score)  # 0.0 – 1.0
    """

    def __init__(self, baseline_window: int = 50) -> None:
        """
        Args:
            baseline_window: Number of recent filler-density samples kept
                per speaker for rolling baseline computation.
        """
        self._baseline_window = baseline_window
        # speaker_id → deque of recent filler densities (fillers / word)
        self._filler_baselines: Dict[str, Deque[float]] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        text: str,
        speaker_id: str = "default",
    ) -> LinguisticUncertaintyResult:
        """Analyse *text* for linguistic uncertainty.

        Args:
            text: Transcript segment (single utterance or short turn).
            speaker_id: Identifier for speaker-specific filler calibration.

        Returns:
            LinguisticUncertaintyResult with sub-scores and overall score.
        """
        if not text or not text.strip():
            return LinguisticUncertaintyResult(score=0.0)

        normalized = text.strip().lower()
        words = normalized.split()
        word_count = len(words)

        signals: List[UncertaintySignal] = []

        # --- Hedging -------------------------------------------------- #
        hedging_score = self._detect_hedging(normalized, signals)

        # --- Fillers -------------------------------------------------- #
        filler_density, relative_filler_density = self._detect_fillers(
            words, speaker_id, signals,
        )

        # --- Question-in-statement ------------------------------------ #
        question_score = self._detect_question_in_statement(text.strip(), signals)

        # --- Self-correction ------------------------------------------ #
        self_correction_score = self._detect_self_correction(normalized, signals)

        # --- Brevity -------------------------------------------------- #
        brevity_score = self._score_brevity(word_count, signals)

        # --- Fusion --------------------------------------------------- #
        composite = (
            W_HEDGING * hedging_score
            + W_FILLER * relative_filler_density
            + W_QUESTION * question_score
            + W_SELF_CORRECTION * self_correction_score
            + W_BREVITY * brevity_score
        )
        composite = max(0.0, min(1.0, composite))

        return LinguisticUncertaintyResult(
            score=composite,
            hedging_score=hedging_score,
            filler_score=relative_filler_density,
            filler_density=filler_density,
            relative_filler_density=relative_filler_density,
            question_score=question_score,
            self_correction_score=self_correction_score,
            brevity_score=brevity_score,
            signals=signals,
        )

    # ------------------------------------------------------------------ #
    # Signal detectors
    # ------------------------------------------------------------------ #

    @staticmethod
    def _detect_hedging(
        normalized: str, signals: List[UncertaintySignal],
    ) -> float:
        """Detect hedging phrases and return the max weight found."""
        max_weight = 0.0
        for phrase, pattern, weight in HEDGING_PATTERNS:
            if pattern.search(normalized):
                signals.append(
                    UncertaintySignal(
                        signal_type="hedging",
                        text=phrase,
                        weight=weight,
                        detail=f"Hedging phrase detected: '{phrase}'",
                    )
                )
                max_weight = max(max_weight, weight)
        return max_weight

    def _detect_fillers(
        self,
        words: List[str],
        speaker_id: str,
        signals: List[UncertaintySignal],
    ) -> tuple[float, float]:
        """Detect filler words and return raw + relative density scores."""
        word_count = len(words)
        if word_count == 0:
            return 0.0, 0.0

        # Strip punctuation for matching
        clean_words = [re.sub(r"[^\w]", "", w) for w in words]
        filler_count = sum(1 for w in clean_words if w in FILLER_WORDS)
        filler_density = filler_count / word_count

        # Record fillers as signals
        for w in clean_words:
            if w in FILLER_WORDS:
                signals.append(
                    UncertaintySignal(
                        signal_type="filler",
                        text=w,
                        weight=0.3,
                        detail=f"Filler word: '{w}'",
                    )
                )

        # Update and retrieve speaker baseline
        if speaker_id not in self._filler_baselines:
            self._filler_baselines[speaker_id] = deque(maxlen=self._baseline_window)

        baseline_deque = self._filler_baselines[speaker_id]

        # Compute baseline from prior utterances only. Median is more robust than
        # mean for speakers with occasional highly disfluent turns.
        if len(baseline_deque) >= 5:
            baseline_value = float(median(baseline_deque))
            if baseline_value > 0.001:
                excess_ratio = max(0.0, filler_density - baseline_value) / baseline_value
                relative_filler_density = min(1.0, excess_ratio)
            else:
                # Speaker normally has no fillers — any filler is significant.
                relative_filler_density = min(1.0, filler_density * 5.0)
        else:
            # Not enough history — use raw density as a cold-start approximation.
            relative_filler_density = min(1.0, filler_density)

        # Append current density to baseline after scoring.
        baseline_deque.append(filler_density)

        return filler_density, relative_filler_density

    @staticmethod
    def _detect_question_in_statement(
        original_text: str, signals: List[UncertaintySignal],
    ) -> float:
        """Detect declarative content ending with '?' (uptalk / uncertainty)."""
        text = original_text.strip()
        if not text.endswith("?"):
            return 0.0

        # Check if it starts with a question word — that's a real question,
        # not an uncertain statement
        question_starters = (
            "who", "what", "where", "when", "why", "how",
            "is", "are", "was", "were", "do", "does", "did",
            "can", "could", "would", "should", "will", "shall",
            "have", "has", "had",
        )
        first_word = text.split()[0].lower().rstrip(",.!?") if text.split() else ""
        if first_word in question_starters:
            return 0.0

        signals.append(
            UncertaintySignal(
                signal_type="question_in_statement",
                text=text,
                weight=0.6,
                detail="Declarative statement ending with '?' (possible uptalk)",
            )
        )
        return 0.6

    @staticmethod
    def _detect_self_correction(
        normalized: str, signals: List[UncertaintySignal],
    ) -> float:
        """Detect self-correction patterns and return the max weight."""
        max_weight = 0.0
        for pattern, weight in SELF_CORRECTION_PATTERNS:
            match = pattern.search(normalized)
            if match:
                signals.append(
                    UncertaintySignal(
                        signal_type="self_correction",
                        text=match.group(),
                        weight=weight,
                        detail=f"Self-correction: '{match.group()}'",
                    )
                )
                max_weight = max(max_weight, weight)
        return max_weight

    @staticmethod
    def _score_brevity(
        word_count: int, signals: List[UncertaintySignal],
    ) -> float:
        """Score response brevity — very short answers suggest uncertainty."""
        if word_count <= BREVITY_SHORT_THRESHOLD:
            score = 0.8
        elif word_count <= BREVITY_MEDIUM_THRESHOLD:
            # Linear interpolation from 0.8 down to 0.3
            t = (word_count - BREVITY_SHORT_THRESHOLD) / (
                BREVITY_MEDIUM_THRESHOLD - BREVITY_SHORT_THRESHOLD
            )
            score = 0.8 - t * 0.5
        else:
            # Longer responses — lower brevity concern
            score = max(0.0, 0.3 - (word_count - BREVITY_MEDIUM_THRESHOLD) * 0.03)

        if score > 0.2:
            signals.append(
                UncertaintySignal(
                    signal_type="brevity",
                    text=f"{word_count} words",
                    weight=score,
                    detail=f"Short response ({word_count} words)",
                )
            )
        return score
