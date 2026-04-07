"""Langfuse observability integration for LLM tracing.

Provides conditional Langfuse initialization (no-op when unconfigured)
and a ``@trace_llm`` decorator that records input, output, model,
latency, and token counts for every LLM call.

Privacy: traces are tagged ``user_input`` so player content is
filterable inside the Langfuse dashboard (spec S17 / AC-3).
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

# Populated by init_langfuse(); remains None when Langfuse is disabled.
_langfuse_client: Any = None

# Fields stripped from trace input to avoid leaking PII (AC-3).
_PII_FIELDS = frozenset(
    {"email", "name", "username", "phone", "address", "ip", "player_id"}
)


# -- public API --------------------------------------------------------


def init_langfuse(settings: Any) -> None:
    """Initialise the Langfuse client **if** configured (AC-1).

    When ``settings.langfuse_host`` is falsy the client stays ``None``
    and every downstream call becomes a silent no-op.
    """
    global _langfuse_client  # noqa: PLW0603

    if settings.langfuse_host:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
    else:
        _langfuse_client = None


def get_langfuse() -> Any:
    """Return the current Langfuse client, or ``None`` if disabled."""
    return _langfuse_client


def shutdown_langfuse() -> None:
    """Flush pending events and shut down the Langfuse client."""
    if _langfuse_client is not None:
        _langfuse_client.flush()


def trace_llm(name: str) -> Callable:  # type: ignore[type-arg]
    """Decorator that traces an ``async`` LLM call via Langfuse (AC-2).

    Recorded fields: input, output, model, latency_ms, token counts.
    The trace is tagged ``user_input`` for privacy filtering (AC-3).

    When Langfuse is disabled the decorated function executes unchanged.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if _langfuse_client is None:
                return await func(*args, **kwargs)  # type: ignore[misc]

            trace = _langfuse_client.trace(name=name, tags=["user_input"])
            start = time.monotonic()

            try:
                result = await func(*args, **kwargs)  # type: ignore[misc]
                latency_ms = int((time.monotonic() - start) * 1000)

                gen_kwargs = _build_generation_kwargs(name, result, latency_ms, kwargs)
                trace.generation(**gen_kwargs)
                return result  # type: ignore[return-value]
            except Exception as exc:
                trace.update(level="ERROR", status_message=str(exc))
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


# -- helpers -----------------------------------------------------------


def _sanitize_input(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Strip PII fields from the keyword arguments before tracing."""
    return {k: v for k, v in kwargs.items() if k not in _PII_FIELDS}


def _build_generation_kwargs(
    name: str,
    result: Any,
    latency_ms: int,
    call_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build the kwargs dict passed to ``trace.generation()``."""
    gen: dict[str, Any] = {
        "name": name,
        "input": _sanitize_input(call_kwargs),
        "metadata": {"latency_ms": latency_ms},
    }

    # LiteLLM responses expose .model and .usage
    if hasattr(result, "model"):
        gen["model"] = result.model

    if hasattr(result, "usage") and result.usage is not None:
        usage = result.usage
        gen["usage"] = {
            "input": getattr(usage, "prompt_tokens", None),
            "output": getattr(usage, "completion_tokens", None),
            "total": getattr(usage, "total_tokens", None),
        }

    # Extract text output from a ChatCompletion-style response
    if hasattr(result, "choices") and result.choices:
        gen["output"] = result.choices[0].message.content
    else:
        gen["output"] = str(result)

    return gen
