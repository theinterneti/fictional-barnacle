"""Pipeline orchestrator — runs the four stages in sequence.

Enforces per-stage and overall timeouts. On failure in any stage,
returns the TurnState with status=failed.
(plans/llm-and-pipeline.md §7)
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC
from datetime import datetime as dt
from uuid import UUID

import sqlalchemy as sa
import structlog
from opentelemetry import trace

from tta.config import get_settings
from tta.logging import bind_context
from tta.models.game import GameState
from tta.models.turn import TurnState, TurnStatus
from tta.models.world import WorldChangeType
from tta.observability.daily_cost import record_daily_turn
from tta.observability.metrics import (
    TURN_DURATION,
    TURN_STAGE_DURATION,
    TURN_TOTAL,
    TURN_TOTAL_DURATION,
)
from tta.observability.tracing import get_tracer, set_span_error
from tta.pipeline.stages.context import context_stage
from tta.pipeline.stages.deliver import deliver_stage
from tta.pipeline.stages.generate import generate_stage
from tta.pipeline.stages.understand import understand_stage
from tta.pipeline.types import (
    PipelineConfig,
    PipelineDeps,
    Stage,
    StageName,
)
from tta.pipeline.world_changes import (
    parse_relationship_delta,
    translate_world_updates,
)
from tta.privacy.cost import get_cost_tracker, reset_cost_tracker

log = structlog.get_logger()

STAGE_MAP: dict[StageName, Stage] = {
    StageName.UNDERSTAND: understand_stage,
    StageName.CONTEXT: context_stage,
    StageName.GENERATE: generate_stage,
    StageName.DELIVER: deliver_stage,
}


async def run_pipeline(
    state: TurnState,
    deps: PipelineDeps,
    config: PipelineConfig | None = None,
) -> TurnState:
    """Execute the turn pipeline: understand → context → generate → deliver.

    Each stage runs within its own timeout. The entire pipeline
    is also bounded by an overall timeout. On any failure, the
    returned TurnState has status=failed.

    Creates an OTel span tree: turn_pipeline → stage_* (FR-15.14).
    """
    config = config or PipelineConfig()
    tracer = get_tracer()

    # Bind session/turn IDs to structlog context for all stage logs.
    bind_context(
        session_id=state.session_id,
        turn_id=state.turn_id,
        turn_number=state.turn_number,
    )

    pipeline_start = time.monotonic()

    with tracer.start_as_current_span(
        "turn_pipeline",
        attributes={
            "tta.session_id": str(state.session_id),
            "tta.turn_id": str(state.turn_id),
            "tta.turn_number": state.turn_number or 0,
        },
    ) as pipeline_span:
        # FR-15.37: count turns for daily cost summary
        record_daily_turn()
        try:
            async with asyncio.timeout(config.overall_timeout_seconds):
                for stage_config in config.stages:
                    stage_fn = STAGE_MAP[stage_config.name]
                    stage_name = stage_config.name.value

                    with tracer.start_as_current_span(
                        f"stage_{stage_name}",
                        attributes={"tta.stage": stage_name},
                    ) as stage_span:
                        stage_start = time.monotonic()
                        try:
                            async with asyncio.timeout(stage_config.timeout_seconds):
                                state = await stage_fn(state, deps)
                        except TimeoutError:
                            log.error(
                                "stage_timeout",
                                stage=stage_name,
                                timeout=stage_config.timeout_seconds,
                            )
                            stage_span.set_status(trace.StatusCode.ERROR, "timeout")
                            stage_elapsed = time.monotonic() - stage_start
                            TURN_STAGE_DURATION.labels(
                                stage=stage_name, status="timeout"
                            ).observe(stage_elapsed)
                            TURN_TOTAL.labels(status="failure").inc()
                            TURN_TOTAL_DURATION.observe(
                                time.monotonic() - pipeline_start
                            )
                            return state.model_copy(
                                update={"status": TurnStatus.failed}
                            )
                        except Exception as exc:
                            log.error(
                                "stage_failed",
                                stage=stage_name,
                                exc_info=True,
                            )
                            set_span_error(exc)
                            stage_elapsed = time.monotonic() - stage_start
                            TURN_STAGE_DURATION.labels(
                                stage=stage_name, status="error"
                            ).observe(stage_elapsed)
                            TURN_TOTAL.labels(status="failure").inc()
                            TURN_TOTAL_DURATION.observe(
                                time.monotonic() - pipeline_start
                            )
                            return state.model_copy(
                                update={"status": TurnStatus.failed}
                            )

                        stage_elapsed = time.monotonic() - stage_start
                        stage_metric_status = (
                            "error" if state.status == TurnStatus.failed else "success"
                        )
                        TURN_DURATION.labels(stage=stage_name).observe(stage_elapsed)
                        TURN_STAGE_DURATION.labels(
                            stage=stage_name, status=stage_metric_status
                        ).observe(stage_elapsed)
                        log.debug(
                            "stage_complete",
                            stage=stage_name,
                            duration_ms=round(stage_elapsed * 1000, 1),
                        )

                    # Early return if stage marked turn as failed
                    if state.status == TurnStatus.failed:
                        log.info(
                            "pipeline_early_exit",
                            stage=stage_name,
                            status=state.status,
                        )
                        pipeline_span.set_status(trace.StatusCode.ERROR, "stage_failed")
                        TURN_TOTAL.labels(status="failure").inc()
                        TURN_TOTAL_DURATION.observe(time.monotonic() - pipeline_start)
                        return state

                    # Early return for moderated turns — redirect narrative
                    # is already set, skip remaining stages (FR-24.06).
                    if state.status == TurnStatus.moderated:
                        log.info(
                            "pipeline_early_exit",
                            stage=stage_name,
                            status=state.status,
                            safety_flags=state.safety_flags,
                        )
                        TURN_TOTAL.labels(status="moderated").inc()
                        TURN_TOTAL_DURATION.observe(time.monotonic() - pipeline_start)
                        return state

        except TimeoutError:
            log.error(
                "pipeline_overall_timeout",
                timeout=config.overall_timeout_seconds,
            )
            pipeline_span.set_status(trace.StatusCode.ERROR, "overall_timeout")
            TURN_TOTAL.labels(status="failure").inc()
            TURN_TOTAL_DURATION.observe(time.monotonic() - pipeline_start)
            return state.model_copy(update={"status": TurnStatus.failed})

    TURN_TOTAL.labels(status="success").inc()
    TURN_TOTAL_DURATION.observe(time.monotonic() - pipeline_start)
    return state


# ── Dispatch wrapper (persistence, cost, world-changes, SSE) ──────────────────


async def dispatch_pipeline(
    app_state: object,
    game_id: UUID,
    turn_id: UUID,
    turn_number: int,
    player_input: str,
    game_state: dict,
    session_cost_usd: float = 0.0,
    player_id: str = "",
) -> None:
    """Run the pipeline as a background task and persist results.

    This is the bridge between the HTTP layer (route handler) and the
    pure pipeline (run_pipeline).  It handles cost tracking, turn
    persistence, auto-save metadata, title/summary/snapshot background
    tasks, world-state application, and SSE result publishing.
    """
    deps = app_state.pipeline_deps  # type: ignore[attr-defined]
    turn_repo = deps.turn_repo

    # Bind game/turn context for correlated logging (S15 §7).
    # player_id is pseudonymized per FR-15.21 before entering logs.
    from tta.observability.langfuse import pseudonymize_player_id

    bind_context(
        session_id=game_id,
        turn_id=turn_id,
        player_id=pseudonymize_player_id(player_id) if player_id else None,
    )

    # Seed cost tracker with session total from DB (FR-07.19).
    reset_cost_tracker(
        session_id=str(game_id),
        session_total_usd=session_cost_usd,
    )

    state = TurnState(
        session_id=game_id,
        turn_id=turn_id,
        turn_number=turn_number,
        player_input=player_input,
        game_state=game_state,
    )

    start = time.monotonic()
    try:
        result = await run_pipeline(state, deps)
    except Exception:
        log.error("pipeline_dispatch_failed", game_id=str(game_id), exc_info=True)
        result = state.model_copy(update={"status": TurnStatus.failed})

    elapsed_ms = (time.monotonic() - start) * 1000
    result = result.model_copy(update={"latency_ms": elapsed_ms})

    # Persist turn result via repository
    turn_persisted = False
    try:
        if (
            result.status
            in (
                TurnStatus.complete,
                TurnStatus.moderated,
            )
            and result.narrative_output
        ):
            token_dict = result.token_count.model_dump() if result.token_count else {}
            await turn_repo.complete_turn(
                turn_id=turn_id,
                narrative_output=result.narrative_output,
                model_used=result.model_used or "unknown",
                latency_ms=elapsed_ms,
                token_count=token_dict,
            )
            # FR-24.06 item 5: mark moderated turns distinctly
            if result.status == TurnStatus.moderated:
                await turn_repo.update_status(turn_id, "moderated")
            turn_persisted = True
        else:
            # FR-23.18: preserve partial narrative on failure
            await turn_repo.fail_turn(turn_id, narrative_output=result.narrative_output)
    except Exception:
        log.error("turn_persist_failed", turn_id=str(turn_id), exc_info=True)
        # Last-resort: ensure turn exits processing state to prevent
        # permanent concurrent-turn lock (critique finding #5).
        try:
            await turn_repo.update_status(turn_id, "failed")
        except Exception:
            log.error(
                "turn_failsafe_status_update_failed",
                turn_id=str(turn_id),
                exc_info=True,
            )

    # --- FR-27.05/06: Post-turn auto-save (metadata) ---
    # Gate on turn_persisted to avoid incrementing counters for failed saves.
    if turn_persisted:
        # TODO: inject session factory via PipelineDeps instead of
        # reaching into repo internals (_sf).
        sf = app_state.pipeline_deps.turn_repo._sf  # type: ignore[attr-defined]
        try:
            async with sf() as meta_sess:
                now = dt.now(UTC)
                await meta_sess.execute(
                    sa.text(
                        "UPDATE game_sessions "
                        "SET turn_count = turn_count + 1, "
                        "last_played_at = :now, updated_at = :now "
                        "WHERE id = :gid"
                    ),
                    {"gid": game_id, "now": now},
                )
                await meta_sess.commit()
        except Exception:
            log.warning(
                "auto_save_metadata_failed",
                game_id=str(game_id),
                exc_info=True,
            )
            # FR-27.07: mark needs_recovery so resume can fix it
            try:
                async with sf() as recovery_sess:
                    await recovery_sess.execute(
                        sa.text(
                            "UPDATE game_sessions "
                            "SET needs_recovery = TRUE "
                            "WHERE id = :gid"
                        ),
                        {"gid": game_id},
                    )
                    await recovery_sess.commit()
            except Exception:
                log.error(
                    "needs_recovery_flag_failed",
                    game_id=str(game_id),
                    exc_info=True,
                )

        # FR-27.22: title from opening narrative (turn 1 IS genesis)
        if turn_number == 1 and result.narrative_output:
            asyncio.create_task(
                _generate_title_bg(app_state, game_id, result.narrative_output)
            )

        # --- FR-07.19: Persist turn cost to session (S07 cost management) ---
        try:
            tracker = get_cost_tracker()
            turn_cost = tracker.turn_cost_usd
            if turn_cost > 0:
                async with sf() as cost_sess:
                    cost_result = await cost_sess.execute(
                        sa.text(
                            "UPDATE game_sessions "
                            "SET total_cost_usd = total_cost_usd + :cost, "
                            "updated_at = :now "
                            "WHERE id = :gid "
                            "RETURNING total_cost_usd, cost_warning_sent"
                        ),
                        {
                            "gid": game_id,
                            "cost": turn_cost,
                            "now": dt.now(UTC),
                        },
                    )
                    cost_row = cost_result.one()
                    await cost_sess.commit()

                    # Send 80% warning once
                    settings = get_settings()
                    cap = settings.session_cost_cap_usd
                    if (
                        cap > 0
                        and not cost_row.cost_warning_sent
                        and float(cost_row.total_cost_usd)
                        >= cap * settings.session_cost_warn_pct
                    ):
                        async with sf() as warn_sess:
                            await warn_sess.execute(
                                sa.text(
                                    "UPDATE game_sessions "
                                    "SET cost_warning_sent = true, "
                                    "updated_at = :now WHERE id = :gid"
                                ),
                                {
                                    "gid": game_id,
                                    "now": dt.now(UTC),
                                },
                            )
                            await warn_sess.commit()
                        log.warning(
                            "session_cost_warning",
                            game_id=str(game_id),
                            total=float(cost_row.total_cost_usd),
                            cap=cap,
                        )
        except Exception:
            log.warning(
                "cost_persist_failed",
                game_id=str(game_id),
                exc_info=True,
            )

        # FR-27.20: fire-and-forget summary regen every Nth turn
        settings = app_state.settings  # type: ignore[attr-defined]
        if (
            settings.summary_interval > 0
            and turn_number % settings.summary_interval == 0
        ):
            asyncio.create_task(_regen_summary_bg(app_state, game_id))

        # AC-12.04: fire-and-forget game snapshot every Nth turn
        if (
            settings.snapshot_interval > 0
            and turn_number % settings.snapshot_interval == 0
        ):
            asyncio.create_task(
                _write_snapshot_bg(app_state, game_id, result.game_state, turn_number)
            )

    # --- Apply world state changes (best-effort) ---
    if turn_persisted and result.world_state_updates:
        try:
            from tta.world.changes import apply_changes

            world_svc = deps.world
            changes = translate_world_updates(result.world_state_updates)
            # Separate relationship changes for dedicated handling (S06 AC-6.4)
            rel_changes = [
                c for c in changes if c.type == WorldChangeType.RELATIONSHIP_CHANGED
            ]
            other_changes = [
                c for c in changes if c.type != WorldChangeType.RELATIONSHIP_CHANGED
            ]
            if other_changes:
                await apply_changes(other_changes, world_svc, game_id)
            # Apply relationship changes via RelationshipService (fire-and-forget)
            rel_svc = deps.relationship_service
            if rel_changes and rel_svc is not None:
                for rc in rel_changes:
                    try:
                        delta = parse_relationship_delta(rc.payload)
                        await rel_svc.update_relationship(
                            session_id=str(game_id),
                            source_id="player",
                            target_id=rc.entity_id,
                            change=delta,
                        )
                    except Exception:
                        log.debug(
                            "relationship_change_skipped",
                            entity=rc.entity_id,
                            exc_info=True,
                        )
            applied = len(other_changes) + len(rel_changes)
            if applied:
                log.info(
                    "world_changes_applied",
                    game_id=str(game_id),
                    count=applied,
                    relationships=len(rel_changes),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning(
                "world_changes_failed_graceful_degradation",
                game_id=str(game_id),
                exc_info=True,
            )

    # Publish result for SSE endpoint
    try:
        store = app_state.turn_result_store  # type: ignore[attr-defined]
        await store.publish(str(turn_id), result)
    except Exception:
        log.error(
            "turn_result_publish_failed",
            turn_id=str(turn_id),
            exc_info=True,
        )
    log.info(
        "pipeline_dispatch_complete",
        game_id=str(game_id),
        turn_id=str(turn_id),
        status=result.status,
        latency_ms=round(elapsed_ms, 1),
    )


async def _generate_title_bg(app_state: object, game_id: UUID, narrative: str) -> None:
    """Fire-and-forget: generate a title from the opening narrative."""
    try:
        svc = app_state.summary_service  # type: ignore[attr-defined]
        title = await svc.generate_title(narrative)
        if title:
            sf = app_state.pipeline_deps.turn_repo._sf  # type: ignore[attr-defined]
            async with sf() as sess:
                await sess.execute(
                    sa.text(
                        "UPDATE game_sessions SET title = :t, "
                        "updated_at = :now WHERE id = :gid AND title IS NULL"
                    ),
                    {
                        "gid": game_id,
                        "t": title[:80],
                        "now": dt.now(UTC),
                    },
                )
                await sess.commit()
            log.info("title_generated", game_id=str(game_id))
    except Exception:
        log.warning("title_generation_failed", game_id=str(game_id), exc_info=True)


async def _write_snapshot_bg(
    app_state: object,
    game_id: UUID,
    game_state_dict: dict,
    turn_number: int,
) -> None:
    """Fire-and-forget: persist a GameState snapshot to PostgreSQL (AC-12.04)."""
    try:
        state = GameState.model_validate(
            {**game_state_dict, "session_id": str(game_id), "turn_number": turn_number}
        )
        svc = app_state.snapshot_service  # type: ignore[attr-defined]
        await svc.save_snapshot(game_id, state)
    except Exception:
        log.warning("snapshot_write_failed", game_id=str(game_id), exc_info=True)


async def _regen_summary_bg(app_state: object, game_id: UUID) -> None:
    """Fire-and-forget: regenerate the context summary for a game."""
    try:
        sf = app_state.pipeline_deps.turn_repo._sf  # type: ignore[attr-defined]
        turn_repo = app_state.pipeline_deps.turn_repo  # type: ignore[attr-defined]
        settings = app_state.settings  # type: ignore[attr-defined]

        turns = await turn_repo.get_recent_turns(
            game_id, limit=settings.resume_turn_count
        )
        if not turns:
            return

        svc = app_state.summary_service  # type: ignore[attr-defined]
        summary = await svc.generate_context_summary(turns)
        if summary:
            now = dt.now(UTC)
            async with sf() as sess:
                await sess.execute(
                    sa.text(
                        "UPDATE game_sessions "
                        "SET summary = :s, summary_generated_at = :now, "
                        "updated_at = :now WHERE id = :gid"
                    ),
                    {"gid": game_id, "s": summary[:200], "now": now},
                )
                await sess.commit()
            log.info("summary_regenerated", game_id=str(game_id))
    except Exception:
        log.warning(
            "summary_regeneration_failed",
            game_id=str(game_id),
            exc_info=True,
        )
