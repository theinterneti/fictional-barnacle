"""SSE event formatting utilities (plan §3.4)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

from tta.persistence.redis_session import _SSE_BUFFER_KEY as _BUFFER_KEY
from tta.persistence.redis_session import _SSE_COUNTER_KEY as _COUNTER_KEY

# Maximum number of events to retain per game in the replay buffer.
SSE_BUFFER_MAX_EVENTS = 100
# TTL (seconds) for the replay buffer sorted set.  FR-10.41: ≥5 min.
SSE_BUFFER_TTL_SECONDS = 300


class SSECounter:
    """Connection-scoped event ID counter."""

    def __init__(self) -> None:
        self._count = 0

    def next_id(self) -> int:
        self._count += 1
        return self._count


class SseEventBuffer:
    """Per-game Redis-backed SSE replay buffer (FR-10.41–10.44).

    Uses a Redis sorted set keyed by ``tta:sse_buffer:{game_id}`` where the
    score is the monotonic event ID and the member is the raw SSE string.
    A separate ``tta:sse_counter:{game_id}`` key provides globally unique,
    monotonically-increasing IDs across reconnections.

    All methods are static so they can be used as free functions without
    instantiating a buffer object per request.
    """

    @staticmethod
    async def get_next_id(redis: Redis, game_id: str) -> int:
        """Atomically increment and return the next event ID for *game_id*.

        Also refreshes the TTL on the counter key so it is reaped alongside
        the buffer sorted-set when the game session goes idle.
        """
        key = _COUNTER_KEY.format(game_id=game_id)
        eid = int(await redis.incr(key))
        await redis.expire(key, SSE_BUFFER_TTL_SECONDS)
        return eid

    @staticmethod
    async def append(
        redis: Redis,
        game_id: str,
        event_id: int,
        raw: str,
    ) -> None:
        """Append *raw* SSE string to the buffer under *event_id*.

        Enforces the 100-event cap (ZREMRANGEBYRANK) and refreshes the
        300-second rolling TTL on every write.
        """
        key = _BUFFER_KEY.format(game_id=game_id)
        await redis.zadd(key, {raw: float(event_id)})
        await redis.expire(key, SSE_BUFFER_TTL_SECONDS)
        # Remove oldest events beyond the cap.
        # ZREMRANGEBYRANK key 0 -(MAX+1): removes nothing when count ≤ MAX.
        await redis.zremrangebyrank(key, 0, -(SSE_BUFFER_MAX_EVENTS + 1))

    @staticmethod
    async def replay_after(
        redis: Redis,
        game_id: str,
        last_id: int,
    ) -> list[str] | None:
        """Return buffered events with ID > *last_id*, or *None* on a miss.

        A miss means the requested position has been evicted and the client
        must receive a full state snapshot instead.  Returns an empty list
        when *last_id* is current (nothing to replay).
        """
        key = _BUFFER_KEY.format(game_id=game_id)

        # Detect whether any events exist at or before last_id + 1.
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if not oldest:
            # Buffer completely empty — treat as a miss only if the client
            # claims to have seen some events already.
            return None if last_id > 0 else []

        # oldest[0] is (member, score) — decode_responses=True so member is str
        oldest_score = int(oldest[0][1])
        if oldest_score > last_id + 1:
            # The oldest buffered event is ahead of where the client left off.
            return None

        # HIT: return all events strictly after last_id.
        members = await redis.zrangebyscore(key, last_id + 1, "+inf")
        return list(members)  # already str due to decode_responses=True


def format_sse(
    event: str,
    data: Any,
    event_id: int | None = None,
) -> str:
    """Format a single SSE event per the HTML Living Standard (EventSource).

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
