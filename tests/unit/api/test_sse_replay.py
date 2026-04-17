"""Unit tests for SseEventBuffer — SSE replay/reconnect buffer.

Spec ref: S10 §6.6 FR-10.40–10.44.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from tta.api.sse import (
    SSE_BUFFER_MAX_EVENTS,
    SSE_BUFFER_TTL_SECONDS,
    SseEventBuffer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_redis(
    *,
    incr_return: int = 1,
    zcard_return: int = 0,
    zrange_return: list[tuple[str, float]] | None = None,
    zrangebyscore_return: list[str] | None = None,
) -> MagicMock:
    """Build a minimal async Redis mock for SseEventBuffer tests."""
    r = MagicMock()
    r.incr = AsyncMock(return_value=incr_return)
    r.zadd = AsyncMock(return_value=1)
    r.zremrangebyrank = AsyncMock(return_value=0)
    r.expire = AsyncMock(return_value=1)
    r.zcard = AsyncMock(return_value=zcard_return)
    r.zrange = AsyncMock(return_value=zrange_return or [])
    r.zrangebyscore = AsyncMock(return_value=zrangebyscore_return or [])
    return r


# ---------------------------------------------------------------------------
# get_next_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_next_id_increments_counter() -> None:
    r = _make_redis(incr_return=7)
    eid = await SseEventBuffer.get_next_id(r, "game-abc")
    assert eid == 7
    r.incr.assert_awaited_once_with("tta:sse_counter:game-abc")
    r.expire.assert_awaited_once_with(
        "tta:sse_counter:game-abc", SSE_BUFFER_TTL_SECONDS
    )


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_stores_event_and_refreshes_ttl() -> None:
    r = _make_redis(incr_return=3)
    await SseEventBuffer.append(r, "game-1", 3, "data: hello\n\n")

    # redis-py zadd mapping: {member: score}
    r.zadd.assert_awaited_once_with("tta:sse_buffer:game-1", {"data: hello\n\n": 3.0})
    r.expire.assert_awaited_once_with("tta:sse_buffer:game-1", SSE_BUFFER_TTL_SECONDS)


@pytest.mark.asyncio
async def test_append_evicts_oldest_when_over_cap() -> None:
    r = _make_redis()
    await SseEventBuffer.append(r, "game-1", 1, "data: a\n\n")

    # ZREMRANGEBYRANK should always be called to enforce the cap
    r.zremrangebyrank.assert_awaited_once_with(
        "tta:sse_buffer:game-1", 0, -(SSE_BUFFER_MAX_EVENTS + 1)
    )


# ---------------------------------------------------------------------------
# replay_after — HIT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_after_hit_returns_events() -> None:
    r = _make_redis(
        zcard_return=3,
        zrange_return=[("data: a\n\n", 1.0)],
        zrangebyscore_return=["data: b\n\n", "data: c\n\n"],
    )
    result = await SseEventBuffer.replay_after(r, "game-1", last_id=5)
    assert result == ["data: b\n\n", "data: c\n\n"]
    # Should query events with score > last_id
    r.zrangebyscore.assert_awaited_once_with("tta:sse_buffer:game-1", 6, "+inf")


@pytest.mark.asyncio
async def test_replay_after_hit_empty_range_means_up_to_date() -> None:
    """last_id is current head → nothing to replay, but it's a HIT (not miss)."""
    r = _make_redis(
        zcard_return=5,
        zrange_return=[("data: first\n\n", 1.0)],
        zrangebyscore_return=[],
    )
    result = await SseEventBuffer.replay_after(r, "game-1", last_id=10)
    assert result == []


# ---------------------------------------------------------------------------
# replay_after — MISS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_after_miss_empty_buffer_with_nonzero_last_id() -> None:
    """Buffer empty but client has last_id>0 → events evicted → MISS."""
    r = _make_redis(zcard_return=0, zrange_return=[])
    result = await SseEventBuffer.replay_after(r, "game-1", last_id=5)
    assert result is None


@pytest.mark.asyncio
async def test_replay_after_miss_oldest_score_after_last_id() -> None:
    """Oldest buffered event is newer than last_id+1 → gap → MISS."""
    # last_id=3, oldest event has score=10 → events 4–9 evicted
    r = _make_redis(
        zcard_return=5,
        zrange_return=[("data: x\n\n", 10.0)],  # oldest score=10
    )
    result = await SseEventBuffer.replay_after(r, "game-1", last_id=3)
    assert result is None


# ---------------------------------------------------------------------------
# replay_after — fresh connect (last_id == 0, empty buffer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_after_fresh_connect_empty_buffer() -> None:
    """Fresh connection with no prior events → return [] (not None)."""
    r = _make_redis(zcard_return=0, zrange_return=[])
    result = await SseEventBuffer.replay_after(r, "game-1", last_id=0)
    assert result == []


@pytest.mark.asyncio
async def test_replay_after_fresh_connect_with_existing_events() -> None:
    """last_id=0 with events in buffer → return all events."""
    events = ["data: a\n\n", "data: b\n\n"]
    r = _make_redis(
        zcard_return=2,
        zrange_return=[("data: a\n\n", 1.0)],
        zrangebyscore_return=events,
    )
    result = await SseEventBuffer.replay_after(r, "game-1", last_id=0)
    assert result == events
    r.zrangebyscore.assert_awaited_once_with("tta:sse_buffer:game-1", 1, "+inf")


# ---------------------------------------------------------------------------
# Cap enforcement (integration-style mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cap_enforced_at_100_events() -> None:
    """After 101 appends, oldest entry should be evicted."""
    r = _make_redis()
    for i in range(1, 102):
        await SseEventBuffer.append(r, "game-x", i, f"data: {i}\n\n")

    # Each append calls ZREMRANGEBYRANK once
    assert r.zremrangebyrank.await_count == 101
    # All calls use the same cap expression
    for c in r.zremrangebyrank.await_args_list:
        assert c == call("tta:sse_buffer:game-x", 0, -(SSE_BUFFER_MAX_EVENTS + 1))


# ---------------------------------------------------------------------------
# TTL refresh on every append
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ttl_refreshed_on_each_append() -> None:
    r = _make_redis()
    for i in range(1, 4):
        await SseEventBuffer.append(r, "g", i, f"data: {i}\n\n")
    assert r.expire.await_count == 3
    for c in r.expire.await_args_list:
        assert c == call("tta:sse_buffer:g", SSE_BUFFER_TTL_SECONDS)
