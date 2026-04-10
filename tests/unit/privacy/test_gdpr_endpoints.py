"""Tests for GDPR endpoints (S17 §3 FR-17.6, FR-17.9, FR-17.10)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg
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
    return AsyncMock()


@pytest.fixture()
def authed_client(pg_mock: AsyncMock) -> TestClient:
    app = create_app(_settings())
    app.dependency_overrides[get_pg] = lambda: pg_mock
    app.dependency_overrides[get_current_player] = lambda: _PLAYER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def anon_client() -> TestClient:
    app = create_app(_settings())
    app.dependency_overrides[get_pg] = lambda: AsyncMock()
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
        """All active/paused game sessions ended."""
        authed_client.delete("/api/v1/players/me")

        second_call = pg_mock.execute.call_args_list[1]
        sql_text = str(second_call.args[0].text)
        params = second_call.args[1]

        assert "game_sessions" in sql_text
        assert "status = 'ended'" in sql_text
        assert "('active', 'paused')" in sql_text
        assert params["pid"] == _PLAYER_ID

    def test_scrubs_turn_pii(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """Turn player_input and narrative_output NULLed."""
        authed_client.delete("/api/v1/players/me")

        third_call = pg_mock.execute.call_args_list[2]
        sql_text = str(third_call.args[0].text)

        assert "player_input = NULL" in sql_text
        assert "narrative_output = NULL" in sql_text
        assert "turns" in sql_text

    def test_scrubs_game_session_pii(
        self,
        authed_client: TestClient,
        pg_mock: AsyncMock,
    ) -> None:
        """Game session world_seed and summary NULLed."""
        authed_client.delete("/api/v1/players/me")

        fourth_call = pg_mock.execute.call_args_list[3]
        sql_text = str(fourth_call.args[0].text)

        assert "world_seed = NULL" in sql_text
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

        pg_mock.commit.assert_called_once()
        assert pg_mock.execute.call_count == 5
