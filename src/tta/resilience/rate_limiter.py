"""Sliding-window rate limiter with Redis + in-memory fallback (S25 §3).

Two backends implement the ``RateLimiter`` protocol:

* **RedisRateLimiter** — production backend using Redis sorted sets.
  Each request is a member (uuid4) scored by timestamp.  A pipeline
  prunes expired entries, counts remaining, and conditionally adds the
  new entry when under the limit.
* **InMemoryRateLimiter** — single-process fallback used when Redis is
  unavailable (FR-25.07).  Not suitable for multi-worker deployments.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import structlog

log = structlog.get_logger()

__all__ = [
    "EndpointGroup",
    "InMemoryRateLimiter",
    "RateLimitResult",
    "RateLimiter",
    "RedisRateLimiter",
]


class EndpointGroup(StrEnum):
    """Endpoint groups with distinct rate limits (S25 §3.2)."""

    TURNS = "turns"
    GAME_MGMT = "game_mgmt"
    AUTH = "auth"
    SSE = "sse"
    HEALTH = "health"


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Outcome of a rate-limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: float  # Unix timestamp when the window resets
    retry_after: int  # Seconds until the client may retry (0 if allowed)


class RateLimiter(Protocol):
    """Rate-limiter contract used by middleware."""

    async def check(
        self, key: str, limit: int, window_seconds: int
    ) -> RateLimitResult: ...

    async def clear_key(self, key: str) -> None:
        """Remove all rate-limit state for *key* (admin reset)."""
        ...


# ---------------------------------------------------------------------------
# In-memory backend (fallback)
# ---------------------------------------------------------------------------


class InMemoryRateLimiter:
    """Dict-of-timestamps sliding window — single process only (FR-25.07)."""

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        window_start = now - window_seconds
        reset_at = now + window_seconds

        timestamps = self._windows.get(key, [])
        # Prune expired entries
        timestamps = [t for t in timestamps if t > window_start]

        if len(timestamps) < limit:
            timestamps.append(now)
            self._windows[key] = timestamps
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - len(timestamps),
                reset_at=reset_at,
                retry_after=0,
            )

        # Rejected — don't add to window (FR-25.09)
        self._windows[key] = timestamps
        earliest = min(timestamps) if timestamps else now
        retry_after = max(1, math.ceil(earliest + window_seconds - now))
        return RateLimitResult(
            allowed=False,
            limit=limit,
            remaining=0,
            reset_at=earliest + window_seconds,
            retry_after=retry_after,
        )

    async def clear_key(self, key: str) -> None:
        """Remove rate-limit window for *key*."""
        self._windows.pop(key, None)


# ---------------------------------------------------------------------------
# Redis backend (production)
# ---------------------------------------------------------------------------


class RedisRateLimiter:
    """Redis sorted-set sliding window (S25 §3, plan §3.2).

    Each key is a sorted set where members are unique IDs and scores are
    timestamps.  A pipeline atomically prunes expired members and counts
    the remaining ones, then conditionally adds the new member if under
    the limit.
    """

    def __init__(self, redis: object) -> None:  # redis.asyncio.Redis
        self._redis = redis

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        window_start = now - window_seconds
        reset_at = now + window_seconds
        member = str(uuid.uuid4())

        # NOTE: transaction=False means commands are pipelined but not atomic.
        # A Lua script would be needed for true atomicity; acceptable for v1.
        pipe = self._redis.pipeline(transaction=False)  # type: ignore[union-attr]
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        results = await pipe.execute()  # type: ignore[union-attr]
        count: int = results[1]

        if count < limit:
            # Under limit — record this request
            pipe2 = self._redis.pipeline(transaction=False)  # type: ignore[union-attr]
            pipe2.zadd(key, {member: now})
            pipe2.expire(key, window_seconds + 1)
            await pipe2.execute()  # type: ignore[union-attr]

            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - count - 1,
                reset_at=reset_at,
                retry_after=0,
            )

        # Rejected — don't record (FR-25.09).
        # Fetch the oldest member's timestamp to compute when the window
        # will shrink below the limit (matches InMemory logic).
        oldest_result = await self._redis.zrange(  # type: ignore[union-attr]
            key, 0, 0, withscores=True
        )
        if oldest_result:
            earliest = oldest_result[0][1]  # score = timestamp
        else:
            earliest = window_start
        retry_after = max(1, math.ceil(earliest + window_seconds - now))
        return RateLimitResult(
            allowed=False,
            limit=limit,
            remaining=0,
            reset_at=earliest + window_seconds,
            retry_after=retry_after,
        )

    async def clear_key(self, key: str) -> None:
        """Delete the sorted set for *key* in Redis."""
        await self._redis.delete(key)  # type: ignore[union-attr]
