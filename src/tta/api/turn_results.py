"""Turn result store — delivers pipeline results to SSE consumers.

Provides a Protocol with two implementations:
- InMemoryTurnResultStore: asyncio.Event-based, for testing / single-worker
- RedisTurnResultStore: pub/sub + GET fallback, for production multi-worker

The Redis implementation handles the race condition where the SSE client
subscribes *after* the pipeline publishes by storing results as Redis
keys with a TTL backup.  Keys are scoped by turn_id (not game_id) to
prevent cross-turn pollution when a player submits rapidly.

Backup keys are NOT deleted on read — TTL handles cleanup.  This allows
multiple consumers (reconnects, duplicate tabs) to safely read the same
result.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

import structlog
from redis.asyncio import Redis

from tta.models.turn import TurnState

log = structlog.get_logger()

_KEY_PREFIX = "tta:turn_result:"
_CHANNEL_PREFIX = "tta:turn_result:"
_RESULT_TTL_SECONDS = 300  # 5 minutes


class TurnResultStore(Protocol):
    """Abstract store for delivering pipeline results to SSE consumers.

    Contract: publish() may be called before or after wait_for_result().
    Both orderings must deliver the result exactly once per waiter.
    """

    async def publish(self, turn_id: str, result: TurnState) -> None:
        """Publish a completed turn result, keyed by turn_id."""
        ...

    async def wait_for_result(
        self, turn_id: str, *, timeout: float = 120.0
    ) -> TurnState | None:
        """Wait for a turn result, returning None on timeout."""
        ...


class InMemoryTurnResultStore:
    """Event-based in-memory store — no polling, suitable for tests."""

    def __init__(self) -> None:
        self._results: dict[str, TurnState] = {}
        self._events: dict[str, asyncio.Event] = {}

    async def publish(self, turn_id: str, result: TurnState) -> None:
        self._results[turn_id] = result
        event = self._events.get(turn_id)
        if event is not None:
            event.set()

    async def wait_for_result(
        self, turn_id: str, *, timeout: float = 120.0
    ) -> TurnState | None:
        # Late-client path: result already available
        if turn_id in self._results:
            return self._results[turn_id]

        event = self._events.setdefault(turn_id, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            return None
        finally:
            self._events.pop(turn_id, None)

        return self._results.get(turn_id)


class RedisTurnResultStore:
    """Redis-backed store using pub/sub with GET fallback.

    Flow:
    - publish(): SET key (TTL) + PUBLISH channel
    - wait_for_result(): SUBSCRIBE first, then GET (closes race window),
      then wait for pub/sub message.  Backup keys are never deleted —
      TTL handles cleanup.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, turn_id: str, result: TurnState) -> None:
        key = f"{_KEY_PREFIX}{turn_id}"
        channel = f"{_CHANNEL_PREFIX}{turn_id}"
        payload = result.model_dump_json()

        # SET with TTL first so late clients can GET
        await self._redis.set(key, payload, ex=_RESULT_TTL_SECONDS)
        # Then notify any waiting subscribers
        await self._redis.publish(channel, payload)
        log.debug("turn_result_published", turn_id=turn_id)

    async def wait_for_result(
        self, turn_id: str, *, timeout: float = 120.0
    ) -> TurnState | None:
        key = f"{_KEY_PREFIX}{turn_id}"
        channel = f"{_CHANNEL_PREFIX}{turn_id}"

        # Subscribe FIRST to close the race window, then check backup key
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(channel)

            # Now check backup key — if result arrived before we
            # subscribed, it's here.  If it arrives after, we'll
            # catch the PUBLISH message.
            stored = await self._redis.get(key)
            if stored is not None:
                return TurnState.model_validate_json(stored)

            # Wait for pub/sub message
            end_time = asyncio.get_event_loop().time() + timeout
            while True:
                remaining = end_time - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=min(remaining, 1.0),
                )
                if msg is not None and msg["type"] == "message":
                    data = msg["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    return TurnState.model_validate_json(data)

        except Exception:
            log.error("redis_wait_failed", turn_id=turn_id, exc_info=True)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

        return None
