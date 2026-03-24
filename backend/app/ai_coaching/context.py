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

    Aggregates recent transcript, uncertainty score, behavioral signals,
    and session metadata so the LLM can produce contextually relevant
    and practical coaching suggestions.

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

        # --- Behavioral signals (visual) ---
        student_attention_state: Current attention state label.
        student_time_in_attention_state: Seconds in current attention state.
        tutor_attention_state: Tutor's attention state.

        # --- Turn-taking & silence ---
        time_since_student_spoke: Seconds since the student last spoke.
        mutual_silence_seconds: Current mutual silence duration.
        tutor_monologue_seconds: Current tutor monologue duration.
        tutor_turn_count: Number of tutor speaking turns.
        student_turn_count: Number of student speaking turns.
        student_response_latency: Seconds it took student to respond last time.

        # --- Interruption signals ---
        recent_hard_interruptions: Hard interruptions in recent window.
        tutor_cutoffs: Times tutor cut off the student.
        active_overlap_state: Current overlap classification.

        # --- Energy / prosody ---
        student_energy_score: Student vocal energy (0-1).
        student_energy_drop: Drop from student's baseline energy.
        tutor_energy_score: Tutor vocal energy (0-1).

        # --- Engagement ---
        engagement_trend: "rising", "stable", or "declining".

        # --- Active coaching rule ---
        active_rule_nudge: Name of coaching rule that just fired, if any.
        active_rule_message: The rule's nudge message, if any.

        # --- Topic context ---
        topic_keywords: Extracted topic keywords from recent conversation.
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

    # --- Behavioral signals (visual) ---
    student_attention_state: str = ""
    student_time_in_attention_state: float = 0.0
    tutor_attention_state: str = ""

    # --- Turn-taking & silence ---
    time_since_student_spoke: float = 0.0
    mutual_silence_seconds: float = 0.0
    tutor_monologue_seconds: float = 0.0
    tutor_turn_count: int = 0
    student_turn_count: int = 0
    student_response_latency: float = 0.0

    # --- Interruption signals ---
    recent_hard_interruptions: int = 0
    tutor_cutoffs: int = 0
    active_overlap_state: str = "none"

    # --- Energy / prosody ---
    student_energy_score: float = 0.0
    student_energy_drop: float = 0.0
    tutor_energy_score: float = 0.0

    # --- Engagement ---
    engagement_trend: str = "stable"

    # --- Active coaching rule ---
    active_rule_nudge: str = ""
    active_rule_message: str = ""

    # --- Topic context ---
    topic_keywords: List[str] = field(default_factory=list)
