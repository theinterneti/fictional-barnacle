"""Tests for GDPR endpoints (S17 §3 FR-17.6, FR-17.9, FR-17.10)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg, get_redis
from tta.config import Settings
from tta.models.player import Player

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="TestPlayer", created_at=_NOW)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


@pytest.fixture()
def pg_mock() -> AsyncMock:
    mock = AsyncMock()
    # SQLAlchemy Result.fetchall() is synchronous even in async mode.
    # Default return gives empty rows so the 6th execute (session ID fetch) works.
    result = MagicMock()
    result.fetchall.return_value = []
    mock.execute.return_value = result
    return mock


@pytest.fixture()
def redis_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def world_service_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def authed_client(
    pg_mock: AsyncMock,
    redis_mock: AsyncMock,
    world_service_mock: AsyncMock,
) -> TestClient:
    app = create_app(_settings())
    app.dependency_overrides[get_pg] = lambda: pg_mock
    app.dependency_overrides[get_current_player] = lambda: _PLAYER
    app.dependency_overrides[get_redis] = lambda: redis_mock
    app.state.world_service = world_service_mock
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def anon_client() -> TestClient:
    app = create_app(_settings())
    app.dependency_overrides[get_pg] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    return TestClient(app, raise_server_exceptions=False)


class TestDataExportEndpoint:
    """GET /api/v1/players/me/data-export → 202."""

    def test_returns_202_accepted(self, authed_client: TestClient) -> None:
        resp = authed_client.get("/api/v1/players/me/data-export")
        assert resp.status_code == 202
        body = resp.json()
        assert "data" in body

    def test_unauthenticated_rejected(self, anon_client: TestClient) -> None:
        resp = anon_client.get("/api/v1/players/me/data-export")
        assert resp.status_code == 401


class TestAccountDeletionEndpoint:
    """DELETE /api/v1/players/me → 202 with real PII erasure."""

    def test_returns_202_accepted(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        resp = authed_client.delete("/api/v1/players/me")
        assert resp.status_code == 202
        body = resp.json()
        assert body["data"]["status"] == "accepted"
        assert body["data"]["player_id"] == str(_PLAYER_ID)

    def test_unauthenticated_rejected(self, anon_client: TestClient) -> None:
        resp = anon_client.delete("/api/v1/players/me")
        assert resp.status_code == 401

    def test_tombstones_player(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """Player status set to pending_deletion, handle anonymised."""
        authed_client.delete("/api/v1/players/me")

        first_call = pg_mock.execute.call_args_list[0]
        sql_text = str(first_call.args[0].text)
        params = first_call.args[1]

        assert "status = 'pending_deletion'" in sql_text
        assert "deletion_requested_at" in sql_text
        assert params["tombstone"] == f"deleted-{_PLAYER_ID}"
        assert params["pid"] == _PLAYER_ID

    def test_ends_active_game_sessions(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """All created/active/paused game sessions ended."""
        authed_client.delete("/api/v1/players/me")

        second_call = pg_mock.execute.call_args_list[1]
        sql_text = str(second_call.args[0].text)
        params = second_call.args[1]

        assert "game_sessions" in sql_text
        assert "status = 'ended'" in sql_text
        assert "('created', 'active', 'paused')" in sql_text
        assert params["pid"] == _PLAYER_ID

    def test_scrubs_turn_pii(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """Turn player_input tombstoned, narrative_output NULLed."""
        authed_client.delete("/api/v1/players/me")

        third_call = pg_mock.execute.call_args_list[2]
        sql_text = str(third_call.args[0].text)

        assert "player_input = '[redacted]'" in sql_text
        assert "narrative_output = NULL" in sql_text
        assert "turns" in sql_text

    def test_scrubs_game_session_pii(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """Game session world_seed tombstoned (NOT NULL col), summary NULLed."""
        authed_client.delete("/api/v1/players/me")

        fourth_call = pg_mock.execute.call_args_list[3]
        sql_text = str(fourth_call.args[0].text)

        assert "world_seed = '{}'::jsonb" in sql_text
        assert "summary = NULL" in sql_text

    def test_deletes_session_tokens(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """All player_sessions rows deleted."""
        authed_client.delete("/api/v1/players/me")

        fifth_call = pg_mock.execute.call_args_list[4]
        sql_text = str(fifth_call.args[0].text)

        assert "DELETE FROM player_sessions" in sql_text

    def test_commits_transaction(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """All operations committed in a single transaction."""
        authed_client.delete("/api/v1/players/me")

        pg_mock.commit.assert_awaited_once()
        assert pg_mock.execute.call_count == 6


class TestMultiStoreCleanup:
    """GDPR erasure cleans Redis + Neo4j (AC-12.03)."""

    @staticmethod
    def _configure_session_ids(
        pg_mock: AsyncMock,
        session_ids: list[str],
    ) -> None:
        """Make the 6th pg.execute return rows with .id attributes."""
        rows = [SimpleNamespace(id=sid) for sid in session_ids]
        fetch_result = MagicMock()
        fetch_result.fetchall.return_value = rows
        # Calls 1-5 return default AsyncMock; 6th returns our rows
        pg_mock.execute = AsyncMock(
            side_effect=[
                AsyncMock(),  # 1: tombstone player
                AsyncMock(),  # 2: end sessions
                AsyncMock(),  # 3: scrub turns
                AsyncMock(),  # 4: scrub game data
                AsyncMock(),  # 5: delete tokens
                fetch_result,  # 6: fetch session IDs
            ]
        )
        pg_mock.commit = AsyncMock()

    def test_redis_sessions_evicted(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
        redis_mock: AsyncMock,
    ) -> None:
        sid1, sid2 = str(uuid4()), str(uuid4())
        self._configure_session_ids(pg_mock, [sid1, sid2])

        authed_client.delete("/api/v1/players/me")

        assert redis_mock.delete.await_count >= 2 or redis_mock.method_calls

    def test_neo4j_worlds_cleaned(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
        world_service_mock: AsyncMock,
    ) -> None:
        sid1, sid2 = str(uuid4()), str(uuid4())
        self._configure_session_ids(pg_mock, [sid1, sid2])

        authed_client.delete("/api/v1/players/me")

        assert world_service_mock.cleanup_session.await_count == 2

    def test_redis_failure_does_not_block_neo4j(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
        redis_mock: AsyncMock,
        world_service_mock: AsyncMock,
    ) -> None:
        sid1 = str(uuid4())
        self._configure_session_ids(pg_mock, [sid1])

        # Make the redis call fail — import needed for side effect

        import tta.api.routes.players as players_mod

        original = players_mod.delete_active_session

        async def _failing_redis(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("Redis down")

        players_mod.delete_active_session = _failing_redis  # type: ignore[assignment]
        try:
            authed_client.delete("/api/v1/players/me")
            # Neo4j cleanup should still have been attempted
            assert world_service_mock.cleanup_session.await_count == 1
        finally:
            players_mod.delete_active_session = original  # type: ignore[assignment]

    def test_no_sessions_skips_cleanup(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
        redis_mock: AsyncMock,
        world_service_mock: AsyncMock,
    ) -> None:
        self._configure_session_ids(pg_mock, [])

        authed_client.delete("/api/v1/players/me")

        world_service_mock.cleanup_session.assert_not_awaited()
