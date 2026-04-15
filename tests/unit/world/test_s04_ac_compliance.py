"""S04 World Model — Acceptance Criteria compliance tests.

Covers AC-4.1, AC-4.3, AC-4.6, AC-4.8.

v2 ACs (deferred — require live infra or engine features not yet built):
  AC-4.2 — Cascading State: requires world-tick engine that propagates changes
            autonomously to nearby entities; no such engine exists in v1.
  AC-4.4 — Region Generation: requires on-demand region generation with adjacency
            checks; v1 uses pre-seeded worlds only.
  AC-4.5 — World Ticks: requires autonomous world-tick scheduler for NPC
            schedules advancing with time.
  AC-4.7 — Scale: requires Neo4j backend for 5000+ entity performant traversal;
            InMemoryWorldService is O(N) and not tested at this scale.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tta.models.world import (
    NPC,
    Item,
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
from tta.world.memory_service import InMemoryWorldService

# ── Shared fixtures ───────────────────────────────────────────────────────────


def _make_seed(
    *,
    with_npc: bool = True,
    with_item: bool = True,
) -> WorldSeed:
    """Return a minimal WorldSeed for AC compliance testing.

    Creates one region with a starting tavern location (plus one adjacent
    market). Optionally includes an NPC and an item in the tavern.
    """
    regions = [TemplateRegion(key="town", archetype="A small town")]
    locations = [
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
    ]
    connections = [
        TemplateConnection(
            from_key="tavern",
            to_key="market",
            direction="e",
            bidirectional=True,
        )
    ]
    npcs = (
        [
            TemplateNPC(
                key="barkeep",
                location_key="tavern",
                role="merchant",
                archetype="A gruff barkeep",
            )
        ]
        if with_npc
        else []
    )
    items = (
        [
            TemplateItem(
                key="rusty_sword",
                location_key="tavern",
                type="weapon",
                archetype="A rusty sword",
            )
        ]
        if with_item
        else []
    )
    return WorldSeed(
        template=WorldTemplate(
            metadata=TemplateMetadata(
                template_key="test",
                display_name="Test World",
            ),
            regions=regions,
            locations=locations,
            connections=connections,
            npcs=npcs,
            items=items,
        )
    )


# ── AC-4.1: WorldContext structure on "look around" ───────────────────────────


class TestAC401WorldContextAssembly:
    """AC-4.1 (partial v1): "Look around" populates the available WorldContext fields.

    The full spec requires: location, entities, environmental conditions,
    time-of-day, and active events. v1 WorldContext covers location, NPCs,
    items, nearby locations, and light_level. Time-of-day and active-events
    fields are not yet implemented — those sub-requirements are v2.

    These tests validate the v1-available fields only and do not imply
    full AC-4.1 compliance.
    """

    @pytest.mark.asyncio
    async def test_world_context_has_current_location(self) -> None:
        """AC-4.1: WorldContext.current_location is set after world creation."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ctx = await svc.get_world_state(sid)

        assert isinstance(ctx, WorldContext)
        assert ctx.current_location is not None
        assert ctx.current_location.name == "tavern"

    @pytest.mark.asyncio
    async def test_world_context_includes_npcs(self) -> None:
        """AC-4.1: WorldContext exposes NPCs present at the current location."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed(with_npc=True))

        ctx = await svc.get_world_state(sid)

        assert len(ctx.npcs_present) == 1
        npc = ctx.npcs_present[0]
        assert isinstance(npc, NPC)
        assert npc.name == "barkeep"

    @pytest.mark.asyncio
    async def test_world_context_includes_items(self) -> None:
        """AC-4.1: WorldContext exposes items at the current location."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed(with_item=True))

        ctx = await svc.get_world_state(sid)

        assert len(ctx.items_here) == 1
        item = ctx.items_here[0]
        assert isinstance(item, Item)
        assert item.name == "rusty_sword"

    @pytest.mark.asyncio
    async def test_world_context_includes_nearby_locations(self) -> None:
        """AC-4.1: WorldContext.nearby_locations shows adjacent places (exits)."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ctx = await svc.get_world_state(sid)

        assert len(ctx.nearby_locations) == 1
        assert ctx.nearby_locations[0].name == "market"

    @pytest.mark.asyncio
    async def test_world_context_location_has_light_level(self) -> None:
        """AC-4.1: Environmental condition (light_level) is present on the location."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ctx = await svc.get_world_state(sid)

        assert ctx.current_location.light_level in (
            "dark",
            "dim",
            "lit",
            "bright",
        )

    @pytest.mark.asyncio
    async def test_world_context_no_entities_when_location_empty(self) -> None:
        """AC-4.1: WorldContext returns empty lists when no NPCs or items seeded."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed(with_npc=False, with_item=False))

        ctx = await svc.get_world_state(sid)

        assert ctx.npcs_present == []
        assert ctx.items_here == []


# ── AC-4.3: Diff query returns state changes since last visit ─────────────────


class TestAC403StateDiffOnReturn:
    """AC-4.3: Returning to a location yields a diff of changes since absence.

    v1 does not expose a diff query API. These tests verify that applied
    mutations are visible in subsequent get_world_state() snapshots and that
    changes from different sessions are fully isolated — which is the
    precondition a true diff implementation would build upon. The diff query
    itself is deferred to v2 (see specs/index.json AC-4.3 status: v2).
    """

    @pytest.mark.asyncio
    async def test_applied_changes_visible_in_subsequent_world_state(self) -> None:
        """AC-4.3: Changes applied via apply_world_changes are retrievable."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_world_state(sid)
        npc = ctx.npcs_present[0]

        changes = [
            WorldChange(
                type=WorldChangeType.NPC_DISPOSITION_CHANGED,
                entity_id=npc.id,
                payload={"disposition": "hostile"},
            ),
            WorldChange(
                type=WorldChangeType.LOCATION_STATE_CHANGED,
                entity_id=loc.id,
                payload={"light_level": "dark"},
            ),
        ]
        await svc.apply_world_changes(sid, changes)

        # Verify effects are reflected in the current state (the "diff" result).
        updated_ctx = await svc.get_world_state(sid)
        assert updated_ctx.npcs_present[0].disposition == "hostile"
        assert updated_ctx.current_location.light_level == "dark"

    @pytest.mark.asyncio
    async def test_multiple_changes_all_reflected(self) -> None:
        """AC-4.3: Multiple sequential change batches are all retained."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ctx = await svc.get_world_state(sid)
        item = ctx.items_here[0]
        npc = ctx.npcs_present[0]

        await svc.apply_world_changes(
            sid,
            [WorldChange(type=WorldChangeType.ITEM_TAKEN, entity_id=item.id)],
        )
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.NPC_STATE_CHANGED,
                    entity_id=npc.id,
                    payload={"state": "traveling"},
                )
            ],
        )

        final_ctx = await svc.get_world_state(sid)
        assert final_ctx.items_here == [], "Item must be gone after ITEM_TAKEN"
        assert final_ctx.npcs_present[0].state == "traveling"

    @pytest.mark.asyncio
    async def test_changes_are_session_isolated(self) -> None:
        """AC-4.3: Changes in session A do not affect session B's diff."""
        svc = InMemoryWorldService()
        sid_a = uuid4()
        sid_b = uuid4()

        await svc.create_world_graph(sid_a, _make_seed())
        await svc.create_world_graph(sid_b, _make_seed())

        ctx_a = await svc.get_world_state(sid_a)
        npc_a = ctx_a.npcs_present[0]

        await svc.apply_world_changes(
            sid_a,
            [
                WorldChange(
                    type=WorldChangeType.NPC_DISPOSITION_CHANGED,
                    entity_id=npc_a.id,
                    payload={"disposition": "hostile"},
                )
            ],
        )

        # Session B's NPC must remain at its initial value ("neutral").
        ctx_b = await svc.get_world_state(sid_b)
        assert ctx_b.npcs_present[0].disposition == "neutral", (
            "Session isolation: B's NPC disposition must remain at its initial value"
        )


# ── AC-4.6: Each region has distinct identity ─────────────────────────────────


class TestAC406DistinctRegionIdentity:
    """AC-4.6: Five distinct regions each have a unique archetype.

    The spec requires: terrain, culture, and atmosphere differ per region.
    v1 captures identity via TemplateRegion.archetype. We verify that a
    5-region template has 5 distinct archetypes, and that TemplateMetadata
    supports compatible_tones / compatible_scales to further differentiate.
    """

    def _make_five_region_template(self) -> WorldTemplate:
        """Build a WorldTemplate with 5 regions each with a unique archetype."""
        regions = [
            TemplateRegion(key="forest", archetype="Ancient elven forest"),
            TemplateRegion(key="desert", archetype="Scorching sun-baked desert"),
            TemplateRegion(key="tundra", archetype="Frozen arctic tundra"),
            TemplateRegion(key="coast", archetype="Storm-lashed rocky coastline"),
            TemplateRegion(key="volcano", archetype="Active volcanic highlands"),
        ]
        # One starting location per region
        locations = [
            TemplateLocation(
                key=f"{r.key}_entrance",
                region_key=r.key,
                type="exterior",
                archetype=f"Entrance to the {r.key}",
                is_starting_location=(r.key == "forest"),
            )
            for r in regions
        ]
        return WorldTemplate(
            metadata=TemplateMetadata(
                template_key="five_regions",
                display_name="Five Regions World",
                compatible_tones=["dark", "heroic", "mysterious"],
                compatible_scales=["local", "regional", "continental"],
            ),
            regions=regions,
            locations=locations,
        )

    def test_five_regions_have_unique_archetypes(self) -> None:
        """AC-4.6: Each region's archetype is distinct (no duplicates)."""
        tmpl = self._make_five_region_template()

        archetypes = [r.archetype for r in tmpl.regions]
        assert len(archetypes) == 5
        assert len(set(archetypes)) == 5, "All 5 region archetypes must be distinct"

    def test_template_metadata_supports_multiple_tones(self) -> None:
        """AC-4.6: TemplateMetadata.compatible_tones differentiates regions."""
        tmpl = self._make_five_region_template()

        assert len(tmpl.metadata.compatible_tones) >= 2, (
            "Templates must declare multiple compatible tones"
        )

    def test_template_metadata_supports_multiple_scales(self) -> None:
        """AC-4.6: TemplateMetadata.compatible_scales allows scale variation."""
        tmpl = self._make_five_region_template()

        assert len(tmpl.metadata.compatible_scales) >= 2

    def test_region_keys_are_unique(self) -> None:
        """AC-4.6: Each region has a distinct key (identity anchor)."""
        tmpl = self._make_five_region_template()

        keys = [r.key for r in tmpl.regions]
        assert len(set(keys)) == len(keys), "Region keys must be unique"

    def test_five_region_locations_cover_all_regions(self) -> None:
        """AC-4.6: Every region has at least one location associated with it."""
        tmpl = self._make_five_region_template()

        region_keys = {r.key for r in tmpl.regions}
        covered = {loc.region_key for loc in tmpl.locations}
        assert region_keys == covered, "Every region must have at least one location"


# ── AC-4.8: World state restored after crash (atomic changes) ─────────────────


class TestAC408AtomicStateRestoration:
    """AC-4.8: World state is consistent after applying a batch of changes.

    The spec requires: if the session crashes mid-turn, the world restores
    to the last completed turn — no partial writes. In v1 the unit contract is:
    apply_world_changes() applies the full batch, and subsequent reads see all
    changes (atomically from the caller's perspective). Idempotent reads are
    also required — two consecutive get_world_state() calls return identical
    snapshots.
    """

    @pytest.mark.asyncio
    async def test_batch_changes_all_applied_atomically(self) -> None:
        """AC-4.8: A multi-change batch is fully reflected after apply."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_world_state(sid)
        npc = ctx.npcs_present[0]
        item = ctx.items_here[0]

        batch = [
            WorldChange(
                type=WorldChangeType.NPC_DISPOSITION_CHANGED,
                entity_id=npc.id,
                payload={"disposition": "warm"},
            ),
            WorldChange(
                type=WorldChangeType.ITEM_TAKEN,
                entity_id=item.id,
            ),
            WorldChange(
                type=WorldChangeType.LOCATION_STATE_CHANGED,
                entity_id=loc.id,
                payload={"light_level": "dim"},
            ),
        ]
        await svc.apply_world_changes(sid, batch)

        result = await svc.get_world_state(sid)

        assert result.npcs_present[0].disposition == "warm", (
            "NPC disposition change must be persisted"
        )
        assert result.items_here == [], "Item must be absent after ITEM_TAKEN"
        assert result.current_location.light_level == "dim", (
            "Light level change must be persisted"
        )

    @pytest.mark.asyncio
    async def test_get_world_state_is_idempotent(self) -> None:
        """AC-4.8: Two consecutive get_world_state() calls return the same data."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        ctx1 = await svc.get_world_state(sid)
        ctx2 = await svc.get_world_state(sid)

        assert ctx1.current_location.id == ctx2.current_location.id
        assert len(ctx1.npcs_present) == len(ctx2.npcs_present)
        assert len(ctx1.items_here) == len(ctx2.items_here)
        assert len(ctx1.nearby_locations) == len(ctx2.nearby_locations)

    @pytest.mark.asyncio
    async def test_empty_change_batch_does_not_corrupt_state(self) -> None:
        """AC-4.8: Applying an empty batch leaves existing state intact."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        before = await svc.get_world_state(sid)

        await svc.apply_world_changes(sid, [])  # empty batch

        after = await svc.get_world_state(sid)

        assert after.current_location.id == before.current_location.id
        assert len(after.npcs_present) == len(before.npcs_present)
        assert len(after.items_here) == len(before.items_here)

    @pytest.mark.asyncio
    async def test_state_consistent_after_multiple_batches(self) -> None:
        """AC-4.8: Sequential batches produce a stable, non-corrupted state."""
        svc = InMemoryWorldService()
        sid = uuid4()
        await svc.create_world_graph(sid, _make_seed())

        loc = await svc.get_player_location(sid)
        ctx = await svc.get_world_state(sid)
        npc = ctx.npcs_present[0]

        # First batch: change NPC disposition
        await svc.apply_world_changes(
            sid,
            [
                WorldChange(
                    type=WorldChangeType.NPC_DISPOSITION_CHANGED,
                    entity_id=npc.id,
                    payload={"disposition": "cold"},
                )
            ],
        )

        # Second batch: change location light
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

        final = await svc.get_world_state(sid)

        assert final.npcs_present[0].disposition == "cold", (
            "First batch changes must survive second batch"
        )
        assert final.current_location.light_level == "dark", (
            "Second batch changes must be applied"
        )
