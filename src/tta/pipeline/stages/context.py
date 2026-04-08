"""Context stage — assemble world context for generation.

Queries WorldService for live world data when available,
with graceful fallback to a basic context dict from game_state.
(plans/llm-and-pipeline.md §4)
"""

from __future__ import annotations

import structlog

from tta.models.turn import TurnState
from tta.models.world import NPC
from tta.pipeline.types import PipelineDeps
from tta.world.dialogue import build_dialogue_contexts_for_location
from tta.world.relationship_service import RelationshipService
from tta.world.state import get_full_context

log = structlog.get_logger()

# Player entity id used as source for relationship lookups
_PLAYER_SOURCE_ID = "player"


async def context_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Assemble world context for the generation prompt.

    Attempts to fetch live world data via WorldService.
    Falls back to a basic game_state dict if the service
    is unavailable or raises.
    """
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"

    # Try to get live world context from WorldService
    try:
        world_context = await get_full_context(deps.world, state.session_id)
        world_context["intent"] = intent
        world_context["turn_number"] = state.turn_number
        context_partial = False
    except Exception as exc:
        # Fallback: still try to get recent events from Postgres
        log.warning(
            "context_fallback",
            reason="world_service_unavailable",
            error=str(exc),
            exc_info=True,
        )
        recent_events: list[dict] = []
        try:
            events = await deps.world.get_recent_events(state.session_id, limit=5)
            recent_events = [e.model_dump(mode="json") for e in events]
        except Exception:
            log.warning(
                "context_events_fetch_failed",
                session_id=str(state.session_id),
                exc_info=True,
            )

        world_context = {
            "game_state": state.game_state,
            "intent": intent,
            "turn_number": state.turn_number,
            "session_id": str(state.session_id),
            "recent_events": recent_events,
        }
        context_partial = True

    # Enrich with NPC dialogue contexts (S06 FR-6)
    world_context = await _enrich_npc_dialogue(world_context, state, deps)

    log.debug(
        "context_assembled",
        intent=intent,
        turn_number=state.turn_number,
        partial=context_partial,
    )

    return state.model_copy(
        update={
            "world_context": world_context,
            "context_partial": context_partial,
        }
    )


async def _enrich_npc_dialogue(
    world_context: dict,
    state: TurnState,
    deps: PipelineDeps,
) -> dict:
    """Add npc_dialogue_contexts to world_context if NPCs are present."""
    npcs_raw: list[dict] = world_context.get("npcs_present", [])
    if not npcs_raw:
        return world_context

    # Resolve relationship service from deps if available
    rel_svc: RelationshipService | None = getattr(deps, "relationship_service", None)

    try:
        npcs = [NPC.model_validate(n) for n in npcs_raw]
        dialogue_contexts = await build_dialogue_contexts_for_location(
            npcs=npcs,
            session_id=state.session_id,
            source_id=_PLAYER_SOURCE_ID,
            relationship_service=rel_svc,
        )
        world_context["npc_dialogue_contexts"] = dialogue_contexts
    except Exception:
        log.warning(
            "npc_dialogue_context_failed",
            session_id=str(state.session_id),
            exc_info=True,
        )

    return world_context
