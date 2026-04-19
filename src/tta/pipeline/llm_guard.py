"""Guarded LLM call helper — semaphore + circuit breaker + cost enforcement.

Wraps every pipeline LLM call so that:
- Session cost budget is checked *before* the call (FR-07.20)
- Semaphore controls concurrency/queue (outer layer)
- Circuit breaker tracks failures (inner layer)
- Actual cost is recorded *after* the call (FR-07.17)
- Langfuse trace + generation recorded per call (S15 AC-13)
- OTel child span with LLM attributes per call (S15 AC-10)

Queue-full/timeout from semaphore does NOT trip the breaker.
"""

from __future__ import annotations

import time

import structlog
from opentelemetry import trace

from tta.llm.client import LLMResponse, Message
from tta.llm.errors import BudgetExceededError
from tta.llm.roles import ModelRole
from tta.observability.daily_cost import record_daily_cost
from tta.observability.langfuse import record_llm_generation
from tta.observability.metrics import (
    LLM_COST_TOTAL,
    LLM_TOKENS_PER_SECOND,
    SESSION_COST_EXCEEDED,
)
from tta.observability.tracing import current_trace_id
from tta.pipeline.types import PipelineDeps
from tta.privacy.cost import get_cost_tracker, load_pricing_yaml

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

    # Create OTel child span for this specific LLM call (AC-10)
    tracer = trace.get_tracer("tta")
    role_name = role.value if hasattr(role, "value") else str(role)
    start_time = time.monotonic()

    with tracer.start_as_current_span(
        "llm_call",
        attributes={"llm.role": role_name},
    ) as llm_span:
        if deps.llm_semaphore:
            response = await deps.llm_semaphore.execute(_call)
        else:
            response = await _call()

        latency_ms = int((time.monotonic() - start_time) * 1000)

        # --- Post-call: record actual cost (FR-07.17) ---
        tc = response.token_count
        cost_usd = 0.0

        if response.cost_usd and response.cost_usd > 0:
            cost_usd = response.cost_usd
            tracker.record_actual(
                model=response.model_used,
                cost_usd=response.cost_usd,
            )
            LLM_COST_TOTAL.labels(model=response.model_used, role=role_name).inc(
                response.cost_usd
            )
        elif tc.prompt_tokens or tc.completion_tokens:
            pricing_path = settings.llm_pricing_path if settings is not None else None
            pricing_table = load_pricing_yaml(pricing_path)
            cost_usd = tracker.record(
                model=response.model_used,
                prompt_tokens=tc.prompt_tokens,
                completion_tokens=tc.completion_tokens,
                pricing=pricing_table,
            )
            LLM_COST_TOTAL.labels(model=response.model_used, role=role_name).inc(
                cost_usd
            )

        # Set OTel span attributes (AC-10, FR-15.15)
        model_name = response.model_used
        provider = model_name.split("/")[0] if "/" in model_name else "unknown"
        llm_span.set_attribute("llm.model", model_name)
        llm_span.set_attribute("llm.provider", provider)
        llm_span.set_attribute("llm.tokens.prompt", tc.prompt_tokens)
        llm_span.set_attribute("llm.tokens.completion", tc.completion_tokens)
        llm_span.set_attribute("llm.cost_usd", cost_usd)
        llm_span.set_attribute("llm.latency_ms", latency_ms)

        # S28 AC-28.03: update LLM throughput gauge (completion tokens/s)
        if tc.completion_tokens is not None and latency_ms > 0:
            LLM_TOKENS_PER_SECOND.labels(model=model_name).set(
                tc.completion_tokens / (latency_ms / 1000)
            )

        # Feed daily cost accumulator (AC-31)
        if cost_usd > 0:
            record_daily_cost(response.model_used, cost_usd)

        # Record Langfuse trace + generation (AC-13, AC-14, AC-27)
        otel_tid = current_trace_id()
        record_llm_generation(
            name=f"pipeline.{role_name}",
            role=role_name,
            messages=messages,
            result=response,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            otel_trace_id=otel_tid,
        )

    return response
