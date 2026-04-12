"""Guarded LLM call helper — semaphore + circuit breaker + cost enforcement.

Wraps every pipeline LLM call so that:
- Session cost budget is checked *before* the call (FR-07.20)
- Semaphore controls concurrency/queue (outer layer)
- Circuit breaker tracks failures (inner layer)
- Actual cost is recorded *after* the call (FR-07.17)

Queue-full/timeout from semaphore does NOT trip the breaker.
"""

from __future__ import annotations

import structlog

from tta.llm.client import LLMResponse, Message
from tta.llm.errors import BudgetExceededError
from tta.llm.roles import ModelRole
from tta.observability.metrics import (
    LLM_COST_TOTAL,
    SESSION_COST_EXCEEDED,
)
from tta.pipeline.types import PipelineDeps
from tta.privacy.cost import get_cost_tracker

_log = structlog.get_logger(__name__)


async def guarded_llm_call(
    deps: PipelineDeps,
    role: ModelRole,
    messages: list[Message],
) -> LLMResponse:
    """Call LLM with cost enforcement, semaphore, and circuit breaker."""

    # --- Pre-call: session cost budget check (FR-07.20) ---
    settings = deps.settings
    tracker = get_cost_tracker()
    if settings is not None:
        budget_status = tracker.check_session_budget(
            cap_usd=settings.session_cost_cap_usd,
            warn_pct=settings.session_cost_warn_pct,
        )
        if budget_status == "exceeded":
            SESSION_COST_EXCEEDED.inc()
            raise BudgetExceededError(
                "Session cost cap reached — please start a new session.",
                model="",
            )
        if budget_status == "warning":
            _log.warning(
                "session_cost_warning",
                session_id=tracker.session_id,
                total_usd=tracker.session_total_usd,
                cap_usd=settings.session_cost_cap_usd,
            )
        # Per-turn cost cap check (FR-07.21)
        if tracker.turn_cost_usd >= settings.turn_cost_cap_usd:
            _log.warning(
                "turn_cost_cap_reached",
                turn_cost=tracker.turn_cost_usd,
                cap=settings.turn_cost_cap_usd,
            )
            raise BudgetExceededError(
                "Turn cost cap reached — this turn used too many LLM calls.",
                model="",
            )

    # --- LLM call with semaphore + circuit breaker ---
    async def _call() -> LLMResponse:
        if deps.llm_circuit_breaker:
            async with deps.llm_circuit_breaker:
                return await deps.llm.generate(role=role, messages=messages)
        return await deps.llm.generate(role=role, messages=messages)

    if deps.llm_semaphore:
        response = await deps.llm_semaphore.execute(_call)
    else:
        response = await _call()

    # --- Post-call: record actual cost (FR-07.17) ---
    # Prefer response.cost_usd from LiteLLM when available;
    # fall back to estimate_cost() via tracker.record().
    tc = response.token_count
    role_name = role.value if hasattr(role, "value") else str(role)

    if response.cost_usd and response.cost_usd > 0:
        # Use actual provider cost
        tracker.record_actual(
            model=response.model_used,
            cost_usd=response.cost_usd,
        )
        LLM_COST_TOTAL.labels(model=response.model_used, role=role_name).inc(
            response.cost_usd
        )
    elif tc.prompt_tokens or tc.completion_tokens:
        # Fall back to estimation
        estimated = tracker.record(
            model=response.model_used,
            prompt_tokens=tc.prompt_tokens,
            completion_tokens=tc.completion_tokens,
        )
        LLM_COST_TOTAL.labels(model=response.model_used, role=role_name).inc(estimated)

    return response
