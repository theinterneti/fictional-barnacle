"""Pipeline stage protocol and configuration types.

Defines the Stage callable type and Pydantic configs for
the turn-processing pipeline (system.md §4.3).
"""

from collections.abc import Awaitable, Callable
from enum import StrEnum

from pydantic import BaseModel, Field

from tta.models.turn import TurnState

# Each stage takes TurnState and returns enriched TurnState
Stage = Callable[[TurnState], Awaitable[TurnState]]


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
            StageConfig(name=StageName.GENERATE),
            StageConfig(name=StageName.DELIVER),
        ]
    )
    overall_timeout_seconds: float = 120.0
