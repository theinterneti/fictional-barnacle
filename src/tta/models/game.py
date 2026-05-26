"""Game-session and game-state domain models plus API request/response schemas."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

# ── Domain models ────────────────────────────────────────────────────────────


class GameStatus(StrEnum):
    """Lifecycle status of a game session (plan §6.1, S27 FR-27.01)."""

    created = "created"
    active = "active"
    paused = "paused"
    completed = "completed"
    ended = "ended"
    expired = "expired"
    abandoned = "abandoned"


class GenesisStatus(StrEnum):
    """Outcome of synchronous genesis during game creation."""

    complete = "complete"
    degraded = "degraded"


class GameSession(BaseModel):
    """Top-level container for a single play-through."""

    id: UUID = Field(default_factory=uuid4)
    player_id: UUID
    status: GameStatus = GameStatus.created
    world_seed: dict = Field(default_factory=dict)
    # v2 fields (nullable for v1 sessions, S30 FR-30.03 / S29)
    universe_id: UUID | None = None
    actors: list[UUID] = Field(default_factory=list)
    title: str | None = Field(default=None, max_length=80)
    summary: str | None = Field(default=None, max_length=200)
    turn_count: int = 0
    needs_recovery: bool = False
    total_cost_usd: float = 0.0
    cost_warning_sent: bool = False
    summary_generated_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_played_at: datetime | None = None
    paused_at: datetime | None = None
    deleted_at: datetime | None = None
    generation_profile: str = "balanced"


class GameState(BaseModel):
    """Snapshot of in-progress game state for a session."""

    session_id: UUID
    turn_number: int = 0
    current_location_id: str = "start"
    narrative_history: list[dict] = Field(default_factory=list)
    world_time: dict = Field(
        default_factory=lambda: {"total_ticks": 0}
    )  # v2 S34 — serialised WorldTime; default is tick-0 (FR-34.06a)


# ── API request schemas ──────────────────────────────────────────────────────


class CreateGameRequest(BaseModel):
    world_id: str | None = None
    preferences: dict[str, str | list[str]] = Field(default_factory=dict)
    generation_profile: str | None = Field(
        None,
        description="Canonical generation serving profile: fast, balanced, or quality.",
        pattern="^(fast|balanced|quality)$",
    )


_ZERO_WIDTH_CHARS = str.maketrans(
    "",
    "",
    "\u200b\u200c\u200d\u2060\ufeff\ufffe",
)


class SubmitTurnRequest(BaseModel):
    input: str = Field(
        ...,
        max_length=2000,
        description="Player's natural-language input.",
    )
    idempotency_key: UUID | None = Field(
        None,
        description="Client-generated UUID for deduplication.",
    )
    traffic_class: str | None = Field(
        None,
        description=(
            "Optional generation traffic class for non-interactive clients "
            "such as eval batches."
        ),
        pattern="^(interactive_player|interactive_smoke|bulk_eval|quality_benchmark)$",
    )

    @field_validator("input")
    @classmethod
    def strip_zero_width_chars(cls, v: str) -> str:
        """Remove invisible Unicode chars that defeat .strip()."""
        return v.translate(_ZERO_WIDTH_CHARS)


class UpdateGameRequest(BaseModel):
    status: str = Field(
        ...,
        description=(
            "Target status. Supported transitions depend on current "
            "game status (e.g. active → paused, paused → active/ended)."
        ),
    )


class DeleteGameRequest(BaseModel):
    confirm: bool = Field(
        ...,
        description="Must be true to confirm deletion (S27 FR-27.18).",
    )


# ── API response schemas ─────────────────────────────────────────────────────


class GameData(BaseModel):
    game_id: str
    player_id: str
    status: str
    turn_count: int
    generation_profile: str = "balanced"
    title: str | None = None
    summary: str | None = None
    narrative_intro: str | None = None
    genesis_status: GenesisStatus = GenesisStatus.complete
    genesis_error_code: str | None = None
    genesis_error_message: str | None = None
    character_name: str | None = None
    character_traits: list[str] = []
    created_at: datetime
    updated_at: datetime
    last_played_at: datetime | None = None


class GameSummary(BaseModel):
    game_id: str
    status: str
    turn_count: int
    generation_profile: str = "balanced"
    title: str | None = None
    summary: str | None = None
    created_at: datetime
    updated_at: datetime
    last_played_at: datetime | None = None


class PaginationMeta(BaseModel):
    next_cursor: str | None
    has_more: bool


class TurnAccepted(BaseModel):
    turn_id: str
    turn_number: int
    stream_url: str


class SaveResult(BaseModel):
    game_id: str
    saved_at: datetime
    turn_count: int


class GameEndedData(BaseModel):
    game_id: str
    status: str
    turn_count: int
    ended_at: datetime
