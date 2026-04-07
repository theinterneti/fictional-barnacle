"""Deterministic mock LLM client for testing."""

from collections.abc import AsyncIterator

from tta.llm.client import (
    GenerationParams,
    LLMResponse,
    Message,
)
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount

MOCK_RESPONSE = "You enter a dimly lit chamber."


class MockLLMClient:
    """Deterministic LLM client for CI and unit tests."""

    def __init__(
        self,
        response: str = MOCK_RESPONSE,
    ) -> None:
        self.response = response

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
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
        )

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> AsyncIterator[str]:
        for token in self.response.split():
            yield token
