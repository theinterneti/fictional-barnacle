"""Tests for player registration and profile routes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg
from tta.config import Settings
from tta.models.player import Player

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="Zara", created_at=_NOW)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    """Build a mock CursorResult with .one_or_none / .scalar_one / .all.

    These methods are synchronous on SQLAlchemy CursorResult, so use
    MagicMock (not AsyncMock).
    """
    result = MagicMock()
    if rows is not None:
        objs = [SimpleNamespace(**r) for r in rows]
        result.one_or_none.return_value = objs[0] if objs else None
        result.all.return_value = objs
    else:
        result.one_or_none.return_value = None
        result.all.return_value = []
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


@pytest.fixture()
def pg() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def app(pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.players.get_settings", lambda: settings)
    a = create_app(settings=settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ------------------------------------------------------------------
# POST /api/v1/players — Registration
# ------------------------------------------------------------------


class TestRegisterPlayer:
    def test_creates_player_and_returns_201(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        # First execute: handle uniqueness check → no existing
        # Rest: INSERT player, INSERT session, commit
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # SELECT id → None (handle not taken)
                _make_result(),  # INSERT player
                _make_result(),  # INSERT session
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            "/api/v1/players",
            json={"handle": "NewPlayer"},
        )

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["handle"] == "NewPlayer"
        assert "session_token" in body
        assert "player_id" in body
        assert pg.commit.await_count == 1

    def test_sets_session_cookie(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),
                _make_result(),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            "/api/v1/players",
            json={"handle": "CookieTest"},
        )

        assert resp.status_code == 201
        assert "tta_session" in resp.cookies

    def test_rejects_duplicate_handle(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result(
                [{"id": uuid4()}]  # handle already exists
            )
        )

        resp = client.post(
            "/api/v1/players",
            json={"handle": "Zara"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "HANDLE_ALREADY_TAKEN"

    def test_rejects_empty_handle(self, client: TestClient) -> None:
        resp = client.post("/api/v1/players", json={"handle": ""})
        assert resp.status_code == 422

    def test_rejects_invalid_handle_chars(self, client: TestClient) -> None:
        resp = client.post("/api/v1/players", json={"handle": "bad@handle!"})
        assert resp.status_code == 422


# ------------------------------------------------------------------
# GET /api/v1/players/me — Profile
# ------------------------------------------------------------------


class TestGetProfile:
    def test_returns_authenticated_player(self, client: TestClient) -> None:
        resp = client.get("/api/v1/players/me")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["player_id"] == str(_PLAYER_ID)
        assert body["handle"] == "Zara"


# ------------------------------------------------------------------
# PATCH /api/v1/players/me — Update profile
# ------------------------------------------------------------------


class TestUpdateProfile:
    def test_updates_handle(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(),  # uniqueness check → not taken
                _make_result(),  # UPDATE
            ]
        )
        pg.commit = AsyncMock()

        resp = client.patch(
            "/api/v1/players/me",
            json={"handle": "NewName"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["handle"] == "NewName"
        assert pg.commit.await_count == 1

    def test_noop_when_no_changes(self, client: TestClient) -> None:
        resp = client.patch(
            "/api/v1/players/me",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["handle"] == "Zara"

    def test_rejects_duplicate_handle(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([{"id": uuid4()}]))

        resp = client.patch(
            "/api/v1/players/me",
            json={"handle": "TakenName"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "HANDLE_ALREADY_TAKEN"

    def test_skips_uniqueness_check_when_unchanged(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        resp = client.patch(
            "/api/v1/players/me",
            json={"handle": "Zara"},  # same as current
        )
        assert resp.status_code == 200
        # No DB calls needed
        pg.execute.assert_not_awaited()
