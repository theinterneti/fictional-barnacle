"""Unit tests for World Memory Writer (S37, AC-37.01–37.08)."""

from __future__ import annotations

from uuid import UUID

import pytest

from tta.simulation.types import MemoryRecord, WorldTime
from tta.simulation.world_memory import InMemoryMemoryWriter, _score_importance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORLD_TIME = WorldTime(
    total_ticks=10,
    day_count=0,
    hour=9,
    minute=0,
    time_of_day_label="morning",
)

_UNIVERSE_ID = "01J00000000000000000000000"
_SESSION_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")


async def _record(
    writer: InMemoryMemoryWriter,
    *,
    turn: int = 1,
    source: str = "player",
    content: str = "Something happened",
    tags: list[str] | None = None,
    npc_tier: str | None = None,
    severity: str | None = None,
    world_time: WorldTime = _WORLD_TIME,
) -> MemoryRecord:
    return await writer.record(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        turn_number=turn,
        world_time=world_time,
        source=source,
        content=content,
        tags=tags or [],
        npc_tier=npc_tier,
        max_consequence_severity=severity,
    )


# ---------------------------------------------------------------------------
# AC-37.01: record() returns MemoryRecord
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.01")
@pytest.mark.asyncio
async def test_record_returns_memory_record():
    writer = InMemoryMemoryWriter()
    rec = await _record(writer, content="A player made a choice.")
    assert isinstance(rec, MemoryRecord)
    assert rec.memory_id
    assert rec.universe_id == _UNIVERSE_ID
    assert rec.session_id == str(_SESSION_ID)
    assert rec.content == "A player made a choice."
    assert rec.source == "player"


# ---------------------------------------------------------------------------
# AC-37.02: importance scoring (additive, source + severity combos)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.02")
def test_importance_score_player_source():
    score = _score_importance("player", None, None, [])
    assert score == pytest.approx(0.3)


@pytest.mark.spec("AC-37.02")
def test_importance_score_narrator_zero():
    score = _score_importance("narrator", None, None, [])
    assert score == pytest.approx(0.0)


@pytest.mark.spec("AC-37.02")
def test_importance_score_key_npc_adds():
    score = _score_importance("npc", "KEY", None, [])
    assert score == pytest.approx(0.3)


@pytest.mark.spec("AC-37.02")
def test_importance_score_critical_severity_adds():
    score = _score_importance("player", None, "critical", [])
    assert score == pytest.approx(0.6)


@pytest.mark.spec("AC-37.02")
def test_importance_score_tags_add():
    score = _score_importance("player", None, None, ["quest"])
    assert score == pytest.approx(0.5)


@pytest.mark.spec("AC-37.02")
def test_importance_score_clamped_at_one():
    score = _score_importance("player", "KEY", "critical", ["quest", "death", "combat"])
    assert score == pytest.approx(1.0)


@pytest.mark.spec("AC-37.02")
def test_importance_score_unknown_source_zero():
    score = _score_importance("unknown", None, None, [])
    assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# AC-37.03: three-tier context assembly (working/active/compressed)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.03")
@pytest.mark.asyncio
async def test_get_context_returns_three_tiers():
    writer = InMemoryMemoryWriter()
    # Records on different turns so they fall into different tiers
    for turn in range(1, 10):
        await _record(writer, turn=turn)

    ctx = await writer.get_context(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        current_tick=10,
        budget_tokens=4000,
    )
    assert isinstance(ctx.working, list)
    assert isinstance(ctx.active, list)
    assert isinstance(ctx.compressed, list)


@pytest.mark.spec("AC-37.03")
@pytest.mark.asyncio
async def test_get_context_working_tier_is_most_recent():
    writer = InMemoryMemoryWriter()
    for turn in range(1, 8):
        await _record(writer, turn=turn)

    ctx = await writer.get_context(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        current_tick=10,
        budget_tokens=4000,
        memory_config={"working_memory_size": 5},
    )
    working_turns = {r.turn_number for r in ctx.working}
    # Working tier should cover the 5 most recent unique turns (3–7)
    assert working_turns == {3, 4, 5, 6, 7}


# ---------------------------------------------------------------------------
# AC-37.04: decay formula — current_importance() at various ticks
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.04")
def test_current_importance_no_decay_at_zero_elapsed():
    rec = MemoryRecord(
        memory_id="test",
        universe_id=_UNIVERSE_ID,
        session_id=str(_SESSION_ID),
        turn_number=1,
        world_time_tick=10,
        source="player",
        attributed_to=None,
        content="test",
        summary=None,
        importance_score=0.8,
        tier="active",
        is_compressed=False,
    )
    assert rec.current_importance(current_tick=10, half_life_ticks=50) == pytest.approx(
        0.8
    )


@pytest.mark.spec("AC-37.04")
def test_current_importance_half_after_one_half_life():
    rec = MemoryRecord(
        memory_id="test",
        universe_id=_UNIVERSE_ID,
        session_id=str(_SESSION_ID),
        turn_number=1,
        world_time_tick=0,
        source="player",
        attributed_to=None,
        content="test",
        summary=None,
        importance_score=1.0,
        tier="active",
        is_compressed=False,
    )
    decayed = rec.current_importance(current_tick=50, half_life_ticks=50)
    assert decayed == pytest.approx(0.5, rel=1e-3)


@pytest.mark.spec("AC-37.04")
def test_current_importance_quarter_after_two_half_lives():
    rec = MemoryRecord(
        memory_id="test",
        universe_id=_UNIVERSE_ID,
        session_id=str(_SESSION_ID),
        turn_number=1,
        world_time_tick=0,
        source="player",
        attributed_to=None,
        content="test",
        summary=None,
        importance_score=1.0,
        tier="active",
        is_compressed=False,
    )
    decayed = rec.current_importance(current_tick=100, half_life_ticks=50)
    assert decayed == pytest.approx(0.25, rel=1e-3)


# ---------------------------------------------------------------------------
# AC-37.05: budget cap drops overflow records
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.05")
@pytest.mark.asyncio
async def test_budget_cap_drops_records():
    writer = InMemoryMemoryWriter()
    # Write records on old turns so they end up in active tier
    for turn in range(1, 20):
        long_content = "x" * 100  # ~25 tokens each
        await _record(writer, turn=turn, source="narrator", content=long_content)

    ctx = await writer.get_context(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        current_tick=100,
        budget_tokens=50,  # very tight budget
        memory_config={"working_memory_size": 3},
    )
    # With budget=50 and 3 working records at ~25 tokens each (75 total),
    # all active records overflow → dropped_count > 0
    assert ctx.dropped_count > 0


# ---------------------------------------------------------------------------
# AC-37.06: compression triggers when token count > threshold
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.06")
@pytest.mark.asyncio
async def test_compress_if_needed_skips_below_threshold():
    writer = InMemoryMemoryWriter()
    # Single short record in active tier
    rec = MemoryRecord(
        memory_id="m1",
        universe_id=_UNIVERSE_ID,
        session_id=str(_SESSION_ID),
        turn_number=1,
        world_time_tick=0,
        source="narrator",
        attributed_to=None,
        content="short",
        summary=None,
        importance_score=0.1,
        tier="active",
        is_compressed=False,
    )
    writer._records.append(rec)
    result = await writer.compress_if_needed(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        memory_config={"compression_threshold_tokens": 4000},
    )
    assert result.skipped is True
    assert result.compressed_count == 0


@pytest.mark.spec("AC-37.06")
@pytest.mark.asyncio
async def test_compress_if_needed_triggers_above_threshold():
    writer = InMemoryMemoryWriter()
    # Many low-importance active records that exceed 100 tokens
    for i in range(20):
        rec = MemoryRecord(
            memory_id=f"m{i}",
            universe_id=_UNIVERSE_ID,
            session_id=str(_SESSION_ID),
            turn_number=i,
            world_time_tick=i,
            source="narrator",
            attributed_to=None,
            content="x" * 80,  # ~20 tokens each; 20*20 = 400 > threshold 100
            summary=None,
            importance_score=0.1,  # below compression importance threshold
            tier="active",
            is_compressed=False,
        )
        writer._records.append(rec)

    result = await writer.compress_if_needed(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        memory_config={
            "compression_threshold_tokens": 100,
            "compression_importance_threshold": 0.5,
        },
    )
    assert result.skipped is False
    assert result.compressed_count > 0


# ---------------------------------------------------------------------------
# AC-37.07: archived records not included in context
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.07")
@pytest.mark.asyncio
async def test_archived_records_excluded_from_context():
    writer = InMemoryMemoryWriter()
    archived = MemoryRecord(
        memory_id="archived",
        universe_id=_UNIVERSE_ID,
        session_id=str(_SESSION_ID),
        turn_number=1,
        world_time_tick=1,
        source="player",
        attributed_to=None,
        content="This is archived",
        summary=None,
        importance_score=0.9,
        tier="archived",
        is_compressed=True,
    )
    writer._records.append(archived)

    ctx = await writer.get_context(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        current_tick=10,
        budget_tokens=4000,
    )
    all_ctx_records = ctx.working + ctx.active + ctx.compressed
    assert not any(r.memory_id == "archived" for r in all_ctx_records)


# ---------------------------------------------------------------------------
# AC-37.08: compressed record references original IDs
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-37.08")
@pytest.mark.asyncio
async def test_compressed_record_references_original_ids():
    writer = InMemoryMemoryWriter()
    original_ids = []
    for i in range(5):
        rec = MemoryRecord(
            memory_id=f"orig-{i}",
            universe_id=_UNIVERSE_ID,
            session_id=str(_SESSION_ID),
            turn_number=i,
            world_time_tick=i,
            source="narrator",
            attributed_to=None,
            content="x" * 80,
            summary=None,
            importance_score=0.1,
            tier="active",
            is_compressed=False,
        )
        writer._records.append(rec)
        original_ids.append(f"orig-{i}")

    result = await writer.compress_if_needed(
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        memory_config={
            "compression_threshold_tokens": 10,
            "compression_importance_threshold": 0.5,
        },
    )
    assert result.new_record is not None
    assert result.new_record.is_compressed is True
    # compressed_from should reference all the original record IDs
    for oid in original_ids:
        assert oid in result.new_record.compressed_from
