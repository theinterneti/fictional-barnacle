"""Context stage — assemble world context for generation.

Queries WorldService for live world data when available,
with graceful fallback to a basic context dict from game_state.
(plans/llm-and-pipeline.md §4)
"""

from __future__ import annotations

import structlog

from tta.models.turn import TurnState
from tta.pipeline.types import PipelineDeps
from tta.world.state import get_full_context

log = structlog.get_logger()


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
        # Fallback to V1 stub behavior
        log.warning(
            "context_fallback",
            reason="world_service_unavailable",
            error=str(exc),
            exc_info=True,
        )
        world_context = {
            "game_state": state.game_state,
            "intent": intent,
            "turn_number": state.turn_number,
            "session_id": str(state.session_id),
        }
        context_partial = True

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
