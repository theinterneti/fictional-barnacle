"""BDD test fixtures and shared step definitions.

Uses sync TestClient because pytest-bdd does not support async step
functions (S16 spec note).  Database interaction is mocked via
dependency overrides following the pattern in tests/unit/api/.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then

from tta.api.app import create_app
from tta.api.deps import get_current_player, get_pg
from tta.config import Settings
from tta.models.player import Player

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="BddHero", created_at=_NOW)
_GAME_ID = uuid4()
_TURN_ID = uuid4()


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        llm_mock=True,
    )


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    *,
    scalar: Any = None,
) -> MagicMock:
    """Build a mock CursorResult (sync methods)."""
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


def _game_row(
    *,
    game_id: Any = None,
    player_id: Any = None,
    status: str = "active",
    turn_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "status": status,
        "world_seed": "{}",
        "turn_count": turn_count,
        "title": None,
        "summary": None,
        "needs_recovery": False,
        "last_played_at": _NOW,
        "deleted_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# ----- fixtures -----


@pytest.fixture()
def pg() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def bdd_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.games.get_settings", lambda: settings)
    monkeypatch.setattr("tta.api.routes.players.get_settings", lambda: settings)
    return settings


@pytest.fixture()
def app(pg: AsyncMock, bdd_settings: Settings) -> FastAPI:
    a = create_app(settings=bdd_settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    return a


@pytest.fixture()
def unauth_app(pg: AsyncMock, bdd_settings: Settings) -> FastAPI:
    """App without the get_current_player override — will hit real auth."""
    a = create_app(settings=bdd_settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def unauth_client(unauth_app: FastAPI) -> TestClient:
    return TestClient(unauth_app)


@pytest.fixture()
def ctx() -> dict:
    """Shared mutable state container passed between BDD steps."""
    return {}


# ----- shared step definitions -----


@given(
    "a registered player with a valid session token",
    target_fixture="ctx",
)
def registered_player(ctx: dict) -> dict:
    ctx["authenticated"] = True
    return ctx


@given("the player has an active game", target_fixture="ctx")
def active_game(ctx: dict) -> dict:
    ctx["game_id"] = _GAME_ID
    return ctx


@given("no authentication is provided", target_fixture="ctx")
def no_auth(ctx: dict) -> dict:
    ctx["authenticated"] = False
    return ctx


@then(parsers.parse("the response status is {code:d}"))
def check_status(ctx: dict, code: int) -> None:
    assert ctx["response"].status_code == code
