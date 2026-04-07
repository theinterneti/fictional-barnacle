"""Tests for WorldChange validation and application."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.models.world import (
    TemplateConnection,
    TemplateItem,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldChange,
    WorldChangeType,
    WorldSeed,
    WorldTemplate,
)
from tta.world.changes import (
    ChangeValidationError,
    apply_changes,
    validate_change,
)
from tta.world.memory_service import InMemoryWorldService

# ── Fixtures ─────────────────────────────────────────────────────


def _make_seed() -> WorldSeed:
    """Minimal world seed with two connected locations."""
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


async def _setup_world() -> tuple[InMemoryWorldService, uuid4.__class__]:
    """Create a service with a seeded world; return (svc, sid)."""
    svc = InMemoryWorldService()
    sid = uuid4()
    await svc.create_world_graph(sid, _make_seed())
    return svc, sid


# ── PLAYER_MOVED validation ─────────────────────────────────────


class TestPlayerMovedValidation:
    """Validate PLAYER_MOVED changes."""

    async def test_valid_movement(self) -> None:
        svc, sid = await _setup_world()
        loc = await svc.get_player_location(sid)
        adjacent = svc._get_adjacent(str(sid), loc.id)
        target = adjacent[0]

        change = WorldChange(
            type=WorldChangeType.PLAYER_MOVED,
            entity_id="player",
            payload={"from_id": loc.id, "to_id": target.id},
        )

        await validate_change(change, svc, sid)

    async def test_missing_from_id(self) -> None:
        svc, sid = await _setup_world()

        change = WorldChange(
            type=WorldChangeType.PLAYER_MOVED,
            entity_id="player",
            payload={"to_id": "somewhere"},
        )

        with pytest.raises(ChangeValidationError, match="from_id"):
            await validate_change(change, svc, sid)

    async def test_missing_to_id(self) -> None:
        svc, sid = await _setup_world()

        change = WorldChange(
            type=WorldChangeType.PLAYER_MOVED,
            entity_id="player",
            payload={"from_id": "somewhere"},
        )

        with pytest.raises(ChangeValidationError, match="to_id"):
            await validate_change(change, svc, sid)

    async def test_invalid_route(self) -> None:
        svc, sid = await _setup_world()

        change = WorldChange(
            type=WorldChangeType.PLAYER_MOVED,
            entity_id="player",
            payload={"from_id": "bad_a", "to_id": "bad_b"},
        )

        with pytest.raises(ChangeValidationError, match="not valid"):
            await validate_change(change, svc, sid)


# ── ITEM_TAKEN / ITEM_DROPPED validation ────────────────────────


class TestItemValidation:
    """Validate ITEM_TAKEN and ITEM_DROPPED changes."""

    async def test_item_taken_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_TAKEN,
            entity_id="sword",
            payload={"item_id": "sword"},
        )
        await validate_change(change, svc, sid)

    async def test_item_taken_missing_item_id(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_TAKEN,
            entity_id="sword",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="item_id"):
            await validate_change(change, svc, sid)

    async def test_item_dropped_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_DROPPED,
            entity_id="sword",
            payload={"item_id": "sword"},
        )
        await validate_change(change, svc, sid)

    async def test_item_dropped_missing_item_id(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_DROPPED,
            entity_id="sword",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="item_id"):
            await validate_change(change, svc, sid)


# ── NPC validation ───────────────────────────────────────────────


class TestNPCValidation:
    """Validate NPC-related changes."""

    async def test_npc_moved_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.NPC_MOVED,
            entity_id="npc1",
            payload={"destination_id": "market"},
        )
        await validate_change(change, svc, sid)

    async def test_npc_moved_missing_destination(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.NPC_MOVED,
            entity_id="npc1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="destination_id"):
            await validate_change(change, svc, sid)

    async def test_npc_disposition_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.NPC_DISPOSITION_CHANGED,
            entity_id="npc1",
            payload={"new_disposition": "friendly"},
        )
        await validate_change(change, svc, sid)

    async def test_npc_disposition_missing(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.NPC_DISPOSITION_CHANGED,
            entity_id="npc1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="new_disposition"):
            await validate_change(change, svc, sid)

    async def test_npc_state_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.NPC_STATE_CHANGED,
            entity_id="npc1",
            payload={"new_state": "active"},
        )
        await validate_change(change, svc, sid)

    async def test_npc_state_missing(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.NPC_STATE_CHANGED,
            entity_id="npc1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="new_state"):
            await validate_change(change, svc, sid)


# ── LOCATION_STATE_CHANGED validation ────────────────────────────


class TestLocationStateValidation:
    """Validate LOCATION_STATE_CHANGED changes."""

    async def test_valid_with_properties(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.LOCATION_STATE_CHANGED,
            entity_id="loc1",
            payload={"description": "Now it's dark"},
        )
        await validate_change(change, svc, sid)

    async def test_empty_payload_rejected(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.LOCATION_STATE_CHANGED,
            entity_id="loc1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="at least one"):
            await validate_change(change, svc, sid)


# ── CONNECTION validation ────────────────────────────────────────


class TestConnectionValidation:
    """Validate CONNECTION_LOCKED/UNLOCKED changes."""

    async def test_connection_locked_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.CONNECTION_LOCKED,
            entity_id="conn1",
            payload={"from_id": "a", "to_id": "b"},
        )
        await validate_change(change, svc, sid)

    async def test_connection_locked_missing_ids(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.CONNECTION_LOCKED,
            entity_id="conn1",
            payload={"from_id": "a"},
        )
        with pytest.raises(ChangeValidationError, match="to_id"):
            await validate_change(change, svc, sid)

    async def test_connection_unlocked_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.CONNECTION_UNLOCKED,
            entity_id="conn1",
            payload={"from_id": "a", "to_id": "b"},
        )
        await validate_change(change, svc, sid)

    async def test_connection_unlocked_missing_ids(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.CONNECTION_UNLOCKED,
            entity_id="conn1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="from_id"):
            await validate_change(change, svc, sid)


# ── QUEST / ITEM_VISIBILITY validation ───────────────────────────


class TestQuestAndVisibilityValidation:
    """Validate QUEST_STATUS_CHANGED and ITEM_VISIBILITY."""

    async def test_quest_status_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.QUEST_STATUS_CHANGED,
            entity_id="quest1",
            payload={"new_status": "completed"},
        )
        await validate_change(change, svc, sid)

    async def test_quest_status_missing(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.QUEST_STATUS_CHANGED,
            entity_id="quest1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="new_status"):
            await validate_change(change, svc, sid)

    async def test_item_visibility_valid(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_VISIBILITY_CHANGED,
            entity_id="item1",
            payload={"hidden": True},
        )
        await validate_change(change, svc, sid)

    async def test_item_visibility_missing(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_VISIBILITY_CHANGED,
            entity_id="item1",
            payload={},
        )
        with pytest.raises(ChangeValidationError, match="hidden"):
            await validate_change(change, svc, sid)

    async def test_item_visibility_not_bool(self) -> None:
        svc, sid = await _setup_world()
        change = WorldChange(
            type=WorldChangeType.ITEM_VISIBILITY_CHANGED,
            entity_id="item1",
            payload={"hidden": "yes"},
        )
        with pytest.raises(ChangeValidationError, match="bool"):
            await validate_change(change, svc, sid)


# ── apply_changes integration ────────────────────────────────────


class TestApplyChanges:
    """Test batch apply_changes."""

    async def test_apply_valid_changes(self) -> None:
        svc, sid = await _setup_world()
        loc = await svc.get_player_location(sid)
        adjacent = svc._get_adjacent(str(sid), loc.id)
        target = adjacent[0]

        changes = [
            WorldChange(
                type=WorldChangeType.PLAYER_MOVED,
                entity_id="player",
                payload={
                    "from_id": loc.id,
                    "to_id": target.id,
                },
            ),
        ]

        applied = await apply_changes(changes, svc, sid)

        assert len(applied) == 1
        new_loc = await svc.get_player_location(sid)
        assert new_loc.id == target.id

    async def test_apply_stops_on_invalid(self) -> None:
        svc, sid = await _setup_world()

        changes = [
            WorldChange(
                type=WorldChangeType.ITEM_TAKEN,
                entity_id="sword",
                payload={},
            ),
        ]

        with pytest.raises(ChangeValidationError):
            await apply_changes(changes, svc, sid)

    async def test_apply_empty_list(self) -> None:
        svc, sid = await _setup_world()
        applied = await apply_changes([], svc, sid)
        assert applied == []

    async def test_apply_multiple_changes(self) -> None:
        svc, sid = await _setup_world()

        changes = [
            WorldChange(
                type=WorldChangeType.ITEM_TAKEN,
                entity_id="sword",
                payload={"item_id": "sword"},
            ),
            WorldChange(
                type=WorldChangeType.NPC_DISPOSITION_CHANGED,
                entity_id="barkeep",
                payload={"new_disposition": "friendly"},
            ),
        ]

        applied = await apply_changes(changes, svc, sid)
        assert len(applied) == 2
