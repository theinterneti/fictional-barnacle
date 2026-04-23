"""Unit tests for NPC Memory and Social Graph (S38, AC-38.01–38.08)."""

from __future__ import annotations

from uuid import UUID

import pytest
from ulid import ULID

from tta.simulation.npc_memory import InMemorySocialMemoryWriter, _distort_content
from tta.simulation.types import NPCEpisodicMemory, NPCSocialEdge, WorldTime

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
_SESSION_ID_2: UUID = UUID("00000000-0000-0000-0000-000000000002")


async def _episode(
    writer: InMemorySocialMemoryWriter,
    *,
    npc_id: str = "npc-alpha",
    content: str = "Observed player action",
    importance: float = 0.5,
    is_gossip: bool = False,
    gossip_source: str | None = None,
    turn: int = 1,
    session_id: UUID = _SESSION_ID,
) -> NPCEpisodicMemory:
    return await writer.record_episode(
        npc_id=npc_id,
        universe_id=_UNIVERSE_ID,
        session_id=session_id,
        turn_number=turn,
        world_time=_WORLD_TIME,
        content=content,
        importance_score=importance,
        is_gossip=is_gossip,
        gossip_source_npc_id=gossip_source,
    )


def _make_edge(
    src: str,
    tgt: str,
    gossip_weight: float = 0.5,
    universe_id: str = _UNIVERSE_ID,
) -> NPCSocialEdge:
    return NPCSocialEdge(
        edge_id=str(ULID()),
        source_npc_id=src,
        target_id=tgt,
        universe_id=universe_id,
        dimensions=None,
        gossip_weight=gossip_weight,
    )


# ---------------------------------------------------------------------------
# AC-38.01: record_episode() returns NPCEpisodicMemory
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.01")
@pytest.mark.asyncio
async def test_record_episode_returns_npc_episodic_memory():
    writer = InMemorySocialMemoryWriter()
    ep = await _episode(writer, content="The player fought a bandit.")
    assert isinstance(ep, NPCEpisodicMemory)
    assert ep.episode_id
    assert ep.npc_id == "npc-alpha"
    assert ep.universe_id == _UNIVERSE_ID
    assert ep.session_id == str(_SESSION_ID)
    assert ep.content == "The player fought a bandit."
    assert ep.is_gossip is False


# ---------------------------------------------------------------------------
# AC-38.02: gossip propagates max 2 hops
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.02", "AC-38.04")
@pytest.mark.asyncio
async def test_gossip_propagates_max_two_hops():
    writer = InMemorySocialMemoryWriter()
    # Build chain: alpha -> beta -> gamma -> delta (3 potential hops)
    await writer.update_relationship(_make_edge("npc-alpha", "npc-beta", 0.5))
    await writer.update_relationship(_make_edge("npc-beta", "npc-gamma", 0.5))
    await writer.update_relationship(_make_edge("npc-gamma", "npc-delta", 0.5))

    ep = await _episode(writer, npc_id="npc-alpha", content="Secret information")
    events = await writer.propagate_gossip(
        ep, social_config={"max_gossip_hops": 2, "gossip_familiarity_threshold": 30}
    )

    receivers = {e.receiver_npc_id for e in events}
    # beta (hop 1) and gamma (hop 2) should receive; delta (hop 3) must NOT
    assert "npc-beta" in receivers
    assert "npc-gamma" in receivers
    assert "npc-delta" not in receivers
    # No event should have hop_count >= 2 as next-step source
    assert all(e.hop_count <= 2 for e in events)


# ---------------------------------------------------------------------------
# AC-38.03: reliability floor stops propagation
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.03", "AC-38.05")
@pytest.mark.asyncio
async def test_reliability_floor_stops_propagation():
    writer = InMemorySocialMemoryWriter()
    # Chain with enough hops that reliability would drop below 0.2
    # reliability after hop 1 = 0.8 (OK), after hop 2 = 0.6 (OK),
    # after hop 3 = 0.4 (OK), after hop 4 = 0.2 (floor hit → stop)
    # but max_hops=2 also caps it; let's test the floor with hops=10
    for i in range(5):
        await writer.update_relationship(_make_edge(f"npc-{i}", f"npc-{i + 1}", 0.5))

    ep = await _episode(writer, npc_id="npc-0")
    events = await writer.propagate_gossip(
        ep, social_config={"max_gossip_hops": 10, "gossip_familiarity_threshold": 30}
    )

    # All events should have reliability >= 0.2 (floor)
    assert all(e.reliability >= 0.2 for e in events)
    # No receiver should exist at a hop where reliability would go below floor
    # After 3 hops: 1.0 - 0.2*3 = 0.4 (passes floor)
    # After 4 hops: 1.0 - 0.2*4 = 0.2 (floor hit, next hop would be 0.0 < floor → stops)
    receivers = {e.receiver_npc_id for e in events}
    # npc-4 receives at hop 4 (reliability=0.2); next would be 0.0 → npc-5 excluded
    assert "npc-5" not in receivers


# ---------------------------------------------------------------------------
# AC-38.04: idempotency — same originating_episode_id not re-recorded
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.02")
@pytest.mark.asyncio
async def test_gossip_idempotency_same_episode_not_re_recorded():
    writer = InMemorySocialMemoryWriter()
    await writer.update_relationship(_make_edge("npc-alpha", "npc-beta", 0.5))

    ep = await _episode(writer, npc_id="npc-alpha", content="A rumour")

    # Propagate twice
    await writer.propagate_gossip(
        ep, social_config={"max_gossip_hops": 2, "gossip_familiarity_threshold": 30}
    )
    second = await writer.propagate_gossip(
        ep, social_config={"max_gossip_hops": 2, "gossip_familiarity_threshold": 30}
    )

    # Second propagation should produce no new events for the same origin episode
    assert len(second) == 0


# ---------------------------------------------------------------------------
# AC-38.05: get_npc_context() sorted by importance desc
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.01")
@pytest.mark.asyncio
async def test_get_npc_context_sorted_by_importance_desc():
    writer = InMemorySocialMemoryWriter()
    await _episode(writer, npc_id="npc-alpha", importance=0.3, content="low importance")
    await _episode(
        writer, npc_id="npc-alpha", importance=0.9, content="high importance"
    )
    await _episode(writer, npc_id="npc-alpha", importance=0.6, content="mid importance")

    ctx = await writer.get_npc_context(
        npc_id="npc-alpha", universe_id=_UNIVERSE_ID, session_id=_SESSION_ID
    )

    scores = [ep.importance_score for ep in ctx.episodes]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# AC-38.06: get_relationship() returns NPCSocialEdge | None
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.02")
@pytest.mark.asyncio
async def test_get_relationship_returns_edge():
    writer = InMemorySocialMemoryWriter()
    edge = _make_edge("npc-alpha", "npc-beta")
    await writer.update_relationship(edge)

    result = await writer.get_relationship("npc-alpha", "npc-beta", _UNIVERSE_ID)
    assert isinstance(result, NPCSocialEdge)
    assert result.source_npc_id == "npc-alpha"
    assert result.target_id == "npc-beta"


@pytest.mark.spec("AC-38.02")
@pytest.mark.asyncio
async def test_get_relationship_returns_none_when_missing():
    writer = InMemorySocialMemoryWriter()
    result = await writer.get_relationship("npc-x", "npc-y", _UNIVERSE_ID)
    assert result is None


# ---------------------------------------------------------------------------
# AC-38.07: update_relationship() persists edge changes
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.02")
@pytest.mark.asyncio
async def test_update_relationship_persists_changes():
    writer = InMemorySocialMemoryWriter()
    edge = _make_edge("npc-alpha", "npc-beta", gossip_weight=0.3)
    await writer.update_relationship(edge)

    # Mutate and persist the updated edge
    updated_edge = NPCSocialEdge(
        edge_id=edge.edge_id,
        source_npc_id="npc-alpha",
        target_id="npc-beta",
        universe_id=_UNIVERSE_ID,
        dimensions=None,
        gossip_weight=0.9,
    )
    await writer.update_relationship(updated_edge)

    stored = await writer.get_relationship("npc-alpha", "npc-beta", _UNIVERSE_ID)
    assert stored is not None
    assert stored.gossip_weight == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# AC-38.08: BACKGROUND NPC episodes scoped to session (not cross-session)
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.07")
@pytest.mark.asyncio
async def test_background_npc_episodes_scoped_to_session():
    writer = InMemorySocialMemoryWriter()
    # Record episode in session 1
    await _episode(
        writer,
        npc_id="npc-background",
        content="Session 1 event",
        session_id=_SESSION_ID,
    )

    # get_npc_context for session 2 must NOT see session 1 episodes
    ctx = await writer.get_npc_context(
        npc_id="npc-background",
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID_2,
    )
    assert len(ctx.episodes) == 0


# ---------------------------------------------------------------------------
# Additional: _distort_content uses templates (NFR-38.04)
# ---------------------------------------------------------------------------


def test_distort_content_uses_template():
    result = _distort_content("the bridge collapsed", hop_count=0)
    assert "the bridge collapsed" in result
    assert result != "the bridge collapsed"  # wrapped in template


def test_distort_content_cycles_templates():
    results = {_distort_content("x", hop_count=i) for i in range(4)}
    # Different hops should produce different template wrappings
    assert len(results) > 1


# ---------------------------------------------------------------------------
# AC-38.06: KEY-tier NPC episodes visible across sessions
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.06")
@pytest.mark.asyncio
async def test_key_npc_episodes_persist_cross_session():
    writer = InMemorySocialMemoryWriter()
    # Record episode in session 1
    await _episode(
        writer,
        npc_id="npc-key",
        content="Survived the great fire",
        importance=0.9,
        session_id=_SESSION_ID,
    )

    # KEY-tier context request for session 2 must still see the episode
    ctx = await writer.get_npc_context(
        npc_id="npc-key",
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID_2,
        npc_tier="KEY",
    )
    assert len(ctx.episodes) == 1
    assert ctx.episodes[0].content == "Survived the great fire"


# ---------------------------------------------------------------------------
# AC-38.08: consequence_id and emotional_valence preserved
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-38.08")
@pytest.mark.asyncio
async def test_consequence_triggers_episode_with_emotional_valence():
    writer = InMemorySocialMemoryWriter()
    ep = await writer.record_episode(
        npc_id="npc-alpha",
        universe_id=_UNIVERSE_ID,
        session_id=_SESSION_ID,
        turn_number=5,
        world_time=_WORLD_TIME,
        content="Witnessed heroic act",
        importance_score=0.85,
        is_gossip=False,
        gossip_source_npc_id=None,
        consequence_id="consequence-001",
        emotional_valence=0.8,
    )
    assert ep.consequence_id == "consequence-001"
    assert ep.emotional_valence == pytest.approx(0.8)
