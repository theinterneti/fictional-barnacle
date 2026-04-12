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

    # Inject tone/genre from world seed (S03 FR-6.1)
    world_context = _inject_tone(world_context, state)

    # Inject existing session summary (S03 FR-3.2)
    world_context = _inject_summary(world_context, state)

    # Enrich with NPC dialogue contexts (S06 FR-6)
    world_context = await _enrich_npc_dialogue(world_context, state, deps)

    # Enrich with active consequence data (S05 FR-3)
    world_context = await _enrich_consequences(world_context, state, deps)

    # Populate TurnState.active_consequences from chain data
    active_consequence_chains = None
    consequence_svc = getattr(deps, "consequence_service", None)
    if consequence_svc is not None:
        try:
            chains = await consequence_svc.get_active_chains(state.session_id)
            if chains:
                active_consequence_chains = chains
        except Exception:
            pass  # Already logged in _enrich_consequences

    log.debug(
        "context_assembled",
        intent=intent,
        turn_number=state.turn_number,
        partial=context_partial,
    )

    update: dict = {
        "world_context": world_context,
        "context_partial": context_partial,
    }
    if active_consequence_chains is not None:
        update["active_consequences"] = active_consequence_chains

    return state.model_copy(update=update)


def _inject_tone(world_context: dict, state: TurnState) -> dict:
    """Add tone from world seed to context (S03 FR-6.1)."""
    world_seed = state.game_state.get("world_seed")
    if isinstance(world_seed, dict):
        tone = world_seed.get("tone")
        if tone:
            world_context["tone"] = tone
        genre = world_seed.get("genre")
        if genre:
            world_context["genre"] = genre
    return world_context


def _inject_summary(world_context: dict, state: TurnState) -> dict:
    """Add existing session summary to context (S03 FR-3.2).

    Reuses the summary already persisted by ContextSummaryService
    via the game routes — no new persistence path.
    """
    summary = state.game_state.get("summary")
    if summary:
        world_context["session_summary"] = summary
    return world_context


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


async def _enrich_consequences(
    world_context: dict,
    state: TurnState,
    deps: PipelineDeps,
) -> dict:
    """Add active consequences and foreshadowing hints to context (S05 FR-3).

    Read-only: queries existing chain state without mutating it.
    Evaluation (state transitions) happens in the understand stage.
    """
    consequence_svc = getattr(deps, "consequence_service", None)
    if consequence_svc is None:
        return world_context

    try:
        chains = await consequence_svc.get_active_chains(state.session_id)
        if not chains:
            return world_context

        # Summaries for the generation prompt
        chain_summaries = [
            {
                "id": str(c.id),
                "trigger_description": c.root_trigger,
                "entries_count": len(c.entries),
                "is_resolved": c.is_resolved,
            }
            for c in chains
            if not c.is_resolved
        ]
        world_context["active_consequences"] = chain_summaries

        # Foreshadowing hints from hidden/foreshadowed entries
        hints = await consequence_svc.get_foreshadowing_hints(state.session_id)
        if hints:
            world_context["foreshadowing_hints"] = hints

    except Exception:
        log.warning(
            "consequence_enrichment_failed",
            session_id=str(state.session_id),
            exc_info=True,
        )

    return world_context
