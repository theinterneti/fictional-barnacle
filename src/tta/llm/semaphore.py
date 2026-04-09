"""LLM concurrency semaphore (S28 FR-28.11–FR-28.13).

Controls concurrent LLM requests with a bounded queue and
configurable timeout to prevent resource exhaustion.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog

from tta.api.errors import AppError
from tta.errors import ErrorCategory

log = structlog.get_logger()

T = TypeVar("T")


class LLMSemaphore:
    """Bounded concurrency limiter for LLM calls.

    Parameters
    ----------
    max_concurrent:
        Maximum simultaneous LLM requests (FR-28.11, default 10).
    queue_size:
        Maximum pending requests in queue (FR-28.12, default 50).
        When exceeded, new requests get 503.
    timeout:
        Per-request timeout in seconds (FR-28.13, default 30).
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        queue_size: int = 50,
        timeout: int = 30,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._queue_size = queue_size
        self._timeout = timeout
        self._waiting = 0
        self._active = 0

    @property
    def active(self) -> int:
        """Number of currently active LLM calls."""
        return self._active

    @property
    def waiting(self) -> int:
        """Number of requests waiting in queue."""
        return self._waiting

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def queue_size(self) -> int:
        return self._queue_size

    async def execute(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: object,
        **kwargs: object,
    ) -> T:
        """Execute *fn* under semaphore with queue and timeout.

        Raises 503 if queue is full, cancels on timeout.
        """
        if self._waiting >= self._queue_size:
            log.warning(
                "llm_queue_full",
                waiting=self._waiting,
                limit=self._queue_size,
            )
            raise AppError(
                ErrorCategory.SERVICE_UNAVAILABLE,
                "LLM_QUEUE_FULL",
                "LLM request queue is full. Try again later.",
            )

        self._waiting += 1
        try:
            async with asyncio.timeout(self._timeout):
                await self._semaphore.acquire()
        except TimeoutError:
            log.warning("llm_queue_timeout", timeout=self._timeout)
            raise AppError(
                ErrorCategory.SERVICE_UNAVAILABLE,
                "LLM_TIMEOUT",
                "LLM request timed out waiting in queue.",
            ) from None
        finally:
            self._waiting -= 1

        self._active += 1
        try:
            async with asyncio.timeout(self._timeout):
                return await fn(*args, **kwargs)  # type: ignore[return-value]
        except TimeoutError:
            log.warning("llm_call_timeout", timeout=self._timeout)
            raise AppError(
                ErrorCategory.SERVICE_UNAVAILABLE,
                "LLM_CALL_TIMEOUT",
                "LLM call exceeded timeout.",
            ) from None
        finally:
            self._active -= 1
            self._semaphore.release()
