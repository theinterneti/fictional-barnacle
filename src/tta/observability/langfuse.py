"""Langfuse observability integration for LLM tracing.

Provides conditional Langfuse initialization (no-op when unconfigured)
and a ``@trace_llm`` decorator that records input, output, model,
latency, token counts, and estimated cost for every LLM call.

Privacy: PII is sanitized before trace/generation creation (S17 / AC-3).
Traces carry session_id and correlation_id for cross-system linking (S15 §7).
Player IDs are pseudonymized via SHA-256 hash (FR-15.21).
Langfuse unavailability does not block gameplay (EC-15.5).
"""

from __future__ import annotations

import functools
import hashlib
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

import structlog

P = ParamSpec("P")
T = TypeVar("T")

_log = structlog.get_logger(__name__)

# Populated by init_langfuse(); remains None when Langfuse is disabled.
_langfuse_client: Any = None

# Throttle Langfuse failure warnings to once per minute (EC-15.5).
_WARNING_INTERVAL_S: float = 60.0
_last_warning_time: float = 0.0

# Fields stripped from trace input to avoid leaking PII (AC-3).
_PII_FIELDS = frozenset(
    {"email", "name", "username", "phone", "address", "ip", "player_id"}
)


# -- public API --------------------------------------------------------


def init_langfuse(settings: Any) -> None:
    """Initialise the Langfuse client **if** configured (AC-1).

    When ``settings.langfuse_host`` is falsy the client stays ``None``
    and every downstream call becomes a silent no-op.  A warning is
    logged at startup when disabled (FR-15.19).
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
        _log.warning("langfuse_disabled", reason="langfuse_host not configured")


def get_langfuse() -> Any:
    """Return the current Langfuse client, or ``None`` if disabled."""
    return _langfuse_client


def shutdown_langfuse() -> None:
    """Flush pending events and shut down the Langfuse client."""
    if _langfuse_client is not None:
        _langfuse_client.flush()


def trace_llm(name: str) -> Callable:  # type: ignore[type-arg]
    """Decorator that traces an ``async`` LLM call via Langfuse (AC-2).

    Recorded fields: input, output, model, latency_ms, token counts,
    estimated cost, associated session_id and correlation_id.

    When Langfuse is disabled the decorated function executes unchanged.
    If Langfuse is unreachable, the LLM call proceeds without
    instrumentation and a warning is throttled to once per minute
    (EC-15.5).
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if _langfuse_client is None:
                return await func(*args, **kwargs)  # type: ignore[misc]

            ctx = _get_context_ids()
            trace_kwargs: dict[str, Any] = {
                "name": name,
                "tags": ["user_input"],
                "metadata": {"correlation_id": ctx.get("correlation_id")},
            }
            if ctx.get("session_id"):
                trace_kwargs["session_id"] = ctx["session_id"]
            # FR-15.21: pseudonymize player IDs in Langfuse
            player_id = ctx.get("player_id")
            if player_id:
                trace_kwargs["user_id"] = pseudonymize_player_id(str(player_id))

            try:
                trace = _langfuse_client.trace(**trace_kwargs)
            except Exception:
                _warn_langfuse_error("langfuse_trace_failed", name=name)
                return await func(*args, **kwargs)  # type: ignore[misc]

            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)  # type: ignore[misc]
                latency_ms = int((time.monotonic() - start) * 1000)

                gen_kwargs = _build_generation_kwargs(
                    name,
                    result,
                    latency_ms,
                    kwargs,
                    ctx,
                )
                try:
                    trace.generation(**gen_kwargs)
                except Exception:
                    _warn_langfuse_error(
                        "langfuse_generation_failed",
                        name=name,
                    )
                return result  # type: ignore[return-value]
            except Exception as exc:
                try:
                    trace.update(
                        level="ERROR",
                        status_message=_sanitize_error(str(exc)),
                    )
                except Exception:
                    _warn_langfuse_error(
                        "langfuse_update_failed",
                        name=name,
                    )
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


# -- helpers -----------------------------------------------------------


def _get_context_ids() -> dict[str, str | None]:
    """Read correlation_id, session_id, turn_id, player_id from
    structlog context."""
    ctx = structlog.contextvars.get_contextvars()
    return {
        "correlation_id": ctx.get("correlation_id"),
        "session_id": ctx.get("session_id"),
        "turn_id": ctx.get("turn_id"),
        "player_id": ctx.get("player_id"),
    }


def _warn_langfuse_error(event: str, **extra: Any) -> None:
    """Log a Langfuse error throttled to once per minute (EC-15.5)."""
    global _last_warning_time  # noqa: PLW0603
    now = time.monotonic()
    if now - _last_warning_time >= _WARNING_INTERVAL_S:
        _last_warning_time = now
        _log.warning(event, **extra)


def _sanitize_input(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Strip PII fields from the keyword arguments before tracing."""
    return {k: v for k, v in kwargs.items() if k not in _PII_FIELDS}


def _sanitize_error(message: str) -> str:
    """Truncate error messages to avoid leaking PII in traces."""
    max_len = 200
    return message[:max_len] + "..." if len(message) > max_len else message


def pseudonymize_player_id(player_id: str) -> str:
    """Hash a player ID for Langfuse (FR-15.21).

    Uses SHA-256 truncated to 16 chars. Not reversible.
    """
    return hashlib.sha256(player_id.encode()).hexdigest()[:16]


def _build_generation_kwargs(
    name: str,
    result: Any,
    latency_ms: int,
    call_kwargs: dict[str, Any],
    ctx: dict[str, str | None],
) -> dict[str, Any]:
    """Build the kwargs dict passed to ``trace.generation()``."""
    metadata: dict[str, Any] = {
        "latency_ms": latency_ms,
        "correlation_id": ctx.get("correlation_id"),
    }
    if ctx.get("turn_id"):
        metadata["turn_id"] = ctx["turn_id"]

    gen: dict[str, Any] = {
        "name": name,
        "input": _sanitize_input(call_kwargs),
        "metadata": metadata,
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
