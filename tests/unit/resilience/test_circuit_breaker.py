"""Tests for circuit breaker (AC-23.5, EC-23.6, FR-23.12-15)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from tta.api.errors import AppError
from tta.errors import ErrorCategory
from tta.resilience.circuit_breaker import (
    LLM_BREAKER,
    NEO4J_BREAKER,
    PG_BREAKER,
    REDIS_BREAKER,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)

# Fast config for tests — low thresholds, tiny windows
FAST_CB = CircuitBreakerConfig(
    failure_threshold=3,
    window_seconds=10.0,
    cooldown_seconds=0.05,
    service_name="test",
    max_cooldown_seconds=0.5,
)


# --- Preset sanity checks (FR-23.14 table) ---


class TestCircuitBreakerPresets:
    def test_llm_preset(self) -> None:
        assert LLM_BREAKER.failure_threshold == 5
        assert LLM_BREAKER.window_seconds == 60.0
        assert LLM_BREAKER.cooldown_seconds == 30.0
        assert LLM_BREAKER.service_name == "llm"

    def test_pg_preset(self) -> None:
        assert PG_BREAKER.failure_threshold == 3
        assert PG_BREAKER.window_seconds == 30.0
        assert PG_BREAKER.cooldown_seconds == 15.0

    def test_neo4j_preset(self) -> None:
        assert NEO4J_BREAKER.failure_threshold == 3
        assert NEO4J_BREAKER.service_name == "neo4j"

    def test_redis_preset(self) -> None:
        assert REDIS_BREAKER.failure_threshold == 5
        assert REDIS_BREAKER.cooldown_seconds == 10.0


# --- State machine basics ---


class TestCircuitBreakerStateMachine:
    """AC-23.5: circuit breaker opens after threshold, fails fast."""

    async def test_starts_closed(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        assert cb.state == CircuitState.CLOSED

    async def test_stays_closed_below_threshold(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        # 2 failures < threshold of 3
        for _ in range(2):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")
        assert cb.state == CircuitState.CLOSED

    async def test_opens_at_threshold(self) -> None:
        """AC-23.5: opens after threshold failures."""
        cb = CircuitBreaker(FAST_CB)
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")
        assert cb.state == CircuitState.OPEN

    async def test_open_circuit_fails_fast(self) -> None:
        """AC-23.5: fails fast when open."""
        cb = CircuitBreaker(FAST_CB)
        # Trip it
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        # Should fail fast with AppError, not execute body
        body_called = False
        with pytest.raises(AppError) as exc_info:
            async with cb:
                body_called = True

        assert not body_called
        assert exc_info.value.category == ErrorCategory.SERVICE_UNAVAILABLE
        assert "CIRCUIT_OPEN" in exc_info.value.code

    async def test_success_does_not_count_as_failure(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        for _ in range(10):
            async with cb:
                pass  # success
        assert cb.state == CircuitState.CLOSED


# --- Half-open behavior ---


class TestHalfOpenBehavior:
    async def test_transitions_to_half_open_after_cooldown(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        # Trip it
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")
        assert cb.state == CircuitState.OPEN

        # Simulate cooldown elapsed
        cb._opened_at = time.monotonic() - FAST_CB.cooldown_seconds - 1

        # Next call transitions to half-open
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED

    async def test_half_open_success_closes_circuit(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        cb._opened_at = time.monotonic() - FAST_CB.cooldown_seconds - 1

        async with cb:
            pass  # probe succeeds

        assert cb.state == CircuitState.CLOSED

    async def test_half_open_failure_reopens_circuit(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        cb._opened_at = time.monotonic() - FAST_CB.cooldown_seconds - 1

        with pytest.raises(ConnectionError):
            async with cb:
                raise ConnectionError("still failing")

        assert cb.state == CircuitState.OPEN

    async def test_half_open_blocks_concurrent_probes(self) -> None:
        """Rubber-duck finding: only one probe at a time in half-open."""
        cb = CircuitBreaker(FAST_CB)
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        cb._opened_at = time.monotonic() - FAST_CB.cooldown_seconds - 1

        # First caller enters half-open (gets the probe)
        async with cb._lock:
            # Simulate being in half-open with probe in flight
            cb._state = CircuitState.HALF_OPEN
            cb._probe_in_flight = True

        # Second caller should fail fast
        with pytest.raises(AppError) as exc_info:
            async with cb:
                pass

        assert "CIRCUIT_OPEN" in exc_info.value.code


# --- Sliding window (FR-23.12) ---


class TestSlidingWindow:
    async def test_old_failures_expire(self) -> None:
        """Failures outside the window don't count toward threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            window_seconds=10.0,
            cooldown_seconds=0.05,
            service_name="test",
        )
        cb = CircuitBreaker(config)

        # Record 2 failures, then age them out
        for _ in range(2):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        # Push old failures outside window
        now = time.monotonic()
        cb._failures.clear()
        cb._failures.append(now - 20.0)
        cb._failures.append(now - 15.0)

        # One more failure — only this one is in the window
        with pytest.raises(ConnectionError):
            async with cb:
                raise ConnectionError("fail")

        # Should still be closed (1 in-window failure < threshold of 3)
        assert cb.state == CircuitState.CLOSED


# --- Flapping protection (EC-23.6) ---


class TestFlappingProtection:
    async def test_cooldown_doubles_on_consecutive_trips(self) -> None:
        """EC-23.6: exponential cooldown for flapping (failed probes)."""
        cb = CircuitBreaker(FAST_CB)
        initial_cooldown = FAST_CB.cooldown_seconds

        # First trip from CLOSED
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")
        assert cb.state == CircuitState.OPEN
        assert cb._current_cooldown == initial_cooldown
        assert cb._consecutive_trips == 1

        # Failed probe → re-trip, cooldown should double
        cb._opened_at = time.monotonic() - cb._current_cooldown - 1
        with pytest.raises(ConnectionError):
            async with cb:
                raise ConnectionError("still failing")
        assert cb.state == CircuitState.OPEN
        assert cb._consecutive_trips == 2
        assert cb._current_cooldown == initial_cooldown * 2

    async def test_cooldown_capped_at_max(self) -> None:
        """EC-23.6: max 5 minute cooldown (or max_cooldown_seconds)."""
        cb = CircuitBreaker(FAST_CB)

        # Force many consecutive trips
        for _trip_num in range(20):
            cb._state = CircuitState.CLOSED
            cb._failures.clear()
            for _ in range(3):
                with pytest.raises(ConnectionError):
                    async with cb:
                        raise ConnectionError("fail")

        assert cb._current_cooldown <= FAST_CB.max_cooldown_seconds

    async def test_successful_recovery_resets_consecutive_trips(
        self,
    ) -> None:
        cb = CircuitBreaker(FAST_CB)

        # Trip it
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        # Recover
        cb._opened_at = time.monotonic() - cb._current_cooldown - 1
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED
        assert cb._consecutive_trips == 0
        assert cb._current_cooldown == FAST_CB.cooldown_seconds


# --- Logging (FR-23.15) ---


class TestCircuitBreakerLogging:
    async def test_state_change_logged_at_warn(self) -> None:
        """FR-23.15: state changes logged at WARN level."""
        cb = CircuitBreaker(FAST_CB)
        with patch("tta.resilience.circuit_breaker.structlog") as mock_sl:
            mock_logger = mock_sl.get_logger.return_value
            for _ in range(3):
                with pytest.raises(ConnectionError):
                    async with cb:
                        raise ConnectionError("fail")

            mock_logger.warning.assert_called()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "circuit_breaker_state_change"

    async def test_no_log_when_state_unchanged(self) -> None:
        """No spurious logs for non-transitions."""
        cb = CircuitBreaker(FAST_CB)
        with patch("structlog.get_logger") as mock_get:
            mock_logger = mock_get.return_value
            # Success in closed state — no transition
            async with cb:
                pass
            mock_logger.warning.assert_not_called()


# --- Error contract ---


class TestCircuitBreakerErrorContract:
    async def test_fail_fast_error_has_correct_fields(self) -> None:
        cb = CircuitBreaker(FAST_CB)
        for _ in range(3):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("fail")

        with pytest.raises(AppError) as exc_info:
            async with cb:
                pass

        err = exc_info.value
        assert err.category == ErrorCategory.SERVICE_UNAVAILABLE
        assert err.code == "TEST_CIRCUIT_OPEN"
        assert "test" in err.message
        assert "cooldown" in err.message

    async def test_body_exception_propagates(self) -> None:
        """The breaker records the failure but does not suppress it."""
        cb = CircuitBreaker(FAST_CB)
        with pytest.raises(ValueError, match="app error"):
            async with cb:
                raise ValueError("app error")


class TestExceptionFilter:
    """counted_exceptions controls which errors trip the breaker."""

    async def test_uncounted_exception_does_not_trip(self) -> None:
        """Exceptions NOT in counted_exceptions don't count as failures."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            window_seconds=10.0,
            cooldown_seconds=0.1,
            service_name="filtered",
            counted_exceptions=(ConnectionError,),
        )
        cb = CircuitBreaker(config)

        # ValueError is not counted — should not trip
        for _ in range(5):
            with pytest.raises(ValueError):
                async with cb:
                    raise ValueError("app bug")
        assert cb.state == CircuitState.CLOSED

    async def test_counted_exception_does_trip(self) -> None:
        """Exceptions IN counted_exceptions count normally."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            window_seconds=10.0,
            cooldown_seconds=0.1,
            service_name="filtered",
            counted_exceptions=(ConnectionError,),
        )
        cb = CircuitBreaker(config)

        for _ in range(2):
            with pytest.raises(ConnectionError):
                async with cb:
                    raise ConnectionError("down")
        assert cb.state == CircuitState.OPEN

    async def test_empty_tuple_counts_all(self) -> None:
        """Default (empty tuple) counts all exceptions."""
        cb = CircuitBreaker(FAST_CB)  # FAST_CB has no counted_exceptions
        for _ in range(3):
            with pytest.raises(ValueError):
                async with cb:
                    raise ValueError("anything")
        assert cb.state == CircuitState.OPEN
