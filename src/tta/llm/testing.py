"""Deterministic mock LLM client for testing."""

from tta.llm.client import (
    GenerationParams,
    LLMResponse,
    Message,
)
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount

MOCK_RESPONSE = "You enter a dimly lit chamber."


class MockLLMClient:
    """Deterministic LLM client for CI and unit tests.

    Both generate() and stream() return LLMResponse (buffer-then-stream).
    Tracks call history for test assertions.
    """

    def __init__(
        self,
        response: str = MOCK_RESPONSE,
    ) -> None:
        self.response = response
        self.call_history: list[dict] = []

    def _build_response(
        self,
        messages: list[Message],
        role: ModelRole,
    ) -> LLMResponse:
        prompt_tokens = sum(len(m.content.split()) for m in messages)
        completion_tokens = len(self.response.split())
        return LLMResponse(
            content=self.response,
            model_used="mock",
            token_count=TokenCount(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            latency_ms=0.0,
            tier_used="primary",
        )

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        self.call_history.append(
            {"method": "generate", "role": role, "messages": messages}
        )
        return self._build_response(messages, role)

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Buffer-then-stream: returns complete LLMResponse like generate()."""
        self.call_history.append(
            {"method": "stream", "role": role, "messages": messages}
        )
        return self._build_response(messages, role)
