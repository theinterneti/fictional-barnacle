"""Deliver stage — finalize turn for delivery.

V1: ensures narrative_output is present and marks the turn complete.
V2 (S34): if WorldTimeService is wired and world_time exists in game_state,
advances diegetic time by one tick before completing the turn.
(plans/llm-and-pipeline.md §6)
"""

from __future__ import annotations

import dataclasses

import structlog

from tta.models.turn import TurnState, TurnStatus
from tta.pipeline.types import PipelineDeps
from tta.simulation.world_time import WorldTimeService

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

    # --- v2 S34: advance diegetic time -----------------------------------
    game_state = state.game_state
    if deps.world_time_service is not None and game_state.get("world_time") is not None:
        current_ticks: int = game_state["world_time"].get("total_ticks", 0)
        time_cfg_data: dict = game_state.get("time_config") or {}
        time_cfg = WorldTimeService.config_from_universe(time_cfg_data)
        delta = deps.world_time_service.tick(current_ticks, time_cfg)
        game_state = {**game_state, "world_time": dataclasses.asdict(delta.world_time)}

    return state.model_copy(
        update={
            "status": TurnStatus.complete,
            "delivered": True,
            "game_state": game_state,
        }
    )
