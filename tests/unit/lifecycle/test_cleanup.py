"""Tests for game-session lifecycle transitions (S11 FR-11.41–45)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tta.lifecycle.cleanup import run_lifecycle_pass


def _make_pg(
    *,
    abandon_rowcount: int = 0,
    expire_rowcount: int = 0,
    idle_rowcount: int = 0,
    anon_rowcount: int = 0,
) -> AsyncMock:
    """Build a mock PG session that returns the given rowcounts."""
    pg = AsyncMock()
    abandon_result = SimpleNamespace(rowcount=abandon_rowcount)
    expire_result = SimpleNamespace(rowcount=expire_rowcount)
    idle_result = SimpleNamespace(rowcount=idle_rowcount)
    anon_result = SimpleNamespace(rowcount=anon_rowcount)
    pg.execute = AsyncMock(
        side_effect=[abandon_result, expire_result, idle_result, anon_result]
    )
    pg.commit = AsyncMock()
    return pg


def _make_factory(pg: AsyncMock):  # noqa: ANN201
    """Wrap a mock PG session in an async context-manager factory."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncMock]:
        yield pg

    return factory


@pytest.mark.spec("AC-11.08")
class TestAbandonRule:
    """created/active + 0 turns + >24h → abandoned."""

    @pytest.mark.anyio
    async def test_abandons_stale_active_games(self) -> None:
        pg = _make_pg(abandon_rowcount=3)
        factory = _make_factory(pg)

        result = await run_lifecycle_pass(factory)

        assert result["abandoned"] == 3
        abandon_call = pg.execute.call_args_list[0]
        sql_text = str(abandon_call.args[0].text)
        assert "IN ('created', 'active')" in sql_text
        assert "turn_count = 0" in sql_text
        assert "deleted_at IS NULL" in sql_text
        pg.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_no_abandoned_means_no_commit(self) -> None:
        pg = _make_pg(abandon_rowcount=0, expire_rowcount=0)
        factory = _make_factory(pg)

        result = await run_lifecycle_pass(factory)

        assert result["abandoned"] == 0
        assert result["expired"] == 0
        assert result["idle_paused"] == 0
        pg.commit.assert_not_awaited()

    @pytest.mark.anyio
    async def test_abandon_cutoff_is_24h(self) -> None:
        pg = _make_pg(abandon_rowcount=1)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, abandon_hours=24)

        params = pg.execute.call_args_list[0].args[1]
        cutoff = params["cutoff"]
        expected = datetime.now(UTC) - timedelta(hours=24)
        assert abs((cutoff - expected).total_seconds()) < 5

    @pytest.mark.anyio
    async def test_abandon_not_triggered_at_exactly_24h(self) -> None:
        """AC-11.08: Game created exactly 24h ago should NOT be abandoned.

        Spec says "more than 24 hours" → strict `<` excludes games at boundary.
        """
        pg = _make_pg(abandon_rowcount=0)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, abandon_hours=24)

        abandon_call = pg.execute.call_args_list[0]
        sql_text = str(abandon_call.args[0].text)
        assert "< :cutoff" in sql_text and "<=" not in sql_text, (
            "AC-11.08: SQL must use strict < (not <=) so games "
            "exactly at 24h boundary are not caught"
        )


@pytest.mark.spec("AC-11.06")
class TestExpireRule:
    """paused + last_played > 30 days → expired."""

    @pytest.mark.anyio
    async def test_expires_stale_paused_games(self) -> None:
        pg = _make_pg(expire_rowcount=5)
        factory = _make_factory(pg)

        result = await run_lifecycle_pass(factory)

        assert result["expired"] == 5
        expire_call = pg.execute.call_args_list[1]
        sql_text = str(expire_call.args[0].text)
        assert "status = 'paused'" in sql_text
        assert "paused_at" in sql_text
        assert "deleted_at IS NULL" in sql_text
        pg.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_expire_cutoff_is_30_days(self) -> None:
        pg = _make_pg(expire_rowcount=1)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, expire_days=30)

        params = pg.execute.call_args_list[1].args[1]
        cutoff = params["cutoff"]
        expected = datetime.now(UTC) - timedelta(days=30)
        assert abs((cutoff - expected).total_seconds()) < 5

    @pytest.mark.anyio
    async def test_expire_not_triggered_at_exactly_30_days(self) -> None:
        """AC-11.06: Game paused exactly 30 days ago should NOT be expired.

        Spec says "more than 30 days" → strict `<` excludes games at boundary.
        """
        pg = _make_pg(expire_rowcount=0)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, expire_days=30)

        expire_call = pg.execute.call_args_list[1]
        sql_text = str(expire_call.args[0].text)
        assert "< :cutoff" in sql_text and "<=" not in sql_text, (
            "AC-11.06: SQL must use strict < (not <=) so games "
            "exactly at 30-day boundary are not caught"
        )


class TestMixedTransitions:
    """Both rules fire in a single pass."""

    @pytest.mark.anyio
    async def test_both_rules_apply(self) -> None:
        pg = _make_pg(abandon_rowcount=2, expire_rowcount=3)
        factory = _make_factory(pg)

        result = await run_lifecycle_pass(factory)

        assert result["abandoned"] == 2
        assert result["expired"] == 3
        pg.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_custom_thresholds(self) -> None:
        pg = _make_pg(abandon_rowcount=1, expire_rowcount=1)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, abandon_hours=48, expire_days=60)

        abandon_params = pg.execute.call_args_list[0].args[1]
        expire_params = pg.execute.call_args_list[1].args[1]
        now = datetime.now(UTC)
        assert (
            abs(
                (abandon_params["cutoff"] - (now - timedelta(hours=48))).total_seconds()
            )
            < 5
        )
        assert (
            abs((expire_params["cutoff"] - (now - timedelta(days=60))).total_seconds())
            < 5
        )


class TestErrorHandling:
    """Lifecycle pass handles DB errors gracefully."""

    @pytest.mark.anyio
    async def test_db_error_propagates(self) -> None:
        pg = AsyncMock()
        pg.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

        @asynccontextmanager
        async def factory() -> AsyncIterator[AsyncMock]:
            yield pg

        with pytest.raises(RuntimeError, match="connection lost"):
            await run_lifecycle_pass(factory)


class TestIdleTimeoutRule:
    """active + turn_count > 0 + idle > 30 min → paused (AC-1.7)."""

    @pytest.mark.anyio
    async def test_pauses_idle_active_games(self) -> None:
        pg = _make_pg(idle_rowcount=4)
        factory = _make_factory(pg)

        result = await run_lifecycle_pass(factory)

        assert result["idle_paused"] == 4
        idle_call = pg.execute.call_args_list[2]
        sql_text = str(idle_call.args[0].text)
        assert "status = 'active'" in sql_text
        assert "turn_count > 0" in sql_text
        assert "deleted_at IS NULL" in sql_text
        pg.commit.assert_awaited_once()

    @pytest.mark.anyio
    async def test_idle_cutoff_is_configurable(self) -> None:
        pg = _make_pg(idle_rowcount=1)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, idle_timeout_minutes=45)

        params = pg.execute.call_args_list[2].args[1]
        cutoff = params["cutoff"]
        expected = datetime.now(UTC) - timedelta(minutes=45)
        assert abs((cutoff - expected).total_seconds()) < 5

    @pytest.mark.anyio
    async def test_zero_turn_games_excluded_from_idle(self) -> None:
        """Games with turn_count=0 must NOT be paused (stay eligible for abandon)."""
        pg = _make_pg(idle_rowcount=0)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory)

        idle_call = pg.execute.call_args_list[2]
        sql_text = str(idle_call.args[0].text)
        assert "turn_count > 0" in sql_text


@pytest.mark.spec("AC-11.05")
class TestAC1105PausedGameNotExpiredBefore30Days:
    """Paused game within 30 days MUST NOT be expired."""

    @pytest.mark.anyio
    async def test_paused_game_cutoff_is_exactly_30_days(self) -> None:
        """AC-11.05: Verify cutoff is 30 days, not 29 or 31."""
        pg = _make_pg(expire_rowcount=0)
        factory = _make_factory(pg)

        await run_lifecycle_pass(factory, expire_days=30)

        expire_call = pg.execute.call_args_list[1]
        params = expire_call.args[1]
        cutoff = params["cutoff"]

        now = datetime.now(UTC)
        expected_cutoff = now - timedelta(days=30)
        assert abs((cutoff - expected_cutoff).total_seconds()) < 5

        sql_text = str(expire_call.args[0].text)
        assert "< :cutoff" in sql_text and "paused_at" in sql_text, (
            "AC-11.05: SQL should use strict < on paused_at to exclude games "
            "exactly at 30-day boundary"
        )
