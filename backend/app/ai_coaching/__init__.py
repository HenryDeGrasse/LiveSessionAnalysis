"""AI Coaching subsystem for AI Conversational Intelligence.

Provides PII scrubbing for transcript text, validation of AI-generated
coaching suggestions, LLM client abstraction, prompt templates,
coaching context/suggestion data models, and the AI coaching copilot.
"""

from .context import AICoachingContext, AISuggestion
from .copilot import AICoachingCopilot
from .llm_client import AnthropicLLMClient, LLMClient, MockLLMClient, OpenRouterLLMClient
from .output_validator import AIOutputValidator
from .pii_scrubber import PIIScrubber
from .prompts import (
    SESSION_TYPE_GUIDANCE,
    SYSTEM_PROMPT,
    build_system_prompt,
    build_user_prompt,
)
from .feedback import (
    FeedbackRecord,
    SuggestionFeedback,
    SuggestionContextRecord,
    get_suggestion_context,
    register_suggestion_context,
)
from .session_summary import AISessionSummary, generate_ai_session_summary

__all__ = [
    "AICoachingContext",
    "AICoachingCopilot",
    "AIOutputValidator",
    "AISessionSummary",
    "AISuggestion",
    "AnthropicLLMClient",
    "LLMClient",
    "MockLLMClient",
    "OpenRouterLLMClient",
    "PIIScrubber",
    "SESSION_TYPE_GUIDANCE",
    "SYSTEM_PROMPT",
    "build_system_prompt",
    "build_user_prompt",
    "generate_ai_session_summary",
    "FeedbackRecord",
    "SuggestionContextRecord",
    "SuggestionFeedback",
    "get_suggestion_context",
    "register_suggestion_context",
]
