"""Tests for Redis/SQL consistency checks (AC-12.04, EC-12.01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from tta.models.game import GameState
from tta.persistence.consistency import (
    audit_cache_consistency,
    check_session_consistency,
)

SID = UUID("00000000-0000-0000-0000-000000000001")


def _cached_payload(turn_number: int = 5) -> bytes:
    """Build a realistic Redis-cached GameState payload."""
    return GameState(session_id=SID, turn_number=turn_number).model_dump_json().encode()


def _sql_row(turn_count: int = 5) -> MagicMock:
    """Build a mock SQL row with turn_count."""
    row = MagicMock()
    row.turn_count = turn_count
    return row


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_pg() -> AsyncMock:
    return AsyncMock()


class TestCheckSessionConsistency:
    async def test_cache_miss_is_consistent(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """No cached state means no drift."""
        mock_redis.get.return_value = None

        with patch("tta.persistence.consistency.STATE_DRIFT_CHECKS") as checks:
            result = await check_session_consistency(mock_redis, mock_pg, SID)

        assert result is True
        checks.inc.assert_called_once()
        mock_pg.execute.assert_not_called()

    async def test_matching_state_is_consistent(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Cache turn_number matches SQL turn_count → consistent."""
        mock_redis.get.return_value = _cached_payload(turn_number=5)

        result_proxy = MagicMock()
        result_proxy.one_or_none.return_value = _sql_row(turn_count=5)
        mock_pg.execute.return_value = result_proxy

        with (
            patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"),
            patch("tta.persistence.consistency.STATE_DRIFT_DETECTED") as detected,
        ):
            result = await check_session_consistency(mock_redis, mock_pg, SID)

        assert result is True
        detected.labels.assert_not_called()

    async def test_phantom_session_detected(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Session in Redis but not SQL → phantom drift."""
        mock_redis.get.return_value = _cached_payload(turn_number=3)

        result_proxy = MagicMock()
        result_proxy.one_or_none.return_value = None
        mock_pg.execute.return_value = result_proxy

        with (
            patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"),
            patch("tta.persistence.consistency.STATE_DRIFT_DETECTED") as detected,
            patch("tta.persistence.consistency.delete_active_session") as evict,
        ):
            result = await check_session_consistency(mock_redis, mock_pg, SID)

        assert result is False
        detected.labels.assert_called_once_with(kind="phantom")
        evict.assert_awaited_once_with(mock_redis, SID)

    async def test_content_mismatch_detected(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Different turn numbers → mismatch drift, cache evicted."""
        mock_redis.get.return_value = _cached_payload(turn_number=10)

        result_proxy = MagicMock()
        result_proxy.one_or_none.return_value = _sql_row(turn_count=7)
        mock_pg.execute.return_value = result_proxy

        with (
            patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"),
            patch("tta.persistence.consistency.STATE_DRIFT_DETECTED") as detected,
            patch("tta.persistence.consistency.delete_active_session") as evict,
        ):
            result = await check_session_consistency(mock_redis, mock_pg, SID)

        assert result is False
        detected.labels.assert_called_once_with(kind="content_mismatch")
        evict.assert_awaited_once_with(mock_redis, SID)

    async def test_sql_null_turn_count_treated_as_zero(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """SQL NULL turn_count defaults to 0; matches cached turn 0."""
        mock_redis.get.return_value = _cached_payload(turn_number=0)

        row = MagicMock()
        row.turn_count = None
        result_proxy = MagicMock()
        result_proxy.one_or_none.return_value = row
        mock_pg.execute.return_value = result_proxy

        with (
            patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"),
            patch("tta.persistence.consistency.STATE_DRIFT_DETECTED") as detected,
        ):
            result = await check_session_consistency(mock_redis, mock_pg, SID)

        assert result is True
        detected.labels.assert_not_called()


class TestAuditCacheConsistency:
    async def test_empty_keyspace(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """No session keys → zero checks."""
        mock_redis.scan.return_value = (0, [])

        with patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"):
            result = await audit_cache_consistency(mock_redis, mock_pg)

        assert result == {
            "checked": 0,
            "drifted": 0,
            "errors": 0,
            "consistent": 0,
        }

    async def test_all_consistent(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """All cached sessions match SQL."""
        sid = uuid4()
        mock_redis.scan.return_value = (
            0,
            [f"tta:session:{sid}".encode()],
        )
        # check_session_consistency will call redis.get + pg.execute
        mock_redis.get.return_value = None  # cache miss = consistent

        with patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"):
            result = await audit_cache_consistency(mock_redis, mock_pg)

        assert result["checked"] == 1
        assert result["drifted"] == 0
        assert result["consistent"] == 1

    async def test_drift_counted(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Drifted sessions are counted."""
        sid = uuid4()
        mock_redis.scan.return_value = (
            0,
            [f"tta:session:{sid}".encode()],
        )
        mock_redis.get.return_value = _cached_payload(turn_number=1)

        result_proxy = MagicMock()
        result_proxy.one_or_none.return_value = None  # phantom
        mock_pg.execute.return_value = result_proxy

        with (
            patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"),
            patch("tta.persistence.consistency.STATE_DRIFT_DETECTED"),
            patch("tta.persistence.consistency.delete_active_session"),
        ):
            result = await audit_cache_consistency(mock_redis, mock_pg)

        assert result["checked"] == 1
        assert result["drifted"] == 1
        assert result["consistent"] == 0

    async def test_sample_limit_respected(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Stops after sample_limit sessions."""
        keys = [f"tta:session:{uuid4()}".encode() for _ in range(10)]
        mock_redis.scan.return_value = (0, keys)
        mock_redis.get.return_value = None  # all cache misses

        with patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"):
            result = await audit_cache_consistency(mock_redis, mock_pg, sample_limit=3)

        assert result["checked"] == 3

    async def test_invalid_key_skipped(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Non-UUID key suffixes are skipped."""
        mock_redis.scan.return_value = (
            0,
            [b"tta:session:not-a-uuid", f"tta:session:{uuid4()}".encode()],
        )
        mock_redis.get.return_value = None

        with patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"):
            result = await audit_cache_consistency(mock_redis, mock_pg)

        assert result["checked"] == 1  # only the valid UUID key

    async def test_exception_counted_as_error(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Exceptions during individual checks count as errors."""
        sid = uuid4()
        mock_redis.scan.return_value = (
            0,
            [f"tta:session:{sid}".encode()],
        )
        mock_redis.get.side_effect = RuntimeError("Redis gone")

        with patch("tta.persistence.consistency.STATE_DRIFT_CHECKS"):
            result = await audit_cache_consistency(mock_redis, mock_pg)

        assert result["errors"] == 1
        assert result["checked"] == 1
