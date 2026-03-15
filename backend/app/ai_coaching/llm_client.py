"""LLM client abstraction for the AI coaching copilot.

Defines a ``LLMClient`` protocol and concrete implementations:
- ``OpenRouterLLMClient``: production client via OpenRouter (supports
  Claude, GPT-4o, Gemini, Llama, etc. through one API key).
- ``AnthropicLLMClient``: direct Anthropic SDK client (fallback).
- ``MockLLMClient``: test client with configurable responses.

OpenRouter is the recommended default because it provides:
- Access to all major model providers through a single API key
- Automatic fallback across providers on outages
- Unified billing and rate limits
- OpenAI-compatible API (uses the ``openai`` SDK with a custom base_url)
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


@runtime_checkable
class LLMClient(Protocol):
    """Abstract interface for LLM inference.

    Implementations must provide a ``generate`` method that accepts a system
    prompt and a user prompt and returns the model's text response, or
    ``None`` on failure.
    """

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> Optional[str]: ...


# --------------------------------------------------------------------------- #
# OpenRouter implementation (recommended default)
# --------------------------------------------------------------------------- #


class OpenRouterLLMClient:
    """Production LLM client via OpenRouter.

    Uses the OpenAI SDK with ``base_url`` pointed at OpenRouter.  This
    gives access to Claude, GPT-4o, Gemini, Llama, and many other models
    through a single API key.

    Supports both blocking and streaming modes.  Streaming is used by
    default for on-demand requests to reduce perceived latency (TTFB).

    Sign up at https://openrouter.ai/ to get an API key.
    """

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str,
        model: str = "anthropic/claude-3.5-haiku",
        app_name: str = "LiveSessionAnalysis",
        app_url: str = "",
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=self.OPENROUTER_BASE_URL,
            api_key=api_key,
            default_headers={
                "HTTP-Referer": app_url or "https://github.com/LiveSessionAnalysis",
                "X-Title": app_name,
            },
        )
        self._model = model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """Call the OpenRouter API (blocking) and return the full text."""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            if response.choices and len(response.choices) > 0:
                return response.choices[0].message.content
            return None
        except Exception:
            logger.exception("OpenRouter API call failed (model=%s)", self._model)
            return None

    async def generate_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """Call the OpenRouter API with streaming and return the full text.

        Streaming doesn't change the final result but reduces TTFB
        on the HTTP connection, which helps when the caller is measuring
        wall-clock time.  For true progressive display, use the
        ``stream_chunks`` method instead.
        """
        try:
            chunks: list[str] = []
            stream = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                stream=True,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            return "".join(chunks) if chunks else None
        except Exception:
            logger.exception(
                "OpenRouter streaming call failed (model=%s)", self._model
            )
            return None

    async def stream_chunks(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Yield individual text chunks as they arrive from the LLM.

        Used by SSE endpoints to stream tokens to the frontend in real time.
        """
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=max_tokens,
                stream=True,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception:
            logger.exception(
                "OpenRouter stream_chunks failed (model=%s)", self._model
            )


# --------------------------------------------------------------------------- #
# Anthropic implementation (direct, fallback)
# --------------------------------------------------------------------------- #


class AnthropicLLMClient:
    """Direct Anthropic SDK client.

    Use this if you have an Anthropic API key and prefer direct access
    without going through OpenRouter.  Requires the ``anthropic`` package.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        """Call the Anthropic Messages API and return the text response."""
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            if message.content and len(message.content) > 0:
                return message.content[0].text
            return None
        except Exception:
            logger.exception("Anthropic API call failed")
            return None


# --------------------------------------------------------------------------- #
# Mock implementation (for tests)
# --------------------------------------------------------------------------- #


class MockLLMClient:
    """Test double for LLMClient with configurable responses.

    By default returns a valid JSON coaching suggestion.  Set
    ``response`` to control the return value, or ``should_fail=True``
    to simulate an API error (returns ``None``).
    """

    DEFAULT_RESPONSE = (
        '{"action": "probe", "topic": "fractions", '
        '"observation": "Student seems unsure about denominators", '
        '"suggestion": "Ask the student to explain what a denominator represents.", '
        '"suggested_prompt": "Can you tell me what the bottom number in a fraction means?", '
        '"priority": "medium", "confidence": 0.85}'
    )

    def __init__(
        self,
        response: Optional[str] = None,
        should_fail: bool = False,
    ) -> None:
        self.response = response if response is not None else self.DEFAULT_RESPONSE
        self.should_fail = should_fail
        self.call_count = 0
        self.last_system_prompt: Optional[str] = None
        self.last_user_prompt: Optional[str] = None

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1024,
    ) -> Optional[str]:
        self.call_count += 1
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        if self.should_fail:
            return None
        return self.response
