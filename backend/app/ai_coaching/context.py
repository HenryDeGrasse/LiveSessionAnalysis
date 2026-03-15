"""AI Coaching context and suggestion data models.

Dataclasses used to pass session context into the coaching copilot and to
represent validated coaching suggestions returned by the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.transcription.models import FinalUtterance


@dataclass
class AISuggestion:
    """A single coaching suggestion produced by the AI copilot.

    Attributes:
        action: Short action verb/phrase (e.g. "probe", "scaffold").
        topic: The topic area the suggestion relates to.
        observation: What the AI observed in the session (evidence).
        suggestion: Human-readable coaching suggestion for the tutor.
        suggested_prompt: An example phrase the tutor could say.
        priority: Priority level — "high", "medium", or "low".
        confidence: Model confidence in the suggestion (0-1).
    """

    action: str
    topic: str
    observation: str
    suggestion: str
    suggested_prompt: str = ""
    priority: str = "medium"
    confidence: float = 0.0


@dataclass
class AICoachingContext:
    """Snapshot of session state passed to the coaching copilot.

    Aggregates recent transcript, uncertainty score, and session metadata
    so the LLM can produce contextually relevant suggestions.

    Attributes:
        session_id: Unique session identifier.
        session_type: Type of tutoring session (e.g. "math", "reading").
        elapsed_seconds: Seconds since session start.
        recent_utterances: Last N finalized utterances from the transcript.
        uncertainty_score: Current fused uncertainty score (0-1).
        uncertainty_topic: Topic extracted from uncertainty detection.
        tutor_talk_ratio: Fraction of talking time attributed to the tutor (0-1).
        student_talk_ratio: Fraction of talking time attributed to the student (0-1).
        student_engagement_score: Estimated student engagement (0-1).
        recent_suggestions: Previously issued suggestions (to avoid repetition).
    """

    session_id: str = ""
    session_type: str = "general"
    elapsed_seconds: float = 0.0
    recent_utterances: List[FinalUtterance] = field(default_factory=list)
    uncertainty_score: float = 0.0
    uncertainty_topic: str = ""
    tutor_talk_ratio: float = 0.0
    student_talk_ratio: float = 0.0
    student_engagement_score: float = 0.0
    recent_suggestions: List[AISuggestion] = field(default_factory=list)
