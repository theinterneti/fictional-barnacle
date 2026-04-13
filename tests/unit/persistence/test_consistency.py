"""Tests for Redis/SQL consistency checks (AC-12.04, EC-12.01)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from tta.persistence.consistency import (
    _content_hash,
    audit_cache_consistency,
    check_session_consistency,
)

SID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_pg() -> AsyncMock:
    return AsyncMock()


class TestContentHash:
    def test_deterministic(self) -> None:
        assert _content_hash("hello") == _content_hash("hello")

    def test_bytes_and_str_match(self) -> None:
        assert _content_hash(b"abc") == _content_hash("abc")

    def test_different_input_different_hash(self) -> None:
        assert _content_hash("a") != _content_hash("b")


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
        """Cache matches SQL → consistent."""
        world_seed = json.dumps({"theme": "forest"}, sort_keys=True)
        mock_redis.get.return_value = world_seed.encode()

        row = MagicMock()
        row.world_seed = {"theme": "forest"}
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

    async def test_phantom_session_detected(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """Session in Redis but not SQL → phantom drift."""
        mock_redis.get.return_value = b"some_data"

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
        """Different content → mismatch drift, cache evicted."""
        mock_redis.get.return_value = b'{"theme": "cave"}'

        row = MagicMock()
        row.world_seed = {"theme": "forest"}
        result_proxy = MagicMock()
        result_proxy.one_or_none.return_value = row
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

    async def test_string_world_seed(
        self, mock_redis: AsyncMock, mock_pg: AsyncMock
    ) -> None:
        """world_seed stored as a string (not dict) still works."""
        mock_redis.get.return_value = b"plain-text-seed"

        row = MagicMock()
        row.world_seed = "plain-text-seed"
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
        mock_redis.get.return_value = b"stale"

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
