"""Uncertainty detection subsystem for AI Conversational Intelligence.

Provides paralinguistic (prosody-based) and linguistic (text-based) uncertainty
analysis using speaker baseline tracking and multi-signal fusion, plus a
fusion detector that combines both signals with persistence gating.
"""

from .detector import UncertaintyDetector
from .linguistic import LinguisticUncertaintyDetector
from .models import (
    FusedUncertaintySignal,
    LinguisticUncertaintyResult,
    UncertaintySignal,
)
from .paralinguistic import ParalinguisticAnalyzer, ParalinguisticResult, SpeakerBaseline
from .topic_extractor import TutorQuestionTopicExtractor

__all__ = [
    "FusedUncertaintySignal",
    "LinguisticUncertaintyDetector",
    "LinguisticUncertaintyResult",
    "ParalinguisticAnalyzer",
    "ParalinguisticResult",
    "SpeakerBaseline",
    "TutorQuestionTopicExtractor",
    "UncertaintyDetector",
    "UncertaintySignal",
]
