"""Typed SSE event models for server-to-client streaming."""

import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from tta.models.world import WorldChange


class EventType(StrEnum):
    """SSE event type discriminator."""

    TURN_START = "turn_start"
    THINKING = "thinking"
    STILL_THINKING = "still_thinking"
    NARRATIVE_TOKEN = "narrative_token"
    NARRATIVE_BLOCK = "narrative_block"
    WORLD_UPDATE = "world_update"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"
    KEEPALIVE = "keepalive"


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


class ErrorEvent(SSEEvent):
    """Reports an error to the client (FR-23.20, S23 §3.1 envelope)."""

    event_type: EventType = EventType.ERROR
    code: str
    message: str
    correlation_id: str | None = None
    retry_after_seconds: int | None = None
    details: dict | None = None


class KeepaliveEvent(SSEEvent):
    """Empty heartbeat to keep the connection alive."""

    event_type: EventType = EventType.KEEPALIVE
