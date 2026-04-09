"""Shared retry utility with per-service presets (S23 §3.3).

FR-23.09: exponential backoff + jitter for transient failures.
FR-23.10: single shared utility (tenacity).
FR-23.11: after exhaustion → raise AppError with appropriate category.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog
from tenacity import (
    RetryError,
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
)

from tta.errors import ErrorCategory

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Per-service retry configuration (FR-23.09 table)."""

    max_retries: int
    initial_backoff: float
    max_backoff: float
    retryable_exceptions: tuple[type[BaseException], ...]
    error_category: ErrorCategory
    service_name: str


# --- Presets from FR-23.09 table ---

DB_CONNECTION = RetryConfig(
    max_retries=3,
    initial_backoff=0.5,
    max_backoff=4.0,
    retryable_exceptions=(ConnectionError, OSError),
    error_category=ErrorCategory.SERVICE_UNAVAILABLE,
    service_name="postgresql",
)

DB_QUERY = RetryConfig(
    max_retries=2,
    initial_backoff=1.0,
    max_backoff=4.0,
    retryable_exceptions=(TimeoutError,),
    error_category=ErrorCategory.SERVICE_UNAVAILABLE,
    service_name="postgresql",
)

REDIS_CONNECTION = RetryConfig(
    max_retries=3,
    initial_backoff=0.5,
    max_backoff=2.0,
    retryable_exceptions=(ConnectionError, OSError),
    error_category=ErrorCategory.SERVICE_UNAVAILABLE,
    service_name="redis",
)

REDIS_TIMEOUT = RetryConfig(
    max_retries=2,
    initial_backoff=0.5,
    max_backoff=2.0,
    retryable_exceptions=(TimeoutError,),
    error_category=ErrorCategory.SERVICE_UNAVAILABLE,
    service_name="redis",
)

NEO4J_CONNECTION = RetryConfig(
    max_retries=3,
    initial_backoff=0.5,
    max_backoff=4.0,
    retryable_exceptions=(ConnectionError, OSError),
    error_category=ErrorCategory.SERVICE_UNAVAILABLE,
    service_name="neo4j",
)

LLM_CALL = RetryConfig(
    max_retries=2,
    initial_backoff=1.0,
    max_backoff=8.0,
    retryable_exceptions=(ConnectionError, TimeoutError, OSError),
    error_category=ErrorCategory.LLM_FAILURE,
    service_name="llm",
)


def with_retry(config: RetryConfig) -> Callable:
    """Decorator factory that wraps an async function with retry logic.

    Uses tenacity with exponential backoff + jitter per FR-23.09.
    After exhaustion raises AppError with the config's error_category (FR-23.11).
    """

    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        # Build tenacity retry wrapper
        tenacity_retry = retry(
            stop=stop_after_attempt(config.max_retries + 1),
            wait=wait_exponential_jitter(
                initial=config.initial_backoff,
                max=config.max_backoff,
            ),
            retry=_make_retry_filter(config.retryable_exceptions),
            reraise=False,
        )
        retried_fn = tenacity_retry(fn)

        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = structlog.get_logger()
            try:
                return await retried_fn(*args, **kwargs)  # pyright: ignore[reportGeneralTypeIssues]
            except RetryError as exc:
                logger.warning(
                    "retry_exhausted",
                    service=config.service_name,
                    max_retries=config.max_retries,
                    error_category=config.error_category.value,
                    last_error=str(exc.last_attempt.exception())
                    if exc.last_attempt.exception()
                    else None,
                )
                # FR-23.11: raise AppError — import here to avoid circular dep
                from tta.api.errors import AppError

                raise AppError(
                    category=config.error_category,
                    code=f"{config.service_name.upper()}_UNAVAILABLE",
                    message=(
                        f"{config.service_name} unavailable after "
                        f"{config.max_retries} retries"
                    ),
                ) from exc.last_attempt.exception()

        return wrapper  # type: ignore[return-value]

    return decorator


def _make_retry_filter(
    exceptions: tuple[type[BaseException], ...],
) -> Callable:
    """Create a tenacity retry predicate that retries only listed exceptions."""
    from tenacity import retry_if_exception_type

    return retry_if_exception_type(exceptions)
