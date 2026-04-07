"""Tests for InMemoryWorldService."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.models.world import (
    Location,
    LocationContext,
    TemplateConnection,
    TemplateItem,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldSeed,
    WorldTemplate,
)
from tta.world.memory_service import (
    InMemoryWorldService,
)
from tta.world.service import WorldService

# ── Fixtures ─────────────────────────────────────────────────────


def _make_seed() -> WorldSeed:
    """Return a minimal WorldSeed for testing."""
    meta = TemplateMetadata(
        template_key="test",
        display_name="Test World",
    )
    return WorldSeed(
        template=WorldTemplate(
            metadata=meta,
            regions=[
                TemplateRegion(
                    key="town",
                    archetype="A small town",
                ),
            ],
            locations=[
                TemplateLocation(
                    key="tavern",
                    region_key="town",
                    type="interior",
                    archetype="A dimly lit tavern",
                    is_starting_location=True,
                ),
                TemplateLocation(
                    key="market",
                    region_key="town",
                    type="exterior",
                    archetype="A bustling market",
                ),
            ],
            connections=[
                TemplateConnection(
                    from_key="tavern",
                    to_key="market",
                    direction="e",
                    bidirectional=True,
                ),
            ],
            npcs=[
                TemplateNPC(
                    key="barkeep",
                    location_key="tavern",
                    role="merchant",
                    archetype="A gruff barkeep",
                ),
            ],
            items=[
                TemplateItem(
                    key="rusty_sword",
                    location_key="tavern",
                    type="weapon",
                    archetype="A rusty sword",
                ),
            ],
        ),
    )


# ── Protocol conformance ────────────────────────────────────────


class TestProtocolConformance:
    """InMemoryWorldService satisfies WorldService."""

    def test_isinstance_check(self) -> None:
        svc = InMemoryWorldService()
        assert isinstance(svc, WorldService)


# ── create_world_graph ───────────────────────────────────────────


class TestCreateWorldGraph:
    """Tests for world graph creation."""

    async def test_creates_locations(self) -> None:
        # Arrange
        svc = InMemoryWorldService()
        sid = uuid4()

        # Act
        await svc.create_world_graph(sid, _make_seed())

        # Assert
        loc = await svc.get_player_location(sid)
        assert loc.name == "tavern"
        assert loc.type == "interior"

    async def test_creates_connections(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        assert len(ctx.adjacent_locations) == 1
        assert ctx.adjacent_locations[0].name == "market"

    async def test_creates_npcs(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        assert len(ctx.npcs_present) == 1
        assert ctx.npcs_present[0].name == "barkeep"

    async def test_creates_items(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        assert len(ctx.items_here) == 1
        assert ctx.items_here[0].name == "rusty_sword"

    async def test_bidirectional_connections(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        # Get market location (the non-starting one).
        state = await svc.get_world_state(sid)
        market = state.nearby_locations[0]
        ctx = await svc.get_location_context(sid, market.id)
        # Market should connect back to tavern.
        assert len(ctx.adjacent_locations) == 1
        assert ctx.adjacent_locations[0].name == "tavern"


# ── get_location_context ─────────────────────────────────────────


class TestGetLocationContext:
    """Tests for get_location_context."""

    async def test_raises_on_unknown_location(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        with pytest.raises(ValueError, match="not found"):
            await svc.get_location_context(uuid4(), "nope")

    async def test_returns_context(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        assert isinstance(ctx, LocationContext)
        assert ctx.location.id == loc.id


# ── get_player_location ─────────────────────────────────────────


class TestGetPlayerLocation:
    """Tests for get_player_location."""

    async def test_raises_when_no_session(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        with pytest.raises(ValueError, match="No player location"):
            await svc.get_player_location(uuid4())

    async def test_returns_starting_location(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        assert isinstance(loc, Location)
        assert loc.name == "tavern"


# ── get_recent_events ────────────────────────────────────────────


class TestGetRecentEvents:
    """Tests for get_recent_events."""

    async def test_returns_empty_by_default(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        events = await svc.get_recent_events(sid)
        assert events == []


# ── validate_movement ────────────────────────────────────────────


class TestValidateMovement:
    """Tests for validate_movement."""

    async def test_valid_connection(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        target = ctx.adjacent_locations[0]

        ok = await svc.validate_movement(sid, loc.id, target.id)
        assert ok is True

    async def test_no_connection(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ok = await svc.validate_movement(sid, "fake-1", "fake-2")
        assert ok is False

    async def test_locked_connection(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        seed = _make_seed()
        seed.template.connections[0].is_locked = True
        await svc.create_world_graph(sid, seed)

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        target = ctx.adjacent_locations[0]

        ok = await svc.validate_movement(sid, loc.id, target.id)
        assert ok is False


# ── get_world_state ──────────────────────────────────────────────


class TestGetWorldState:
    """Tests for get_world_state."""

    async def test_returns_context(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ctx = await svc.get_world_state(sid)
        assert isinstance(ctx, WorldContext)
        assert ctx.current_location.name == "tavern"
        assert len(ctx.nearby_locations) == 1
        assert len(ctx.npcs_present) == 1
        assert len(ctx.items_here) == 1

    async def test_raises_when_no_session(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        with pytest.raises(ValueError, match="No world state"):
            await svc.get_world_state(uuid4())


# ── apply_world_changes ─────────────────────────────────────────


class TestApplyWorldChanges:
    """Tests for world change application."""

    async def test_player_moved(self) -> None:
        # Arrange
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        start = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, start.id)
        target = ctx.adjacent_locations[0]

        # Act
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.PLAYER_MOVED,
                    entity_id=target.id,
                    payload={"to_id": target.id},
                )
            ],
        )

        # Assert
        new_loc = await svc.get_player_location(sid)
        assert new_loc.id == target.id
        assert new_loc.visited is True

    async def test_item_taken(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        item = ctx.items_here[0]

        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.ITEM_TAKEN,
                    entity_id=item.id,
                )
            ],
        )

        # Item should no longer be at the location.
        ctx2 = await svc.get_location_context(sid, loc.id)
        assert len(ctx2.items_here) == 0

    async def test_item_dropped(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        item = ctx.items_here[0]

        # Take then drop.
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.ITEM_TAKEN,
                    entity_id=item.id,
                )
            ],
        )
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.ITEM_DROPPED,
                    entity_id=item.id,
                )
            ],
        )

        ctx2 = await svc.get_location_context(sid, loc.id)
        assert len(ctx2.items_here) == 1

    async def test_npc_disposition_changed(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        npc = ctx.npcs_present[0]

        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.NPC_DISPOSITION_CHANGED,
                    entity_id=npc.id,
                    payload={"disposition": "hostile"},
                )
            ],
        )

        ctx2 = await svc.get_location_context(sid, loc.id)
        assert ctx2.npcs_present[0].disposition == "hostile"

    async def test_location_state_changed(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.LOCATION_STATE_CHANGED,
                    entity_id=loc.id,
                    payload={"light_level": "dark"},
                )
            ],
        )

        updated = await svc.get_player_location(sid)
        assert updated.light_level == "dark"

    async def test_connection_lock_unlock(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        target = ctx.adjacent_locations[0]

        # Lock
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.CONNECTION_LOCKED,
                    entity_id=loc.id,
                    payload={"to_id": target.id},
                )
            ],
        )
        ok = await svc.validate_movement(sid, loc.id, target.id)
        assert ok is False

        # Unlock
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.CONNECTION_UNLOCKED,
                    entity_id=loc.id,
                    payload={"to_id": target.id},
                )
            ],
        )
        ok = await svc.validate_movement(sid, loc.id, target.id)
        assert ok is True

    async def test_item_visibility_changed(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        item = ctx.items_here[0]

        # Hide
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.ITEM_VISIBILITY_CHANGED,
                    entity_id=item.id,
                    payload={"hidden": True},
                )
            ],
        )
        ctx2 = await svc.get_location_context(sid, loc.id)
        assert len(ctx2.items_here) == 0

    async def test_npc_state_changed(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        npc = ctx.npcs_present[0]

        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.NPC_STATE_CHANGED,
                    entity_id=npc.id,
                    payload={"state": "sleeping"},
                )
            ],
        )
        ctx2 = await svc.get_location_context(sid, loc.id)
        assert ctx2.npcs_present[0].state == "sleeping"

    async def test_npc_moved(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_location_context(sid, loc.id)
        npc = ctx.npcs_present[0]
        target = ctx.adjacent_locations[0]

        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.NPC_MOVED,
                    entity_id=npc.id,
                    payload={"to_location_id": target.id},
                )
            ],
        )

        # NPC gone from tavern.
        ctx2 = await svc.get_location_context(sid, loc.id)
        assert len(ctx2.npcs_present) == 0

        # NPC at market.
        ctx3 = await svc.get_location_context(sid, target.id)
        assert len(ctx3.npcs_present) == 1


# ── cleanup_session ──────────────────────────────────────────────


class TestCleanupSession:
    """Tests for cleanup_session."""

    async def test_removes_all_data(self) -> None:
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        await svc.cleanup_session(sid)

        with pytest.raises(ValueError):
            await svc.get_player_location(sid)

    async def test_cleanup_nonexistent_is_safe(
        self,
    ) -> None:
        svc = InMemoryWorldService()
        # Should not raise.
        await svc.cleanup_session(uuid4())
