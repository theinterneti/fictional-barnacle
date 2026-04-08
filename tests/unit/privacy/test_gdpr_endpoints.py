"""Tests for GDPR stub endpoints (S17 §3 FR-17.6, FR-17.9)."""

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
_PLAYER = Player(id=uuid4(), handle="TestPlayer", created_at=_NOW)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


@pytest.fixture()
def authed_client() -> TestClient:
    app = create_app(_settings())
    app.dependency_overrides[get_pg] = lambda: AsyncMock()
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
    """DELETE /api/v1/players/me → 202."""

    def test_returns_202_accepted(self, authed_client: TestClient) -> None:
        resp = authed_client.delete("/api/v1/players/me")
        assert resp.status_code == 202
        body = resp.json()
        assert "data" in body

    def test_unauthenticated_rejected(self, anon_client: TestClient) -> None:
        resp = anon_client.delete("/api/v1/players/me")
        assert resp.status_code == 401
