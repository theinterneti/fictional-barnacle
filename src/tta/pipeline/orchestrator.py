"""Pipeline orchestrator — runs the four stages in sequence.

Enforces per-stage and overall timeouts. On failure in any stage,
returns the TurnState with status=failed.
(plans/llm-and-pipeline.md §7)
"""

from __future__ import annotations

import asyncio
import time

import structlog
from opentelemetry import trace

from tta.logging import bind_context
from tta.models.turn import TurnState, TurnStatus
from tta.observability.metrics import TURN_DURATION, TURN_TOTAL
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

    with tracer.start_as_current_span(
        "turn_pipeline",
        attributes={
            "tta.session_id": str(state.session_id),
            "tta.turn_id": str(state.turn_id),
            "tta.turn_number": state.turn_number or 0,
        },
    ) as pipeline_span:
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
                            TURN_TOTAL.labels(status="failure").inc()
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
                            TURN_TOTAL.labels(status="failure").inc()
                            return state.model_copy(
                                update={"status": TurnStatus.failed}
                            )

                        stage_ms = round((time.monotonic() - stage_start) * 1000, 1)
                        TURN_DURATION.labels(stage=stage_name).observe(
                            time.monotonic() - stage_start
                        )
                        log.debug(
                            "stage_complete",
                            stage=stage_name,
                            duration_ms=stage_ms,
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
                        return state

        except TimeoutError:
            log.error(
                "pipeline_overall_timeout",
                timeout=config.overall_timeout_seconds,
            )
            pipeline_span.set_status(trace.StatusCode.ERROR, "overall_timeout")
            TURN_TOTAL.labels(status="failure").inc()
            return state.model_copy(update={"status": TurnStatus.failed})

    TURN_TOTAL.labels(status="success").inc()
    return state
