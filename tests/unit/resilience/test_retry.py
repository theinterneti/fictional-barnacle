"""Tests for retry utility (AC-23.4, FR-23.09/10/11)."""

from __future__ import annotations

import pytest

from tta.api.errors import AppError
from tta.errors import ErrorCategory
from tta.resilience.retry import (
    DB_CONNECTION,
    DB_QUERY,
    LLM_CALL,
    NEO4J_CONNECTION,
    REDIS_CONNECTION,
    REDIS_TIMEOUT,
    RetryConfig,
    with_retry,
)

# --- Preset sanity checks (FR-23.09 table) ---


class TestRetryPresets:
    pytestmark = [pytest.mark.spec("AC-23.04")]

    def test_db_connection_preset(self) -> None:
        assert DB_CONNECTION.max_retries == 3
        assert DB_CONNECTION.initial_backoff == 0.5
        assert DB_CONNECTION.max_backoff == 4.0
        assert DB_CONNECTION.service_name == "postgresql"

    def test_db_query_preset(self) -> None:
        assert DB_QUERY.max_retries == 2
        assert DB_QUERY.initial_backoff == 1.0
        assert DB_QUERY.service_name == "postgresql"

    def test_redis_connection_preset(self) -> None:
        assert REDIS_CONNECTION.max_retries == 3
        assert REDIS_CONNECTION.service_name == "redis"

    def test_redis_timeout_preset(self) -> None:
        assert REDIS_TIMEOUT.max_retries == 2
        assert REDIS_TIMEOUT.service_name == "redis"

    def test_neo4j_connection_preset(self) -> None:
        assert NEO4J_CONNECTION.max_retries == 3
        assert NEO4J_CONNECTION.service_name == "neo4j"

    def test_llm_call_preset(self) -> None:
        assert LLM_CALL.max_retries == 2
        assert LLM_CALL.error_category == ErrorCategory.LLM_FAILURE
        assert LLM_CALL.service_name == "llm"

    def test_presets_are_frozen(self) -> None:
        with pytest.raises(AttributeError):
            DB_CONNECTION.max_retries = 99  # type: ignore[misc]


# --- Decorator behavior ---

FAST_CONFIG = RetryConfig(
    max_retries=2,
    initial_backoff=0.001,
    max_backoff=0.01,
    retryable_exceptions=(ConnectionError,),
    error_category=ErrorCategory.SERVICE_UNAVAILABLE,
    service_name="test",
)


class TestWithRetry:
    """AC-23.4: database retry with exponential backoff + jitter."""

    pytestmark = [pytest.mark.spec("AC-23.04")]

    async def test_success_on_first_attempt(self) -> None:
        call_count = 0

        @with_retry(FAST_CONFIG)
        async def succeeds() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeeds()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_retryable_exception(self) -> None:
        call_count = 0

        @with_retry(FAST_CONFIG)
        async def fails_then_succeeds() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = await fails_then_succeeds()
        assert result == "recovered"
        assert call_count == 3  # 1 initial + 2 retries

    async def test_raises_app_error_after_exhaustion(self) -> None:
        """FR-23.11: after retries exhausted → AppError."""
        call_count = 0

        @with_retry(FAST_CONFIG)
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("down")

        with pytest.raises(AppError) as exc_info:
            await always_fails()

        err = exc_info.value
        assert err.category == ErrorCategory.SERVICE_UNAVAILABLE
        assert err.code == "TEST_UNAVAILABLE"
        assert "2 retries" in err.message
        # 1 initial + 2 retries = 3 total calls
        assert call_count == 3

    async def test_exhaustion_preserves_cause(self) -> None:
        @with_retry(FAST_CONFIG)
        async def always_fails() -> str:
            raise ConnectionError("root cause")

        with pytest.raises(AppError) as exc_info:
            await always_fails()

        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, ConnectionError)

    async def test_non_retryable_exception_propagates_immediately(
        self,
    ) -> None:
        call_count = 0

        @with_retry(FAST_CONFIG)
        async def raises_value_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await raises_value_error()

        assert call_count == 1  # No retries

    async def test_llm_failure_category(self) -> None:
        """FR-23.11: LLM failures get LLM_FAILURE category."""
        llm_config = RetryConfig(
            max_retries=1,
            initial_backoff=0.001,
            max_backoff=0.01,
            retryable_exceptions=(ConnectionError,),
            error_category=ErrorCategory.LLM_FAILURE,
            service_name="llm",
        )

        @with_retry(llm_config)
        async def llm_call() -> str:
            raise ConnectionError("model unreachable")

        with pytest.raises(AppError) as exc_info:
            await llm_call()

        assert exc_info.value.category == ErrorCategory.LLM_FAILURE
        assert exc_info.value.code == "LLM_UNAVAILABLE"

    async def test_passes_through_args_and_kwargs(self) -> None:
        @with_retry(FAST_CONFIG)
        async def add(a: int, b: int, extra: int = 0) -> int:
            return a + b + extra

        assert await add(1, 2, extra=3) == 6


# --- AC-23.4: db_retry / redis_retry convenience helpers ---


from tta.resilience.retry import (  # noqa: E402
    db_retry,
    redis_retry,
    with_db_retry,
    with_redis_retry,
)


class TestDbRetry:
    """AC-23.4: db_retry decorator and with_db_retry helper."""

    pytestmark = [pytest.mark.spec("AC-23.04")]

    async def test_db_retry_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        @db_retry
        async def fetch() -> str:
            nonlocal call_count
            call_count += 1
            return "row"

        assert await fetch() == "row"
        assert call_count == 1

    async def test_db_retry_retries_on_connection_error(self) -> None:
        call_count = 0

        @db_retry
        async def flaky_query() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient db error")
            return "ok"

        result = await flaky_query()
        assert result == "ok"
        assert call_count == 3

    async def test_db_retry_retries_on_oserror(self) -> None:
        """OSError (connection lost) is also retryable per FR-23.09."""
        call_count = 0

        @db_retry
        async def flaky_os() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("connection reset by peer")
            return "recovered"

        assert await flaky_os() == "recovered"
        assert call_count == 2

    async def test_db_retry_raises_app_error_after_exhaustion(self) -> None:
        """FR-23.11: SERVICE_UNAVAILABLE after all DB retries exhausted."""

        @db_retry
        async def always_fails() -> str:
            raise ConnectionError("pg down")

        with pytest.raises(AppError) as exc_info:
            await always_fails()

        err = exc_info.value
        assert err.category == ErrorCategory.SERVICE_UNAVAILABLE
        assert err.code == "POSTGRESQL_UNAVAILABLE"

    async def test_with_db_retry_helper_retries(self) -> None:
        """with_db_retry functional helper retries correctly."""
        call_count = 0

        async def db_call() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("transient")
            return "result"

        result = await with_db_retry(db_call)
        assert result == "result"
        assert call_count == 2

    async def test_with_db_retry_passes_args(self) -> None:
        async def add(a: int, b: int) -> int:
            return a + b

        assert await with_db_retry(add, 3, 4) == 7

    async def test_with_db_retry_raises_app_error_after_exhaustion(self) -> None:
        async def always_fails() -> str:
            raise ConnectionError("pg gone")

        with pytest.raises(AppError) as exc_info:
            await with_db_retry(always_fails)

        assert exc_info.value.category == ErrorCategory.SERVICE_UNAVAILABLE


class TestRedisRetry:
    """AC-23.4: redis_retry decorator and with_redis_retry helper."""

    pytestmark = [pytest.mark.spec("AC-23.04")]

    async def test_redis_retry_succeeds_on_first_attempt(self) -> None:
        call_count = 0

        @redis_retry
        async def ping() -> str:
            nonlocal call_count
            call_count += 1
            return "PONG"

        assert await ping() == "PONG"
        assert call_count == 1

    async def test_redis_retry_retries_on_connection_error(self) -> None:
        call_count = 0

        @redis_retry
        async def flaky_get() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("redis transient")
            return "value"

        result = await flaky_get()
        assert result == "value"
        assert call_count == 3

    async def test_redis_retry_raises_app_error_after_exhaustion(self) -> None:
        """FR-23.11: SERVICE_UNAVAILABLE after all Redis retries exhausted."""

        @redis_retry
        async def always_fails() -> str:
            raise ConnectionError("redis down")

        with pytest.raises(AppError) as exc_info:
            await always_fails()

        err = exc_info.value
        assert err.category == ErrorCategory.SERVICE_UNAVAILABLE
        assert err.code == "REDIS_UNAVAILABLE"

    async def test_with_redis_retry_helper_retries(self) -> None:
        call_count = 0

        async def redis_op() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("transient redis")
            return "ok"

        assert await with_redis_retry(redis_op) == "ok"
        assert call_count == 2

    async def test_with_redis_retry_passes_args(self) -> None:
        async def add(a: int, b: int) -> int:
            return a + b

        assert await with_redis_retry(add, 3, 4) == 7

    async def test_with_redis_retry_raises_app_error_after_exhaustion(self) -> None:
        async def always_fails() -> str:
            raise ConnectionError("redis gone")

        with pytest.raises(AppError) as exc_info:
            await with_redis_retry(always_fails)

        assert exc_info.value.category == ErrorCategory.SERVICE_UNAVAILABLE

    async def test_redis_retry_non_retryable_propagates(self) -> None:
        """Non-retryable exceptions are not caught."""
        call_count = 0

        @redis_retry
        async def bad_call() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("bad key")

        with pytest.raises(ValueError, match="bad key"):
            await bad_call()

        assert call_count == 1
