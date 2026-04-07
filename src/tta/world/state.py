"""World state management utilities.

Helpers for assembling full world context and compact summaries
from the WorldService, used by the context pipeline stage and
save/resume logic.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from tta.world.service import WorldService

log = structlog.get_logger()


async def get_full_context(
    world_service: WorldService,
    session_id: UUID,
    depth: int = 1,
) -> dict:
    """Get full world context as a dict for prompt assembly."""
    player_loc = await world_service.get_player_location(session_id)
    loc_context = await world_service.get_location_context(
        session_id, player_loc.id, depth=depth
    )
    events = await world_service.get_recent_events(session_id)

    log.debug(
        "full_context_assembled",
        location=player_loc.id,
        adjacent=len(loc_context.adjacent_locations),
        npcs=len(loc_context.npcs_present),
        items=len(loc_context.items_here),
        events=len(events),
    )

    return {
        "location": loc_context.location.model_dump(),
        "adjacent_locations": [
            loc.model_dump() for loc in loc_context.adjacent_locations
        ],
        "npcs_present": [n.model_dump() for n in loc_context.npcs_present],
        "items_here": [i.model_dump() for i in loc_context.items_here],
        "recent_events": [e.model_dump() for e in events],
    }


async def summarize_world_state(
    world_service: WorldService,
    session_id: UUID,
) -> dict:
    """Compact summary of world state for save/resume."""
    ctx = await world_service.get_world_state(session_id)

    log.debug(
        "world_state_summarized",
        location=ctx.current_location.id,
    )

    return {
        "current_location": ctx.current_location.model_dump(),
        "nearby_count": len(ctx.nearby_locations),
        "npcs_count": len(ctx.npcs_present),
        "items_count": len(ctx.items_here),
        "events_count": len(ctx.recent_events),
    }
