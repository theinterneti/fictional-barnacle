"""Tests for world state management utilities."""

from __future__ import annotations

from uuid import UUID, uuid4

from tta.models.world import (
    TemplateConnection,
    TemplateItem,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldSeed,
    WorldTemplate,
)
from tta.world.memory_service import InMemoryWorldService
from tta.world.state import get_full_context, summarize_world_state

# ── Fixtures ─────────────────────────────────────────────────────


def _make_seed() -> WorldSeed:
    """Minimal world seed with two locations and an NPC/item."""
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


async def _setup_world() -> tuple[InMemoryWorldService, UUID]:
    """Create a service with a seeded world."""
    svc = InMemoryWorldService()
    sid = uuid4()
    await svc.create_world_graph(sid, _make_seed())
    return svc, sid


# ── get_full_context ─────────────────────────────────────────────


class TestGetFullContext:
    """Tests for get_full_context."""

    async def test_returns_location_dict(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid)

        assert "location" in ctx
        assert isinstance(ctx["location"], dict)
        assert ctx["location"]["name"] == "tavern"

    async def test_returns_adjacent_locations(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid)

        assert "adjacent_locations" in ctx
        assert isinstance(ctx["adjacent_locations"], list)
        assert len(ctx["adjacent_locations"]) == 1
        assert ctx["adjacent_locations"][0]["name"] == "market"

    async def test_returns_npcs_present(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid)

        assert "npcs_present" in ctx
        assert len(ctx["npcs_present"]) == 1
        assert ctx["npcs_present"][0]["name"] == "barkeep"

    async def test_returns_items_here(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid)

        assert "items_here" in ctx
        assert len(ctx["items_here"]) == 1
        assert ctx["items_here"][0]["name"] == "rusty_sword"

    async def test_returns_recent_events(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid)

        assert "recent_events" in ctx
        assert isinstance(ctx["recent_events"], list)

    async def test_all_values_are_dicts_or_lists(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid)

        assert isinstance(ctx["location"], dict)
        assert isinstance(ctx["adjacent_locations"], list)
        assert isinstance(ctx["npcs_present"], list)
        assert isinstance(ctx["items_here"], list)
        assert isinstance(ctx["recent_events"], list)

    async def test_depth_parameter_accepted(self) -> None:
        svc, sid = await _setup_world()

        ctx = await get_full_context(svc, sid, depth=2)

        assert "location" in ctx


# ── summarize_world_state ────────────────────────────────────────


class TestSummarizeWorldState:
    """Tests for summarize_world_state."""

    async def test_returns_current_location(self) -> None:
        svc, sid = await _setup_world()

        summary = await summarize_world_state(svc, sid)

        assert "current_location" in summary
        assert isinstance(summary["current_location"], dict)
        assert summary["current_location"]["name"] == "tavern"

    async def test_returns_counts(self) -> None:
        svc, sid = await _setup_world()

        summary = await summarize_world_state(svc, sid)

        assert summary["nearby_count"] == 1
        assert summary["npcs_count"] == 1
        assert summary["items_count"] == 1
        assert isinstance(summary["events_count"], int)

    async def test_summary_is_compact(self) -> None:
        """Summary has counts, not full objects for collections."""
        svc, sid = await _setup_world()

        summary = await summarize_world_state(svc, sid)

        expected_keys = {
            "current_location",
            "nearby_count",
            "npcs_count",
            "items_count",
            "events_count",
        }
        assert set(summary.keys()) == expected_keys
