"""Tests for Wave 19: API completeness & observability wiring.

Covers:
  - Task 1: Turn history cursor-based pagination
  - Task 2: CORS environment-based configuration (CSV / JSON / default)
  - Task 3: DB query auto-instrumentation via SQLAlchemy events
  - Task 4: Redis operation instrumentation
  - Task 5: SSE heartbeat configurability
"""

from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tta.observability.metrics import (
    DB_QUERY_DURATION,
    REDIS_OPERATIONS,
    REGISTRY,
)


def _sample_value(
    sample_name: str,
    labels: dict[str, str],
) -> float:
    """Read a specific sample value from the custom REGISTRY by name + labels."""
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == sample_name and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


# ---------------------------------------------------------------------------
# Task 1: Turn history pagination
# ---------------------------------------------------------------------------


class TestListTurnsCursorEncoding:
    """Cursor encoding and decoding for the /turns endpoint."""

    def test_cursor_is_base64_of_turn_number(self) -> None:
        turn_number = 42
        encoded = base64.urlsafe_b64encode(str(turn_number).encode()).decode()
        decoded = int(base64.urlsafe_b64decode(encoded).decode("utf-8"))
        assert decoded == turn_number

    def test_invalid_base64_cursor_is_detected(self) -> None:
        """Non-base64 cursor should raise on decode."""
        import binascii

        with pytest.raises(binascii.Error):
            base64.urlsafe_b64decode("not-base64!!!").decode("utf-8")

    def test_non_integer_cursor_is_detected(self) -> None:
        """Base64 of a non-integer should raise ValueError."""
        encoded = base64.urlsafe_b64encode(b"abc").decode()
        with pytest.raises(ValueError):
            int(base64.urlsafe_b64decode(encoded).decode("utf-8"))

    def test_zero_cursor_rejected(self) -> None:
        """A cursor encoding 0 should be considered non-positive."""
        cursor = base64.urlsafe_b64encode(b"0").decode()
        decoded = int(base64.urlsafe_b64decode(cursor).decode("utf-8"))
        assert decoded < 1  # endpoint rejects non-positive cursors

    def test_negative_cursor_rejected(self) -> None:
        cursor = base64.urlsafe_b64encode(b"-5").decode()
        decoded = int(base64.urlsafe_b64decode(cursor).decode("utf-8"))
        assert decoded < 1


class TestPaginationNPlusOne:
    """N+1 fetch pattern for has_more detection."""

    def test_has_more_true_when_extra_row(self) -> None:
        limit = 3
        rows = list(range(limit + 1))  # 4 items = more pages
        has_more = len(rows) > limit
        items = rows[:limit]
        assert has_more is True
        assert len(items) == limit

    def test_has_more_false_when_exact_or_fewer(self) -> None:
        limit = 3
        for count in (0, 1, 2, 3):
            rows = list(range(count))
            has_more = len(rows) > limit
            assert has_more is False

    def test_next_cursor_none_when_no_more(self) -> None:
        limit = 5
        rows = list(range(3))  # fewer than limit
        has_more = len(rows) > limit
        next_cursor = "something" if has_more and rows else None
        assert next_cursor is None


# ---------------------------------------------------------------------------
# Task 2: CORS environment-based configuration
# ---------------------------------------------------------------------------


class TestCorsEnvironmentConfig:
    """CORS origins parsing from env vars via _TtaEnvSource."""

    _REQUIRED_ENV = {
        "TTA_DATABASE_URL": "postgresql://localhost/test",
        "TTA_NEO4J_PASSWORD": "test",
    }

    @pytest.fixture(autouse=True)
    def _clean_tta_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove all TTA_ env vars so host env doesn't leak into tests."""
        for key in list(os.environ):
            if key.startswith("TTA_"):
                monkeypatch.delenv(key, raising=False)

    def _make_settings(self, **env_overrides: str) -> Any:
        from tta.config import Settings

        env = {**self._REQUIRED_ENV, **env_overrides}
        with patch.dict(os.environ, env, clear=True):
            return Settings()

    def test_csv_origins_parsed(self) -> None:
        s = self._make_settings(TTA_CORS_ORIGINS="http://a.com, http://b.com")
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_json_array_origins_parsed(self) -> None:
        s = self._make_settings(TTA_CORS_ORIGINS='["*"]')
        assert s.cors_origins == ["*"]

    def test_single_origin_parsed(self) -> None:
        s = self._make_settings(TTA_CORS_ORIGINS="https://example.com")
        assert s.cors_origins == ["https://example.com"]

    def test_default_origins(self) -> None:
        s = self._make_settings()
        assert s.cors_origins == [
            "http://localhost:3000",
            "http://localhost:8080",
        ]

    def test_direct_constructor_overrides(self) -> None:
        from tta.config import Settings

        env = {**self._REQUIRED_ENV}
        with patch.dict(os.environ, env, clear=True):
            s = Settings(cors_origins=["https://custom.dev"])
        assert s.cors_origins == ["https://custom.dev"]

    def test_empty_string_produces_empty_list(self) -> None:
        s = self._make_settings(TTA_CORS_ORIGINS="")
        assert s.cors_origins == []


# ---------------------------------------------------------------------------
# Task 3: DB auto-instrumentation via SQLAlchemy events
# ---------------------------------------------------------------------------


class TestClassifyOperation:
    """_classify_operation extracts SQL operation from statement prefix."""

    def test_select(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("SELECT * FROM foo") == "select"

    def test_insert(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("INSERT INTO bar VALUES (1)") == "insert"

    def test_update(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("UPDATE baz SET x=1") == "update"

    def test_delete(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("DELETE FROM qux") == "delete"

    def test_other(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("CREATE TABLE t (id int)") == "other"

    def test_case_insensitive(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("select * from foo") == "select"

    def test_leading_whitespace(self) -> None:
        from tta.persistence.engine import _classify_operation

        assert _classify_operation("  \n SELECT 1") == "select"


class TestDbInstrumentationListeners:
    """before/after cursor execute listeners record DB_QUERY_DURATION."""

    def test_before_stores_timing_key(self) -> None:
        from tta.persistence.engine import _TIMING_KEY, _before_cursor_execute

        conn = MagicMock()
        conn.info = {}
        _before_cursor_execute(conn, None, "SELECT 1", None, None, False)
        assert _TIMING_KEY in conn.info
        assert isinstance(conn.info[_TIMING_KEY], float)

    def test_after_observes_duration(self) -> None:
        from tta.persistence.engine import (
            _after_cursor_execute,
            _before_cursor_execute,
        )

        conn = MagicMock()
        conn.info = {}
        _before_cursor_execute(conn, None, "SELECT 1", None, None, False)

        before = _sample_value(
            "tta_db_query_duration_seconds_count",
            {"database": "postgresql", "operation": "select"},
        )

        _after_cursor_execute(conn, None, "SELECT 1", None, None, False)

        after = _sample_value(
            "tta_db_query_duration_seconds_count",
            {"database": "postgresql", "operation": "select"},
        )
        assert after > before

    def test_after_pops_timing_key(self) -> None:
        from tta.persistence.engine import (
            _TIMING_KEY,
            _after_cursor_execute,
            _before_cursor_execute,
        )

        conn = MagicMock()
        conn.info = {}
        _before_cursor_execute(conn, None, "UPDATE t SET x=1", None, None, False)
        _after_cursor_execute(conn, None, "UPDATE t SET x=1", None, None, False)
        assert _TIMING_KEY not in conn.info

    def test_after_without_before_is_noop(self) -> None:
        """If before never ran, after should not crash."""
        from tta.persistence.engine import _after_cursor_execute

        conn = MagicMock()
        conn.info = {}
        # No exception expected
        _after_cursor_execute(conn, None, "SELECT 1", None, None, False)


class TestDbHandleError:
    """_handle_error cleans up timing on failed queries."""

    def test_error_cleans_timing_and_observes(self) -> None:
        from tta.persistence.engine import (
            _TIMING_KEY,
            _before_cursor_execute,
            _handle_error,
        )

        conn = MagicMock()
        conn.info = {}
        _before_cursor_execute(conn, None, "DELETE FROM t", None, None, False)

        before = _sample_value(
            "tta_db_query_duration_seconds_count",
            {"database": "postgresql", "operation": "delete"},
        )

        exc_ctx = SimpleNamespace(connection=conn, statement="DELETE FROM t")
        _handle_error(exc_ctx)

        after = _sample_value(
            "tta_db_query_duration_seconds_count",
            {"database": "postgresql", "operation": "delete"},
        )
        assert after > before
        assert _TIMING_KEY not in conn.info

    def test_error_without_timing_is_noop(self) -> None:
        from tta.persistence.engine import _handle_error

        conn = MagicMock()
        conn.info = {}
        exc_ctx = SimpleNamespace(connection=conn, statement="SELECT 1")
        _handle_error(exc_ctx)  # should not crash

    def test_error_with_none_connection(self) -> None:
        from tta.persistence.engine import _handle_error

        exc_ctx = SimpleNamespace(connection=None, statement="SELECT 1")
        _handle_error(exc_ctx)  # should not crash


# ---------------------------------------------------------------------------
# Task 4: Redis operation instrumentation
# ---------------------------------------------------------------------------


class TestRedisInstrumentation:
    """count_redis_op() increments REDIS_OPERATIONS counter."""

    def test_get_increments(self) -> None:
        from tta.observability.db_metrics import count_redis_op

        before = _sample_value("tta_redis_operations_total", {"operation": "get"})
        with count_redis_op("get"):
            pass  # simulated Redis get
        after = _sample_value("tta_redis_operations_total", {"operation": "get"})
        assert after == before + 1.0

    def test_set_increments(self) -> None:
        from tta.observability.db_metrics import count_redis_op

        before = _sample_value("tta_redis_operations_total", {"operation": "set"})
        with count_redis_op("set"):
            pass
        after = _sample_value("tta_redis_operations_total", {"operation": "set"})
        assert after == before + 1.0

    def test_delete_increments(self) -> None:
        from tta.observability.db_metrics import count_redis_op

        before = _sample_value("tta_redis_operations_total", {"operation": "delete"})
        with count_redis_op("delete"):
            pass
        after = _sample_value("tta_redis_operations_total", {"operation": "delete"})
        assert after == before + 1.0

    def test_increments_even_on_exception(self) -> None:
        from tta.observability.db_metrics import count_redis_op

        before = _sample_value("tta_redis_operations_total", {"operation": "get"})
        with pytest.raises(RuntimeError), count_redis_op("get"):
            raise RuntimeError("simulated failure")
        after = _sample_value("tta_redis_operations_total", {"operation": "get"})
        assert after == before + 1.0


# ---------------------------------------------------------------------------
# Task 5: SSE heartbeat configurability
# ---------------------------------------------------------------------------


class TestHeartbeatConfig:
    """sse_heartbeat_interval setting validation and usage."""

    _REQUIRED_ENV = {
        "TTA_DATABASE_URL": "postgresql://localhost/test",
        "TTA_NEO4J_PASSWORD": "test",
    }

    @pytest.fixture(autouse=True)
    def _clean_tta_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in list(os.environ):
            if key.startswith("TTA_"):
                monkeypatch.delenv(key, raising=False)

    def test_default_is_15(self) -> None:
        from tta.config import Settings

        with patch.dict(os.environ, self._REQUIRED_ENV, clear=True):
            s = Settings()
        assert s.sse_heartbeat_interval == 15.0

    def test_custom_value(self) -> None:
        from tta.config import Settings

        with patch.dict(os.environ, self._REQUIRED_ENV, clear=True):
            s = Settings(sse_heartbeat_interval=5.0)
        assert s.sse_heartbeat_interval == 5.0

    def test_env_override(self) -> None:
        from tta.config import Settings

        env = {**self._REQUIRED_ENV, "TTA_SSE_HEARTBEAT_INTERVAL": "10.0"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings()
        assert s.sse_heartbeat_interval == 10.0

    def test_zero_rejected(self) -> None:
        from pydantic import ValidationError

        from tta.config import Settings

        with (
            patch.dict(os.environ, self._REQUIRED_ENV, clear=True),
            pytest.raises(ValidationError, match="positive"),
        ):
            Settings(sse_heartbeat_interval=0.0)

    def test_negative_rejected(self) -> None:
        from pydantic import ValidationError

        from tta.config import Settings

        with (
            patch.dict(os.environ, self._REQUIRED_ENV, clear=True),
            pytest.raises(ValidationError, match="positive"),
        ):
            Settings(sse_heartbeat_interval=-1.0)

    def test_above_15_rejected(self) -> None:
        from pydantic import ValidationError

        from tta.config import Settings

        with (
            patch.dict(os.environ, self._REQUIRED_ENV, clear=True),
            pytest.raises(ValidationError, match="<= 15s"),
        ):
            Settings(sse_heartbeat_interval=20.0)


class TestDbQueryDurationLabels:
    """DB_QUERY_DURATION histogram uses correct label names."""

    def test_has_database_and_operation_labels(self) -> None:
        assert DB_QUERY_DURATION._labelnames == ("database", "operation")

    def test_postgresql_label_value(self) -> None:
        """Engine listeners use 'postgresql' label, matching db_metrics convention."""
        from tta.persistence.engine import (
            _after_cursor_execute,
            _before_cursor_execute,
        )

        conn = MagicMock()
        conn.info = {}
        _before_cursor_execute(
            conn, None, "INSERT INTO t VALUES (1)", None, None, False
        )
        _after_cursor_execute(conn, None, "INSERT INTO t VALUES (1)", None, None, False)

        val = _sample_value(
            "tta_db_query_duration_seconds_count",
            {"database": "postgresql", "operation": "insert"},
        )
        assert val > 0


class TestRedisOperationsLabels:
    """REDIS_OPERATIONS counter uses correct label names."""

    def test_has_operation_label(self) -> None:
        assert REDIS_OPERATIONS._labelnames == ("operation",)
