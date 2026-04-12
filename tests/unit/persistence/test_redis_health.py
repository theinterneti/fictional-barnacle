"""Tests for Redis TTL compliance monitoring (AC-12.12)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tta.persistence.redis_health import audit_ttl_compliance


@pytest.fixture
def mock_redis() -> AsyncMock:
    return AsyncMock()


class TestAuditTtlCompliance:
    async def test_all_keys_have_ttl(self, mock_redis: AsyncMock) -> None:
        """No violations when every key has a TTL."""
        mock_redis.scan.return_value = (
            0,
            [b"tta:session:abc", b"tta:turn_result:xyz"],
        )
        pipe = AsyncMock()
        pipe.ttl = AsyncMock()
        pipe.execute = AsyncMock(return_value=[3600, 300])
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline = MagicMock(return_value=pipe)

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL") as gauge:
            result = await audit_ttl_compliance(mock_redis)

        assert result == {}
        gauge.set.assert_called_once_with(0)

    async def test_key_without_ttl_detected(self, mock_redis: AsyncMock) -> None:
        """Keys returning TTL=-1 are reported as violations."""
        mock_redis.scan.return_value = (
            0,
            [b"tta:session:abc", b"tta:session:def"],
        )
        pipe = AsyncMock()
        pipe.ttl = AsyncMock()
        pipe.execute = AsyncMock(return_value=[3600, -1])
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline = MagicMock(return_value=pipe)

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL") as gauge:
            result = await audit_ttl_compliance(mock_redis)

        assert result == {"tta:session": 1}
        gauge.set.assert_called_once_with(1)

    async def test_empty_keyspace(self, mock_redis: AsyncMock) -> None:
        """No keys at all is fine — zero violations."""
        mock_redis.scan.return_value = (0, [])

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL") as gauge:
            result = await audit_ttl_compliance(mock_redis)

        assert result == {}
        gauge.set.assert_called_once_with(0)

    async def test_multi_batch_scan(self, mock_redis: AsyncMock) -> None:
        """Handles paginated SCAN results across multiple batches."""
        mock_redis.scan.side_effect = [
            (42, [b"tta:session:a"]),  # batch 1, cursor 42
            (0, [b"tta:turn_result:b"]),  # batch 2, cursor 0 → done
        ]
        pipe = AsyncMock()
        pipe.ttl = AsyncMock()
        pipe.execute = AsyncMock(side_effect=[[3600], [-1]])
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline = MagicMock(return_value=pipe)

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL") as gauge:
            result = await audit_ttl_compliance(mock_redis)

        assert result == {"tta:turn_result": 1}
        gauge.set.assert_called_once_with(1)
        assert mock_redis.scan.call_count == 2
