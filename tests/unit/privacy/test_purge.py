"""Tests for automated data purge (S17 FR-17.15, FR-27.17)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from tta.privacy.purge import (
    _collect_session_ids,
    _completed_retention_days,
    _delete_sessions,
    _soft_delete_retention_days,
    run_purge,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _make_factory(pg: AsyncMock):
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield pg

    return factory


class TestRetentionDays:
    """Verify retention day lookups match spec requirements."""

    def test_soft_delete_retention_is_3_days(self) -> None:
        assert _soft_delete_retention_days() == 3

    def test_completed_retention_is_90_days(self) -> None:
        assert _completed_retention_days() == 90


class TestCollectSessionIds:
    """_collect_session_ids queries both soft-deleted and completed paths."""

    @pytest.mark.anyio
    async def test_returns_both_soft_and_completed_ids(self) -> None:
        pg = AsyncMock()
        soft_rows = SimpleNamespace(fetchall=lambda: [("s1",), ("s2",)])
        completed_rows = SimpleNamespace(fetchall=lambda: [("c1",)])
        pg.execute = AsyncMock(side_effect=[soft_rows, completed_rows])

        now = datetime.now(UTC)
        ids = await _collect_session_ids(
            pg, now - timedelta(days=3), now - timedelta(days=90)
        )

        assert ids == ["s1", "s2", "c1"]
        assert pg.execute.call_count == 2

    @pytest.mark.anyio
    async def test_soft_delete_query_filters_deleted_at(self) -> None:
        pg = AsyncMock()
        empty = SimpleNamespace(fetchall=list)
        pg.execute = AsyncMock(side_effect=[empty, empty])

        now = datetime.now(UTC)
        await _collect_session_ids(pg, now, now)

        sql = str(pg.execute.call_args_list[0].args[0].text)
        assert "deleted_at IS NOT NULL" in sql
        assert "deleted_at < :cutoff" in sql

    @pytest.mark.anyio
    async def test_completed_query_filters_status_and_updated(self) -> None:
        pg = AsyncMock()
        empty = SimpleNamespace(fetchall=list)
        pg.execute = AsyncMock(side_effect=[empty, empty])

        now = datetime.now(UTC)
        await _collect_session_ids(pg, now, now)

        sql = str(pg.execute.call_args_list[1].args[0].text)
        assert "IN ('ended', 'completed', 'expired', 'abandoned')" in sql
        assert "deleted_at IS NULL" in sql
        assert "updated_at < :cutoff" in sql

    @pytest.mark.anyio
    async def test_empty_results(self) -> None:
        pg = AsyncMock()
        empty = SimpleNamespace(fetchall=list)
        pg.execute = AsyncMock(side_effect=[empty, empty])

        now = datetime.now(UTC)
        ids = await _collect_session_ids(pg, now, now)
        assert ids == []


class TestDeleteSessions:
    """_delete_sessions performs FK-safe cascade deletion."""

    @pytest.mark.anyio
    async def test_deletes_in_fk_safe_order(self) -> None:
        pg = AsyncMock()
        we_result = SimpleNamespace(rowcount=5)
        turn_result = SimpleNamespace(rowcount=10)
        session_result = SimpleNamespace(rowcount=2)
        pg.execute = AsyncMock(side_effect=[we_result, turn_result, session_result])
        pg.commit = AsyncMock()

        result = await _delete_sessions(pg, ["s1", "s2"])

        assert result == {
            "sessions": 2,
            "turns": 10,
            "world_events": 5,
        }
        # Verify order: world_events → turns → sessions
        calls = pg.execute.call_args_list
        assert "world_events" in str(calls[0].args[0].text)
        assert "turns" in str(calls[1].args[0].text)
        assert "game_sessions" in str(calls[2].args[0].text)
        pg.commit.assert_awaited_once()


class TestRunPurge:
    """run_purge orchestrates collection + deletion."""

    @pytest.mark.anyio
    async def test_noop_when_no_sessions(self) -> None:
        pg = AsyncMock()
        empty = SimpleNamespace(fetchall=list)
        pg.execute = AsyncMock(side_effect=[empty, empty])

        factory = _make_factory(pg)
        result = await run_purge(factory)

        assert result["sessions_purged"] == 0
        assert result["turns_purged"] == 0
        assert "cutoff_soft_delete" in result
        assert "cutoff_completed" in result

    @pytest.mark.anyio
    async def test_dry_run_counts_without_deleting(self) -> None:
        pg = AsyncMock()
        soft_rows = SimpleNamespace(fetchall=lambda: [("s1",)])
        completed_rows = SimpleNamespace(fetchall=list)
        we_count = SimpleNamespace(scalar=lambda: 3)
        turn_count = SimpleNamespace(scalar=lambda: 7)
        pg.execute = AsyncMock(
            side_effect=[soft_rows, completed_rows, we_count, turn_count]
        )

        factory = _make_factory(pg)
        result = await run_purge(factory, dry_run=True)

        assert result["dry_run"] is True
        assert result["sessions_purged"] == 1
        assert result["turns_purged"] == 7
        assert result["world_events_purged"] == 3
        # No commit should happen during dry run
        pg.commit.assert_not_awaited()

    @pytest.mark.anyio
    async def test_real_purge_deletes_and_commits(self) -> None:
        pg = AsyncMock()
        soft_rows = SimpleNamespace(fetchall=lambda: [("s1",), ("s2",)])
        completed_rows = SimpleNamespace(fetchall=lambda: [("c1",)])
        # After collect, _delete_sessions calls 3 executes + commit
        we_result = SimpleNamespace(rowcount=4)
        turn_result = SimpleNamespace(rowcount=8)
        session_result = SimpleNamespace(rowcount=3)
        pg.execute = AsyncMock(
            side_effect=[
                soft_rows,
                completed_rows,
                we_result,
                turn_result,
                session_result,
            ]
        )
        pg.commit = AsyncMock()

        factory = _make_factory(pg)
        result = await run_purge(factory)

        assert result["dry_run"] is False
        assert result["sessions_purged"] == 3
        assert result["turns_purged"] == 8
        assert result["world_events_purged"] == 4
        pg.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_cutoffs_use_correct_retention(self) -> None:
        pg = AsyncMock()
        empty = SimpleNamespace(fetchall=list)
        pg.execute = AsyncMock(side_effect=[empty, empty])

        factory = _make_factory(pg)
        result = await run_purge(factory)

        soft_cutoff = datetime.fromisoformat(result["cutoff_soft_delete"])
        completed_cutoff = datetime.fromisoformat(result["cutoff_completed"])

        now = datetime.now(UTC)
        soft_delta = now - soft_cutoff
        completed_delta = now - completed_cutoff

        # 3 days for soft-deleted (±1 minute tolerance)
        assert abs(soft_delta.total_seconds() - 3 * 86400) < 60
        # 90 days for completed (±1 minute tolerance)
        assert abs(completed_delta.total_seconds() - 90 * 86400) < 60
