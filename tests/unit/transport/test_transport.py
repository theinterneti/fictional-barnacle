"""Unit tests for the NarrativeTransport protocol and concrete implementations.

Covers AC-32.01 through AC-32.10.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tta.transport import (
    MemoryTransport,
    NarrativeTransport,
    SSETransport,
    split_narrative,
)

# ---------------------------------------------------------------------------
# split_narrative  (AC-32.07)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-32.07")
def test_split_narrative_empty_returns_empty():
    assert split_narrative("") == []
    assert split_narrative("   ") == []


@pytest.mark.spec("AC-32.07")
def test_split_narrative_single_sentence():
    result = split_narrative("Hello, world.")
    assert result == ["Hello, world."]


@pytest.mark.spec("AC-32.07")
def test_split_narrative_multiple_sentences():
    text = "First sentence. Second sentence! Third sentence?"
    result = split_narrative(text)
    assert result == ["First sentence.", "Second sentence!", "Third sentence?"]


@pytest.mark.spec("AC-32.07")
def test_split_narrative_strips_whitespace():
    text = "  Leading.  Trailing.  "
    result = split_narrative(text)
    assert all(chunk == chunk.strip() for chunk in result)


# ---------------------------------------------------------------------------
# MemoryTransport — basic send_* behaviour (AC-32.02–32.05)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-32.02")
@pytest.mark.asyncio
async def test_memory_transport_send_narrative_chunks():
    t = MemoryTransport()
    text = "First sentence. Second sentence."
    count = await t.send_narrative(text, turn_id="t1")

    narrative_events = [e for e in t.events if e["event"] == "narrative"]
    assert count == len(narrative_events)
    assert count == 2
    assert narrative_events[0]["sequence"] == 0
    assert narrative_events[1]["sequence"] == 1
    assert narrative_events[0]["turn_id"] == "t1"


@pytest.mark.spec("AC-32.03")
@pytest.mark.asyncio
async def test_memory_transport_send_end_records_event():
    t = MemoryTransport()
    await t.send_end(turn_id="t1", total_chunks=3)

    assert len(t.events) == 1
    ev = t.events[0]
    assert ev["event"] == "narrative_end"
    assert ev["turn_id"] == "t1"
    assert ev["total_chunks"] == 3


@pytest.mark.spec("AC-32.04")
@pytest.mark.asyncio
async def test_memory_transport_send_heartbeat_records_event():
    t = MemoryTransport()
    await t.send_heartbeat()

    assert len(t.events) == 1
    assert t.events[0]["event"] == "heartbeat"


@pytest.mark.asyncio
async def test_memory_transport_send_error_records_event():
    t = MemoryTransport()
    await t.send_error(
        code="TEST_ERROR",
        message="Something broke",
        turn_id="t1",
        correlation_id="c1",
        retry_after_seconds=3,
    )

    assert len(t.events) == 1
    ev = t.events[0]
    assert ev["event"] == "error"
    assert ev["code"] == "TEST_ERROR"
    assert ev["retry_after_seconds"] == 3


@pytest.mark.asyncio
async def test_memory_transport_send_moderation_records_event():
    t = MemoryTransport()
    await t.send_moderation(reason="Safety redirect")

    assert len(t.events) == 1
    assert t.events[0]["event"] == "moderation"
    assert t.events[0]["reason"] == "Safety redirect"


@pytest.mark.asyncio
async def test_memory_transport_send_state_update_records_event():
    t = MemoryTransport()
    changes = [{"type": "location_changed", "entity_id": "loc1"}]
    await t.send_state_update(changes)

    assert len(t.events) == 1
    assert t.events[0]["event"] == "state_update"
    assert t.events[0]["changes"] == changes


# ---------------------------------------------------------------------------
# Protocol conformance (AC-32.05, AC-32.06)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-32.01")
def test_narrative_transport_is_runtime_checkable():
    """NarrativeTransport must be a @runtime_checkable Protocol."""
    from typing import Protocol

    assert issubclass(NarrativeTransport, Protocol)
    # runtime_checkable means isinstance() works
    t = MemoryTransport()
    assert isinstance(t, NarrativeTransport)


@pytest.mark.spec("AC-32.05")
def test_memory_transport_satisfies_protocol():
    t = MemoryTransport()
    assert isinstance(t, NarrativeTransport)


@pytest.mark.spec("AC-32.06")
def test_sse_transport_satisfies_protocol():
    emit = AsyncMock(return_value="data: x\n\n")
    t = SSETransport(redis=None, game_id="g1", emit=emit)  # type: ignore[arg-type]
    assert isinstance(t, NarrativeTransport)


# ---------------------------------------------------------------------------
# AC-32.08 — after close(), all send_* are silent no-ops
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-32.08")
@pytest.mark.asyncio
async def test_memory_transport_no_ops_after_close():
    t = MemoryTransport()
    await t.close()

    assert not t.is_connected

    await t.send_narrative("text", turn_id="t1")
    await t.send_end(turn_id="t1", total_chunks=0)
    await t.send_heartbeat()
    await t.send_error(code="X", message="x", turn_id=None, correlation_id=None)
    await t.send_state_update([])
    await t.send_moderation(reason="r")

    assert t.events == []


@pytest.mark.spec("AC-32.08")
@pytest.mark.asyncio
async def test_sse_transport_no_ops_after_close():
    emit = AsyncMock(return_value="data: x\n\n")
    t = SSETransport(redis=None, game_id="g1", emit=emit)  # type: ignore[arg-type]
    await t.close()

    assert not t.is_connected

    count = await t.send_narrative("text", turn_id="t1")
    await t.send_end(turn_id="t1", total_chunks=0)
    await t.send_heartbeat()
    await t.send_error(code="X", message="x", turn_id=None, correlation_id=None)
    await t.send_state_update([])
    await t.send_moderation(reason="r")

    assert count == 0
    emit.assert_not_called()


# ---------------------------------------------------------------------------
# SSETransport — emit delegation (AC-32.09, AC-32.10)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-32.09")
@pytest.mark.asyncio
async def test_sse_transport_send_narrative_calls_emit_once_per_chunk():
    """SSETransport.send_narrative() calls _emit once for every chunk."""
    emit = AsyncMock(return_value="data: x\n\n")
    t = SSETransport(redis=None, game_id="g1", emit=emit)  # type: ignore[arg-type]

    text = "First sentence. Second sentence. Third sentence."
    await t.send_narrative(text, turn_id="t1")

    # split_narrative("First sentence. Second sentence. Third sentence.") => 3 chunks
    assert emit.call_count == 3


@pytest.mark.spec("AC-32.10")
@pytest.mark.asyncio
async def test_sse_transport_send_narrative_returns_chunk_count():
    """SSETransport.send_narrative() returns the number of chunks emitted."""
    emit = AsyncMock(return_value="data: x\n\n")
    t = SSETransport(redis=None, game_id="g1", emit=emit)  # type: ignore[arg-type]

    text = "One. Two."
    count = await t.send_narrative(text, turn_id="t1")

    assert count == 2
    assert emit.call_count == count
