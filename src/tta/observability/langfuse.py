"""Langfuse observability integration for LLM tracing.

Provides conditional Langfuse initialization (no-op when unconfigured)
and a ``@trace_llm`` decorator that records input, output, model,
latency, token counts, and estimated cost for every LLM call.

Also exposes ``record_llm_generation()`` for imperative use from
``guarded_llm_call()`` — same privacy/resilience guarantees as the
decorator but callable from non-decorator contexts (S15 §4).

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


def _to_langfuse_id(uuid_str: str) -> str:
    """Convert a UUID-like string to Langfuse 32-char hex format.

    Langfuse SDK v4+ requires trace IDs to be 32 lowercase hex
    characters.  Strips dashes, lowercases, and truncates to 32 chars
    so non-UUID or malformed values produce valid trace IDs.
    """
    return uuid_str.replace("-", "").lower()[:32]


# -- public API --------------------------------------------------------


def init_langfuse(settings: Any) -> None:
    """Initialize Langfuse via shared-langfuse when configured (AC-1).

    When ``settings.langfuse_host`` is falsy the client stays unconfigured
    and every downstream call becomes a silent no-op.  A warning is
    logged at startup when disabled (FR-15.19).
    """
    global _langfuse_client  # noqa: PLW0603

    if settings.langfuse_host:
        from shared_langfuse.client import init_langfuse as _init

        _init(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
        )
        _langfuse_client = True  # sentinel: shared-langfuse manages its own client
    else:
        _langfuse_client = None
        _log.warning("langfuse_disabled", reason="langfuse_host not configured")


def get_langfuse() -> Any:
    """Return the shared-langfuse client, or ``None`` if disabled."""
    if _langfuse_client is None:
        return None
    from shared_langfuse.client import get_client

    return get_client()


def shutdown_langfuse() -> None:
    """Flush pending events and shut down the Langfuse client."""
    from shared_langfuse.client import is_configured

    if is_configured():
        from shared_langfuse.client import get_client

        client = get_client()
        if client:
            client.flush()


def record_llm_generation(
    *,
    name: str,
    role: str,
    messages: list[Any],
    result: Any,
    latency_ms: int,
    cost_usd: float,
    otel_trace_id: str | None = None,
    prompt_id: str | None = None,
    prompt_version: str | None = None,
    fragment_versions: dict[str, str] | None = None,
    prompt_hash: str | None = None,
    langfuse_prompt: Any | None = None,
) -> None:
    """Record a single LLM call via shared-langfuse (FR-15.18, AC-09.7).

    Thin wrapper around shared_langfuse.llm_chat() that:
    - Sanitizes PII from messages (AC-3)
    - Propagates session_id, user_id, turn_id from structlog context
    - Links to Langfuse prompt version for provenance (FB-005)
    - Scores latency and cost inline (AC-09.8)

    When shared-langfuse is not configured, this is a silent no-op.
    """
    from shared_langfuse import llm_chat, score_trace
    from shared_langfuse.client import is_configured

    if not is_configured():
        return

    ctx = _get_context_ids()
    session_id = ctx.get("session_id")
    user_id = pseudonymize_player_id(str(ctx["player_id"])) if ctx.get("player_id") else None

    # PII sanitization (AC-3)
    sanitized_input = [
        {
            k: v
            for k, v in (
                m if isinstance(m, dict) else {"role": m.role, "content": m.content}
            ).items()
            if k not in _PII_FIELDS
        }
        for m in messages
    ]

    try:
        llm_chat(
            sanitized_input,
            name=name,
            model=getattr(result, "model_used", "free-model-router"),
            langfuse_prompt=langfuse_prompt,
            tags=[role],
            user_id=user_id,
            session_id=session_id,
        )
    except Exception:
        _warn_langfuse_error("langfuse_generation_failed", name=name)
        return

    # Inline scoring (AC-09.8)
    try:
        score_trace(name="llm_latency_ms", value=float(latency_ms))
        score_trace(name="llm_cost_usd", value=cost_usd)
        if role:
            score_trace(name="llm_role", value=role)
    except Exception:
        _warn_langfuse_error("langfuse_scoring_failed", name=name)


def trace_llm(name: str) -> Callable:  # type: ignore[type-arg]
    """Decorator that traces an async LLM call via shared-langfuse (AC-2).

    When shared-langfuse is not configured, the decorated function
    executes unchanged. If Langfuse is unreachable, the LLM call
    proceeds without instrumentation (EC-15.5).
    """
    from shared_langfuse.client import is_configured

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            if not is_configured():
                return await func(*args, **kwargs)  # type: ignore[misc]

            ctx = _get_context_ids()
            session_id = ctx.get("session_id")
            player_id = ctx.get("player_id")
            user_id = pseudonymize_player_id(str(player_id)) if player_id else None

            start = time.monotonic()
            try:
                result = await func(*args, **kwargs)  # type: ignore[misc]
                latency_ms = int((time.monotonic() - start) * 1000)

                model_used = getattr(result, "model_used", getattr(result, "model", None))

                try:
                    from shared_langfuse import llm_chat, score_trace

                    sanitized = _sanitize_input(kwargs)
                    llm_chat(
                        [{"role": "user", "content": str(sanitized)}],
                        name=name,
                        model=model_used or "free-model-router",
                        tags=["user_input"],
                        user_id=user_id,
                        session_id=session_id,
                    )
                    score_trace(name="llm_latency_ms", value=float(latency_ms))
                except Exception:
                    _warn_langfuse_error("langfuse_generation_failed", name=name)

                return result  # type: ignore[return-value]
            except Exception as exc:
                if is_configured():
                    try:
                        from shared_langfuse import score_trace

                        score_trace(name="llm_error", value=1)
                    except Exception:
                        pass
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


def pseudonymize_player_id(player_id: str) -> str:
    """Hash a player ID for Langfuse (FR-15.21).

    Uses SHA-256 truncated to 16 chars. Not reversible.
    """
    return hashlib.sha256(player_id.encode()).hexdigest()[:16]
