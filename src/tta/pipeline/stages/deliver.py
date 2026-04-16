"""Deliver stage — finalize turn for delivery.

V1: ensures narrative_output is present and marks the turn complete.
World state updates are applied by the caller/orchestrator.
(plans/llm-and-pipeline.md §6)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from tta.models.turn import TurnState, TurnStatus

if TYPE_CHECKING:
    from tta.pipeline.types import PipelineDeps

log = structlog.get_logger()


async def deliver_stage(state: TurnState, deps: PipelineDeps) -> TurnState:
    """Mark the turn as delivered and complete."""
    if not state.narrative_output:
        log.error(
            "deliver_missing_narrative",
            session_id=str(state.session_id),
            turn_number=state.turn_number,
        )
        return state.model_copy(
            update={"status": TurnStatus.failed, "delivered": False}
        )

    log.info(
        "turn_delivered",
        session_id=str(state.session_id),
        turn_number=state.turn_number,
    )

    return state.model_copy(
        update={
            "status": TurnStatus.complete,
            "delivered": True,
        }
    )
