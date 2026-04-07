"""Context stage — assemble world context for generation.

V1 stub: builds basic context dict from game_state.
Full implementation will query WorldService + narrative history.
(plans/llm-and-pipeline.md §4)
"""

from __future__ import annotations

import structlog

from tta.models.turn import TurnState
from tta.pipeline.types import PipelineDeps

log = structlog.get_logger()


async def context_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Assemble world context for the generation prompt.

    V1 stub — real implementation will query WorldService and
    narrative history.  Sets context_partial=True because this
    stub does not fetch live world data.
    """
    intent = state.parsed_intent.intent if state.parsed_intent else "unknown"

    context: dict = {
        "game_state": state.game_state,
        "intent": intent,
        "turn_number": state.turn_number,
        "session_id": str(state.session_id),
    }

    log.debug(
        "context_assembled",
        intent=intent,
        turn_number=state.turn_number,
    )

    return state.model_copy(
        update={
            "world_context": context,
            "context_partial": True,
        }
    )
