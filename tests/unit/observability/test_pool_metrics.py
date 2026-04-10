"""Tests for the pool-metrics periodic sampler."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from tta.observability.pool_metrics import _sample_once, start_pool_metrics_sampler


class _FakePool:
    """Minimal stub for SQLAlchemy pool stats."""

    def size(self) -> int:
        return 5

    def checkedout(self) -> int:
        return 2

    def overflow(self) -> int:
        return 0


class _FakeRedisPool:
    """Minimal stub for redis-py ConnectionPool."""

    _created_connections = 4
    _available_connections = [1, 2]  # 2 idle → 2 active


@pytest.fixture
def fake_app() -> MagicMock:
    app = MagicMock()
    engine = MagicMock()
    engine.pool = _FakePool()
    app.state.pg_engine = engine

    redis = MagicMock()
    redis.connection_pool = _FakeRedisPool()
    app.state.redis = redis

    app.state.neo4j_driver = None
    return app


class TestSampleOnce:
    @pytest.mark.asyncio
    async def test_sets_pg_gauges(self, fake_app: MagicMock) -> None:
        with (
            patch("tta.observability.pool_metrics.PG_POOL_SIZE") as pg_size,
            patch("tta.observability.pool_metrics.PG_POOL_CHECKED_OUT") as pg_co,
            patch("tta.observability.pool_metrics.PG_POOL_OVERFLOW") as pg_of,
        ):
            await _sample_once(fake_app)
            pg_size.set.assert_called_once_with(5)
            pg_co.set.assert_called_once_with(2)
            pg_of.set.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_sets_redis_gauge(self, fake_app: MagicMock) -> None:
        with patch("tta.observability.pool_metrics.REDIS_POOL_ACTIVE") as redis_active:
            await _sample_once(fake_app)
            redis_active.set.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_no_engine_skips_pg(self) -> None:
        app = MagicMock()
        app.state.pg_engine = None
        app.state.redis = None
        app.state.neo4j_driver = None
        with patch("tta.observability.pool_metrics.PG_POOL_SIZE") as pg_size:
            await _sample_once(app)
            pg_size.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_pool_skips(self) -> None:
        app = MagicMock()
        app.state.pg_engine = None
        app.state.neo4j_driver = None
        redis = MagicMock(spec=[])  # no connection_pool attr
        app.state.redis = redis
        with patch("tta.observability.pool_metrics.REDIS_POOL_ACTIVE") as redis_active:
            await _sample_once(app)
            redis_active.set.assert_not_called()


class TestSamplerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_cancel(self, fake_app: MagicMock) -> None:
        task = start_pool_metrics_sampler(fake_app, interval=0.05)
        assert not task.done()
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
