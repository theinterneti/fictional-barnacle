"""LLM client protocol and supporting types."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from tta.llm.roles import ModelRole
from tta.llm.serving_profiles import (
    GenerationServingProfile,
    GenerationTrafficClass,
)
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
    response_format: dict[str, Any] | None = None


class LLMResponse(BaseModel):
    """Response from an LLM generation call.

    Both generate() and stream() return this envelope.
    In v1's buffer-then-stream architecture, stream() collects
    the full response internally and returns the same LLMResponse.
    """

    content: str
    model_used: str
    token_count: TokenCount
    latency_ms: float
    tier_used: Literal["primary", "fallback"] = "primary"
    trace_id: str = ""
    cost_usd: float = 0.0
    requested_profile: str = ""
    effective_profile: str = ""
    traffic_class: str = ""
    degraded: bool = False
    degradation_reason: str = ""


class LLMClient(Protocol):
    """Protocol for LLM client implementations.

    Both generate() and stream() return LLMResponse.
    stream() uses internal streaming for timeout/progress but
    buffers the complete response (buffer-then-stream, S07 FR-07.23).
    """

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
        *,
        generation_profile: GenerationServingProfile | None = None,
        traffic_class: GenerationTrafficClass | None = None,
    ) -> LLMResponse: ...

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
        *,
        generation_profile: GenerationServingProfile | None = None,
        traffic_class: GenerationTrafficClass | None = None,
    ) -> LLMResponse: ...
