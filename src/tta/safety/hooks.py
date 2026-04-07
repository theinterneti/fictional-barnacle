"""Safety hook protocol and pass-through implementation."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from tta.models.turn import TurnState


class SafetyResult(BaseModel):
    """Result of a safety check."""

    safe: bool
    flags: list[str] = Field(default_factory=list)
    modified_content: str | None = None


@runtime_checkable
class SafetyHook(Protocol):
    """Protocol for safety check hooks (v1: pass-through only)."""

    async def pre_generation_check(
        self, turn_state: TurnState
    ) -> SafetyResult: ...

    async def post_generation_check(
        self, narrative_output: str, turn_state: TurnState
    ) -> SafetyResult: ...


class PassthroughHook:
    """V1 default: all content passes through unchanged."""

    async def pre_generation_check(
        self, turn_state: TurnState
    ) -> SafetyResult:
        return SafetyResult(safe=True)

    async def post_generation_check(
        self, narrative_output: str, turn_state: TurnState
    ) -> SafetyResult:
        return SafetyResult(safe=True)
