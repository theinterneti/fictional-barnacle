"""Turn-related domain models.

Covers the pipeline's internal contract (system.md §4.3) and
public request/response types for turn processing.
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class TurnStatus(StrEnum):
    """Lifecycle status of a single turn."""

    processing = "processing"
    complete = "complete"
    failed = "failed"


class TokenCount(BaseModel):
    """LLM token usage for a single turn."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ParsedIntent(BaseModel):
    """Result of intent-parsing stage."""

    intent: str
    confidence: float
    entities: dict = Field(default_factory=dict)


class TurnRequest(BaseModel):
    """Player-facing input for a single turn."""

    input: str
    idempotency_key: UUID | None = None


class TurnResult(BaseModel):
    """Player-facing output after turn processing."""

    narrative_output: str
    model_used: str
    latency_ms: float
    token_count: TokenCount


class TurnState(BaseModel):
    """Pipeline-internal state bag carried through all stages.

    Required fields are populated at the start of a turn;
    optional fields are filled by successive pipeline stages.
    TurnState is the normative pipeline contract (system.md §4.3).
    Component plans may add optional fields but not rename/remove.
    """

    # --- required ---
    session_id: UUID
    turn_id: UUID | None = None
    turn_number: int
    player_input: str
    game_state: dict

    # --- stage outputs (optional) ---
    parsed_intent: ParsedIntent | None = None
    world_context: dict | None = None
    narrative_history: list[dict] | None = None
    generation_prompt: str | None = None
    narrative_output: str | None = None
    model_used: str | None = None
    token_count: TokenCount | None = None
    delivered: bool = False
    latency_ms: float | None = None
    safety_flags: list[str] = Field(default_factory=list)
    status: TurnStatus = TurnStatus.processing
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # --- extensions (plans/llm-and-pipeline.md §2.3) ---
    world_state_updates: list[dict] | None = None
    suggested_actions: list[str] | None = None
    extraction_latency_ms: int | None = None
    context_partial: bool = False
