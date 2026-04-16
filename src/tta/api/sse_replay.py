"""SSE replay primitives for resumable EventSource streams (S10 FR-10.41..10.44)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Literal

ReplayLookup = Literal["hit", "unavailable"]


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """Single SSE event in the replay buffer."""

    event_id: int
    payload: str
    created_at: float


def parse_last_event_id(header_value: str | None) -> int | None:
    """Parse Last-Event-ID header as a positive integer or ``None``.

    Event IDs used by this service are positive integer sequence values.
    Unknown/invalid values are ignored to preserve stream compatibility.
    """
    if header_value is None:
        return None
    value = header_value.strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


class SSEReplayBuffer:
    """In-memory replay store.

    Retention policy implements FR-10.42:
    keep at least ``min_events`` OR ``min_seconds`` worth of events, whichever
    requires keeping more.
    """

    def __init__(
        self,
        *,
        min_events: int = 100,
        min_seconds: float = 300.0,
    ) -> None:
        if min_events <= 0:
            msg = "min_events must be positive"
            raise ValueError(msg)
        if min_seconds <= 0:
            msg = "min_seconds must be positive"
            raise ValueError(msg)
        self._min_events = min_events
        self._min_seconds = min_seconds
        self._events: deque[ReplayEvent] = deque()

    @property
    def size(self) -> int:
        return len(self._events)

    @property
    def oldest_event_id(self) -> int | None:
        if not self._events:
            return None
        return self._events[0].event_id

    @property
    def newest_event_id(self) -> int | None:
        if not self._events:
            return None
        return self._events[-1].event_id

    def append(self, event_id: int, payload: str) -> None:
        now = monotonic()
        self._events.append(
            ReplayEvent(event_id=event_id, payload=payload, created_at=now)
        )
        self._prune(now=now)

    def events_after(self, last_event_id: int) -> tuple[ReplayLookup, list[str]]:
        """Return replay events after ``last_event_id``.

        Returns:
        - (``"hit"``, payloads) when replay can be served from buffer
        - (``"unavailable"``, []) when requested id predates current buffer
        """
        if not self._events:
            return "unavailable", []

        oldest = self._events[0].event_id
        if last_event_id < oldest:
            return "unavailable", []

        payloads = [e.payload for e in self._events if e.event_id > last_event_id]
        return "hit", payloads

    def _prune(self, *, now: float) -> None:
        cutoff = now - self._min_seconds
        while len(self._events) > self._min_events:
            oldest = self._events[0]
            if oldest.created_at >= cutoff:
                break
            self._events.popleft()
