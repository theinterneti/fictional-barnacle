"""LLM client protocol and supporting types."""

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount


class MessageRole(StrEnum):
    """Role of a message in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """Single message in a conversation."""

    role: MessageRole
    content: str


class GenerationParams(BaseModel):
    """Parameters controlling LLM generation."""

    temperature: float = 0.7
    max_tokens: int = 1024
    stop: list[str] = Field(default_factory=list)


class LLMResponse(BaseModel):
    """Response from an LLM generation call."""

    content: str
    model_used: str
    token_count: TokenCount
    latency_ms: float


class LLMClient(Protocol):
    """Protocol for LLM client implementations."""

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse: ...

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> AsyncIterator[str]: ...
