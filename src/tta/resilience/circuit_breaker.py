"""Circuit breaker for external service calls (S23 §3.4).

FR-23.12: fail-fast when service accumulates N failures in M seconds.
FR-23.13: closed → open → half-open state machine.
FR-23.14: per-service thresholds.
FR-23.15: state changes logged at WARN.
EC-23.6: exponential cooldown for flapping.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

import structlog

from tta.api.errors import AppError
from tta.errors import ErrorCategory


class CircuitState(StrEnum):
    """Circuit breaker states per FR-23.13."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Per-service circuit breaker settings (FR-23.14)."""

    failure_threshold: int
    window_seconds: float
    cooldown_seconds: float
    service_name: str
    max_cooldown_seconds: float = 300.0  # EC-23.6: 5 min cap
    # Only these exception types count toward the failure threshold.
    # Empty tuple = count ALL exceptions (default until integration in #64).
    counted_exceptions: tuple[type[Exception], ...] = ()


# --- Presets from FR-23.14 ---

LLM_BREAKER = CircuitBreakerConfig(
    failure_threshold=5,
    window_seconds=60.0,
    cooldown_seconds=30.0,
    service_name="llm",
)

PG_BREAKER = CircuitBreakerConfig(
    failure_threshold=3,
    window_seconds=30.0,
    cooldown_seconds=15.0,
    service_name="postgresql",
)

NEO4J_BREAKER = CircuitBreakerConfig(
    failure_threshold=3,
    window_seconds=30.0,
    cooldown_seconds=15.0,
    service_name="neo4j",
)

REDIS_BREAKER = CircuitBreakerConfig(
    failure_threshold=5,
    window_seconds=30.0,
    cooldown_seconds=10.0,
    service_name="redis",
)


@dataclass
class CircuitBreaker:
    """Async circuit breaker with sliding-window failure tracking.

    Usage::

        cb = CircuitBreaker(PG_BREAKER)
        async with cb:
            await db.execute(query)

    When the circuit is OPEN, entering the context manager immediately
    raises ``AppError(SERVICE_UNAVAILABLE)``.
    """

    config: CircuitBreakerConfig
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failures: deque[float] = field(default_factory=deque, init=False)
    _opened_at: float = field(default=0.0, init=False)
    _consecutive_trips: int = field(default=0, init=False)
    _current_cooldown: float = field(default=0.0, init=False)
    _probe_in_flight: bool = field(default=False, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self._current_cooldown = self.config.cooldown_seconds

    @property
    def state(self) -> CircuitState:
        return self._state

    async def __aenter__(self) -> Self:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._cooldown_elapsed():
                    self._transition(CircuitState.HALF_OPEN)
                else:
                    raise self._fail_fast_error()

            if self._state == CircuitState.HALF_OPEN:
                # Only one probe at a time — others fail fast
                if self._probe_in_flight:
                    raise self._fail_fast_error()
                self._probe_in_flight = True

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        """Record call outcome and update state.

        Returns False so exceptions propagate to the caller.
        """
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._probe_in_flight = False

            if exc_val is not None and self._is_counted(exc_val):
                self._record_failure()
                if self._state == CircuitState.HALF_OPEN or (
                    self._state == CircuitState.CLOSED
                    and self._window_failures() >= self.config.failure_threshold
                ):
                    self._trip()
            elif self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.CLOSED)
                self._failures.clear()
                self._consecutive_trips = 0
                self._current_cooldown = self.config.cooldown_seconds

        # Never suppress the exception
        return False

    # --- Internal ---

    def _record_failure(self) -> None:
        now = time.monotonic()
        self._failures.append(now)

    def _window_failures(self) -> int:
        """Count failures within the sliding window."""
        cutoff = time.monotonic() - self.config.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
        return len(self._failures)

    def _cooldown_elapsed(self) -> bool:
        return (time.monotonic() - self._opened_at) >= self._current_cooldown

    def _is_counted(self, exc: BaseException) -> bool:
        """Return True if this exception counts toward failure threshold."""
        if not self.config.counted_exceptions:
            return True  # empty tuple → count all
        return isinstance(exc, self.config.counted_exceptions)

    def _trip(self) -> None:
        """Open the circuit (EC-23.6: exponential cooldown for flapping)."""
        self._consecutive_trips += 1
        if self._consecutive_trips > 1:
            self._current_cooldown = min(
                self._current_cooldown * 2,
                self.config.max_cooldown_seconds,
            )
        self._opened_at = time.monotonic()
        self._transition(CircuitState.OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        if old != new_state:
            logger = structlog.get_logger()
            logger.warning(
                "circuit_breaker_state_change",
                service=self.config.service_name,
                from_state=old.value,
                to_state=new_state.value,
                consecutive_trips=self._consecutive_trips,
                current_cooldown=self._current_cooldown,
            )

    def _fail_fast_error(self) -> AppError:
        return AppError(
            category=ErrorCategory.SERVICE_UNAVAILABLE,
            code=f"{self.config.service_name.upper()}_CIRCUIT_OPEN",
            message=(
                f"{self.config.service_name} circuit breaker is open "
                f"(cooldown {self._current_cooldown:.0f}s)"
            ),
            retry_after_seconds=int(self._current_cooldown),
        )
