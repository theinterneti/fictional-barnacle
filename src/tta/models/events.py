"""Typed SSE event models for server-to-client streaming."""

import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from tta.models.world import WorldChange


class EventType(StrEnum):
    """SSE event type discriminator."""

    # Legacy plans-based events (kept for backward compat with games.py)
    TURN_START = "turn_start"
    THINKING = "thinking"
    STILL_THINKING = "still_thinking"
    NARRATIVE_TOKEN = "narrative_token"
    NARRATIVE_BLOCK = "narrative_block"
    WORLD_UPDATE = "world_update"
    TURN_COMPLETE = "turn_complete"
    MODERATION = "moderation"
    KEEPALIVE = "keepalive"
    # S10 §6.2 canonical event taxonomy
    NARRATIVE = "narrative"
    NARRATIVE_END = "narrative_end"
    STATE_UPDATE = "state_update"
    LOCATION_CHANGE = "location_change"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class SSEEvent(BaseModel):
    """Base SSE event."""

    event_type: EventType

    def format_sse(self, event_id: int | None = None) -> str:
        """Format as SSE wire format."""
        data = self.model_dump(exclude={"event_type"}, mode="json")
        id_line = f"id: {event_id}\n" if event_id is not None else ""
        payload = json.dumps(data, default=str)
        return f"{id_line}event: {self.event_type}\ndata: {payload}\n\n"


class TurnStartEvent(SSEEvent):
    """Signals the beginning of a new turn."""

    event_type: EventType = EventType.TURN_START
    turn_id: str | None = None
    turn_number: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NarrativeTokenEvent(SSEEvent):
    """A single streamed token of narrative text."""

    event_type: EventType = EventType.NARRATIVE_TOKEN
    token: str


class NarrativeBlockEvent(SSEEvent):
    """Complete narrative block after streaming finishes."""

    event_type: EventType = EventType.NARRATIVE_BLOCK
    full_text: str


class WorldUpdateEvent(SSEEvent):
    """World-state mutations applied this turn."""

    event_type: EventType = EventType.WORLD_UPDATE
    changes: list[WorldChange]


class ThinkingEvent(SSEEvent):
    """Signals the server is processing (shown as thinking indicator)."""

    event_type: EventType = EventType.THINKING


class StillThinkingEvent(SSEEvent):
    """Sent after 3s if generation is still running."""

    event_type: EventType = EventType.STILL_THINKING


class TurnCompleteEvent(SSEEvent):
    """Signals the turn is fully processed."""

    event_type: EventType = EventType.TURN_COMPLETE
    turn_number: int
    model_used: str
    latency_ms: float
    suggested_actions: list[str] = Field(default_factory=list)


class ModerationEvent(SSEEvent):
    """Notifies the client that content was moderated (FR-24.08).

    The ``reason`` field provides a generic, player-safe explanation.
    Category details are never leaked to the client.
    """

    event_type: EventType = EventType.MODERATION
    reason: str


class ErrorEvent(SSEEvent):
    """Reports an error to the client (FR-23.20, S23 §3.1 envelope)."""

    event_type: EventType = EventType.ERROR
    code: str
    message: str
    turn_id: str | None = None
    correlation_id: str | None = None
    retry_after_seconds: int | None = None
    details: dict | None = None


class KeepaliveEvent(SSEEvent):
    """Empty heartbeat to keep the connection alive."""

    event_type: EventType = EventType.KEEPALIVE


# ---------------------------------------------------------------------------
# S10 §6.2 canonical SSE event taxonomy
# ---------------------------------------------------------------------------


class NarrativeEvent(SSEEvent):
    """Streamed narrative chunk (S10 §6.2).

    ``sequence`` is a 0-indexed per-turn counter so the client can detect gaps.
    """

    event_type: EventType = EventType.NARRATIVE
    text: str
    turn_id: str
    sequence: int = Field(ge=0)


class NarrativeEndEvent(SSEEvent):
    """Signals that all narrative chunks for a turn have been sent (S10 §6.2)."""

    event_type: EventType = EventType.NARRATIVE_END
    turn_id: str
    total_chunks: int


class StateUpdateEvent(WorldUpdateEvent):
    """S10 §6.2 spec-compliant alias for WorldUpdateEvent (state_update event name).

    Inherits all fields from WorldUpdateEvent; only overrides the event_type so
    SSE wire output carries ``event: state_update`` instead of ``event: world_update``.
    WorldUpdateEvent is kept for backwards compatibility until Task 2 migrates games.py.
    """

    event_type: EventType = EventType.STATE_UPDATE


class LocationChangeEvent(SSEEvent):
    """Player has moved to a new location (S10 §6.2)."""

    event_type: EventType = EventType.LOCATION_CHANGE
    location_id: str
    name: str
    description: str
    exits: list[str]


class HeartbeatEvent(SSEEvent):
    """Periodic heartbeat to keep the SSE connection alive (S10 §6.2)."""

    event_type: EventType = EventType.HEARTBEAT
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
