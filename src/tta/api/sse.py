"""SSE event formatting utilities (plan §3.4)."""

from __future__ import annotations

import json
from typing import Any


class SSECounter:
    """Connection-scoped event ID counter."""

    def __init__(self) -> None:
        self._count = 0

    def next_id(self) -> int:
        self._count += 1
        return self._count


def format_sse(
    event: str,
    data: Any,
    event_id: int | None = None,
) -> str:
    """Format a single SSE event per RFC 8895.

    Parameters
    ----------
    event:
        The event type name (e.g. ``connected``, ``narrative_token``).
    data:
        JSON-serialisable payload.
    event_id:
        Optional explicit event ID. If *None*, caller should supply
        one from a connection-scoped :class:`SSECounter`.

    Returns
    -------
    str
        A fully formatted SSE event block ending with ``\\n\\n``.
    """
    payload = json.dumps(data, default=str)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {line}" for line in lines)
    id_line = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_line}event: {event}\n{data_lines}\n\n"
