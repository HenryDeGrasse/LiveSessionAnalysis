"""Data models for uncertainty detection signals and results.

These dataclasses are shared across linguistic and paralinguistic uncertainty
detectors, providing a common vocabulary for uncertainty signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class UncertaintySignal:
    """A single uncertainty signal detected in a transcript segment.

    Attributes:
        signal_type: Category of the signal (e.g. "hedging", "filler",
            "question_in_statement", "self_correction", "brevity").
        text: The text fragment that triggered the signal.
        weight: How strongly this signal contributes to uncertainty (0-1).
        detail: Optional human-readable description.
    """

    signal_type: str
    text: str
    weight: float
    detail: str = ""


@dataclass
class FusedUncertaintySignal:
    """Output of the fusion UncertaintyDetector when persistence is met.

    This is the high-level signal surfaced to the coaching layer and UI,
    distinct from the low-level ``UncertaintySignal`` (individual signal hits).

    Attributes:
        score: Fused uncertainty score in [0, 1].
        paralinguistic_score: Contribution from prosody analysis (0-1).
        linguistic_score: Contribution from text analysis (0-1).
        topic: Extracted topic from recent tutor questions.
        trigger_text: The student utterance that triggered the signal.
        signals: Individual signals that contributed.
        confidence: Confidence in the fused score (0-1).
    """

    score: float
    paralinguistic_score: float
    linguistic_score: float
    topic: str = ""
    trigger_text: str = ""
    signals: List[UncertaintySignal] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class LinguisticUncertaintyResult:
    """Output of linguistic uncertainty analysis for a single utterance.

    Attributes:
        score: Overall uncertainty score in [0, 1].
        hedging_score: Sub-score from hedging phrase detection (0-1).
        filler_score: Sub-score from filler word density relative to speaker
            baseline (0-1).
        filler_density: Raw filler density for this utterance (fillers / words).
        relative_filler_density: Filler density normalized against the speaker's
            rolling baseline (0-1).
        question_score: Sub-score from question-in-statement detection (0-1).
        self_correction_score: Sub-score from self-correction detection (0-1).
        brevity_score: Sub-score from response brevity (0-1).
        signals: Individual uncertainty signals found.
    """

    score: float
    hedging_score: float = 0.0
    filler_score: float = 0.0
    filler_density: float = 0.0
    relative_filler_density: float = 0.0
    question_score: float = 0.0
    self_correction_score: float = 0.0
    brevity_score: float = 0.0
    signals: List[UncertaintySignal] = field(default_factory=list)
