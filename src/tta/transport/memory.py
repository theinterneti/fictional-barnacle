"""MemoryTransport: in-memory transport for tests (S32 AC-32.05)."""

from __future__ import annotations

from typing import Any

from tta.transport._chunking import split_narrative


class MemoryTransport:
    """An in-memory NarrativeTransport for unit and integration tests.

    Records every delivered event to ``self.events`` as plain dicts so tests
    can make simple assertions without parsing SSE wire format.  No I/O is
    performed.  Obeys the disconnected-discard rule (AC-32.08).
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def send_narrative(self, text: str, turn_id: str) -> int:
        if not self._connected:
            return 0
        chunks = split_narrative(text)
        for i, chunk in enumerate(chunks):
            self.events.append(
                {
                    "event": "narrative",
                    "text": chunk,
                    "turn_id": turn_id,
                    "sequence": i,
                }
            )
        return len(chunks)

    async def send_end(self, turn_id: str, total_chunks: int) -> None:
        if not self._connected:
            return
        self.events.append(
            {
                "event": "narrative_end",
                "turn_id": turn_id,
                "total_chunks": total_chunks,
            }
        )

    async def send_error(
        self,
        code: str,
        message: str,
        turn_id: str | None,
        correlation_id: str | None,
        retry_after_seconds: int = 0,
    ) -> None:
        if not self._connected:
            return
        self.events.append(
            {
                "event": "error",
                "code": code,
                "message": message,
                "turn_id": turn_id,
                "correlation_id": correlation_id,
                "retry_after_seconds": retry_after_seconds,
            }
        )

    async def send_heartbeat(self) -> None:
        if not self._connected:
            return
        self.events.append({"event": "heartbeat"})

    async def send_state_update(self, changes: list[Any]) -> None:
        if not self._connected:
            return
        self.events.append({"event": "state_update", "changes": changes})

    async def send_moderation(self, reason: str) -> None:
        if not self._connected:
            return
        self.events.append({"event": "moderation", "reason": reason})

    async def close(self) -> None:
        self._connected = False
