"""SSETransport: delivers narrative events over a FastAPI SSE stream (S32)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from tta.transport._chunking import split_narrative

if TYPE_CHECKING:
    from redis.asyncio import Redis


class SSETransport:
    """Wraps the per-request SSE ``_emit`` callable to deliver narrative events.

    All ``send_*`` methods import event classes locally (FR-32.05a) so that
    ``games.py`` no longer needs to import them directly.

    After calling any ``send_*`` method, the caller should drain the
    ``_emit`` closure's ``_pending`` buffer and yield those raw SSE strings.

    Parameters
    ----------
    redis:
        The Redis client (passed through to ``emit`` for buffer writes).
    game_id:
        The game session ID string used for SSE buffer keys.
    emit:
        The ``_emit`` async closure from ``event_stream()``.  It must:
          1. Obtain a monotonic event ID from Redis.
          2. Format the event as a raw SSE string.
          3. Append to the connection-scoped ``_pending`` list.
          4. Return the raw string.
    """

    def __init__(
        self,
        redis: Redis,
        game_id: str,
        emit: Callable[[Any], Awaitable[str]],
    ) -> None:
        self._redis = redis
        self._game_id = game_id
        self._emit = emit
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_narrative(self, text: str, turn_id: str) -> int:
        """Emit narrative text as sentence-aligned chunks (AC-32.02).

        Returns the total number of chunks emitted (0 when disconnected).
        """
        if not self._connected:
            return 0

        # Import locally so games.py can remove these imports (FR-32.05a).
        from tta.models.events import NarrativeEvent  # noqa: PLC0415

        chunks = split_narrative(text)
        for i, chunk in enumerate(chunks):
            await self._emit(NarrativeEvent(text=chunk, turn_id=turn_id, sequence=i))
        return len(chunks)

    async def send_end(self, turn_id: str, total_chunks: int) -> None:
        """Emit a narrative_end event (AC-32.03)."""
        if not self._connected:
            return

        from tta.models.events import NarrativeEndEvent  # noqa: PLC0415

        await self._emit(NarrativeEndEvent(turn_id=turn_id, total_chunks=total_chunks))

    async def send_error(
        self,
        code: str,
        message: str,
        turn_id: str | None,
        correlation_id: str | None,
        retry_after_seconds: int = 0,
    ) -> None:
        """Emit an error event."""
        if not self._connected:
            return

        from tta.models.events import ErrorEvent  # noqa: PLC0415

        await self._emit(
            ErrorEvent(
                code=code,
                message=message,
                turn_id=turn_id,
                correlation_id=correlation_id,
                retry_after_seconds=retry_after_seconds,
            )
        )

    async def send_heartbeat(self) -> None:
        """Emit a heartbeat event (AC-32.04)."""
        if not self._connected:
            return

        from tta.models.events import HeartbeatEvent  # noqa: PLC0415

        await self._emit(HeartbeatEvent())

    async def send_state_update(self, changes: list[Any]) -> None:
        """Emit a state_update event."""
        if not self._connected:
            return

        from tta.models.events import StateUpdateEvent  # noqa: PLC0415

        await self._emit(StateUpdateEvent(changes=changes))

    async def send_moderation(self, reason: str) -> None:
        """Emit a moderation event."""
        if not self._connected:
            return

        from tta.models.events import ModerationEvent  # noqa: PLC0415

        await self._emit(ModerationEvent(reason=reason))

    async def close(self) -> None:
        """Mark this transport as disconnected (AC-32.08)."""
        self._connected = False
