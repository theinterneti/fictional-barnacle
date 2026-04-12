"""Tests for Redis session cache — latency instrumentation + reconstruction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tta.models.game import GameState
from tta.persistence.redis_session import (
    delete_active_session,
    get_active_session,
    get_or_reconstruct_session,
    set_active_session,
)


def _make_state(**overrides: object) -> GameState:
    defaults: dict[str, object] = {
        "session_id": str(uuid4()),
        "turn_number": 0,
        "current_location_id": "start",
    }
    defaults.update(overrides)
    return GameState(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def mock_redis() -> AsyncMock:
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock()
    r.delete = AsyncMock()
    return r


# --- get_active_session --------------------------------------------------


class TestGetActiveSession:
    async def test_cache_hit(self, mock_redis: AsyncMock) -> None:
        state = _make_state()
        mock_redis.get.return_value = state.model_dump_json().encode()
        result = await get_active_session(mock_redis, uuid4())
        assert result is not None
        assert result.session_id == state.session_id

    async def test_cache_miss_returns_none(self, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = None
        result = await get_active_session(mock_redis, uuid4())
        assert result is None


# --- set_active_session ---------------------------------------------------


class TestSetActiveSession:
    async def test_sets_with_ttl(self, mock_redis: AsyncMock) -> None:
        state = _make_state()
        sid = uuid4()
        await set_active_session(mock_redis, sid, state, ttl=600)
        mock_redis.set.assert_awaited_once()
        _, kwargs = mock_redis.set.call_args
        assert kwargs["ex"] == 600

    async def test_default_ttl(self, mock_redis: AsyncMock) -> None:
        await set_active_session(mock_redis, uuid4(), _make_state())
        _, kwargs = mock_redis.set.call_args
        assert kwargs["ex"] == 3600


# --- delete_active_session ------------------------------------------------


class TestDeleteActiveSession:
    async def test_deletes_key(self, mock_redis: AsyncMock) -> None:
        sid = uuid4()
        await delete_active_session(mock_redis, sid)
        mock_redis.delete.assert_awaited_once()


# --- get_or_reconstruct_session -------------------------------------------


class TestGetOrReconstructSession:
    async def test_returns_cached_state(self, mock_redis: AsyncMock) -> None:
        state = _make_state()
        mock_redis.get.return_value = state.model_dump_json().encode()
        result = await get_or_reconstruct_session(mock_redis, uuid4())
        assert result is not None
        assert result.session_id == state.session_id

    async def test_returns_none_without_loader(self, mock_redis: AsyncMock) -> None:
        result = await get_or_reconstruct_session(mock_redis, uuid4())
        assert result is None

    async def test_reconstructs_from_sql(self, mock_redis: AsyncMock) -> None:
        state = _make_state()
        loader = AsyncMock(return_value=state)
        sid = uuid4()

        with patch(
            "tta.persistence.redis_session.CACHE_RECONSTRUCTION_TOTAL"
        ) as mock_counter:
            result = await get_or_reconstruct_session(
                mock_redis, sid, load_from_sql=loader
            )

        assert result is not None
        assert result.session_id == state.session_id
        loader.assert_awaited_once_with(sid)
        mock_counter.inc.assert_called_once()
        # Should re-warm cache
        mock_redis.set.assert_awaited_once()

    async def test_sql_returns_none(self, mock_redis: AsyncMock) -> None:
        loader = AsyncMock(return_value=None)
        result = await get_or_reconstruct_session(
            mock_redis, uuid4(), load_from_sql=loader
        )
        assert result is None
        # Should NOT re-warm cache if SQL returned nothing
        mock_redis.set.assert_not_awaited()
