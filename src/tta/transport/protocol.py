"""NarrativeTransport protocol (S32 AC-32.01)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NarrativeTransport(Protocol):
    """Protocol for narrative event delivery.

    All send_* methods are no-ops when ``is_connected`` is False (AC-32.08).
    """

    @property
    def is_connected(self) -> bool:
        """Return True if this transport can still deliver events."""
        ...

    async def send_narrative(self, text: str, turn_id: str) -> int:
        """Emit narrative text as sentence-aligned chunks.

        Returns the total number of chunks emitted (AC-32.02).
        """
        ...

    async def send_end(self, turn_id: str, total_chunks: int) -> None:
        """Emit a narrative_end event (AC-32.03)."""
        ...

    async def send_error(
        self,
        code: str,
        message: str,
        turn_id: str | None,
        correlation_id: str | None,
        retry_after_seconds: int = 0,
    ) -> None:
        """Emit an error event."""
        ...

    async def send_heartbeat(self) -> None:
        """Emit a heartbeat event (AC-32.04)."""
        ...

    async def send_state_update(self, changes: list[Any]) -> None:
        """Emit a state_update event."""
        ...

    async def send_moderation(self, reason: str) -> None:
        """Emit a moderation event."""
        ...

    async def close(self) -> None:
        """Mark this transport as disconnected."""
        ...
