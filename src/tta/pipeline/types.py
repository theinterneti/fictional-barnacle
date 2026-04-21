"""Pipeline stage protocol and configuration types.

Defines the Stage callable type, PipelineDeps, and Pydantic configs
for the turn-processing pipeline (system.md §4.3,
plans/llm-and-pipeline.md §2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from tta.models.turn import TurnState

if TYPE_CHECKING:
    from tta.choices.consequence_service import ConsequenceService
    from tta.config import Settings
    from tta.llm.client import LLMClient
    from tta.llm.semaphore import LLMSemaphore
    from tta.persistence.repositories import (
        SessionRepository,
        TurnRepository,
    )
    from tta.prompts.loader import FilePromptRegistry
    from tta.resilience.circuit_breaker import CircuitBreaker
    from tta.safety.hooks import SafetyHook
    from tta.world.relationship_service import RelationshipService
    from tta.world.service import WorldService


@dataclass
class PipelineDeps:
    """Injected dependencies for pipeline stages.

    Stages receive (TurnState, PipelineDeps) and return TurnState.
    """

    llm: LLMClient
    world: WorldService
    session_repo: SessionRepository
    turn_repo: TurnRepository
    safety_pre_input: SafetyHook
    safety_pre_gen: SafetyHook
    safety_post_gen: SafetyHook
    langfuse_trace: Any | None = None
    settings: Settings | None = None
    consequence_service: ConsequenceService | None = None
    relationship_service: RelationshipService | None = None
    prompt_registry: FilePromptRegistry | None = None
    llm_semaphore: LLMSemaphore | None = None
    llm_circuit_breaker: CircuitBreaker | None = None
    db_session_factory: Any | None = None  # async_sessionmaker for direct DB access


# Each stage takes (TurnState, PipelineDeps) and returns enriched TurnState
Stage = Callable[[TurnState, PipelineDeps], Awaitable[TurnState]]


class StageName(StrEnum):
    """Canonical names for the four pipeline stages."""

    UNDERSTAND = "understand"
    CONTEXT = "context"
    GENERATE = "generate"
    DELIVER = "deliver"


class StageConfig(BaseModel):
    """Configuration for a single pipeline stage."""

    name: StageName
    timeout_seconds: float = 30.0


class PipelineConfig(BaseModel):
    """Configuration for the full turn pipeline."""

    stages: list[StageConfig] = Field(
        default_factory=lambda: [
            StageConfig(name=StageName.UNDERSTAND),
            StageConfig(name=StageName.CONTEXT),
            StageConfig(name=StageName.GENERATE, timeout_seconds=90.0),
            StageConfig(name=StageName.DELIVER),
        ]
    )
    overall_timeout_seconds: float = 120.0
