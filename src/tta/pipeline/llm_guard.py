"""Guarded LLM call helper — semaphore + circuit breaker.

Wraps every pipeline LLM call so that:
- Semaphore controls concurrency/queue (outer layer)
- Circuit breaker tracks failures (inner layer)
Queue-full/timeout from semaphore does NOT trip the breaker.
"""

from __future__ import annotations

from tta.llm.client import LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.pipeline.types import PipelineDeps


async def guarded_llm_call(
    deps: PipelineDeps,
    role: ModelRole,
    messages: list[Message],
) -> LLMResponse:
    """Call LLM with optional semaphore + circuit breaker."""

    async def _call() -> LLMResponse:
        if deps.llm_circuit_breaker:
            async with deps.llm_circuit_breaker:
                return await deps.llm.generate(role=role, messages=messages)
        return await deps.llm.generate(role=role, messages=messages)

    if deps.llm_semaphore:
        return await deps.llm_semaphore.execute(_call)
    return await _call()
