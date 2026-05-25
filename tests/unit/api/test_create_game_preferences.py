from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from tta.api.app import create_app
from tta.api.deps import (
    get_current_player,
    get_pg,
    require_anonymous_game_limit,
    require_consent,
)
from tta.config import Settings
from tta.models.player import Player


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
        neo4j_uri="",
    )


def _make_result(*, scalar: int | None = None):
    result = MagicMock()
    if scalar is not None:
        result.scalar_one.return_value = scalar
    return result


def _mock_genesis_result() -> SimpleNamespace:
    return SimpleNamespace(
        world_id="world-1",
        player_location_id="loc-1",
        template_key="fantasy",
        narrative_intro="A strange wind stirs.",
        genesis_elements=["wind", "gate"],
    )


def _build_client() -> tuple[TestClient, AsyncMock, MagicMock]:
    app = create_app(_settings())
    pg = AsyncMock()
    player = Player(id=uuid4(), handle="Tester")

    async def _pg_override():
        return pg

    app.dependency_overrides[get_pg] = _pg_override
    app.dependency_overrides[get_current_player] = lambda: player
    app.dependency_overrides[require_consent] = lambda: player
    app.dependency_overrides[require_anonymous_game_limit] = lambda: player

    registry = MagicMock()
    registry.select_by_preferences.return_value = MagicMock()
    registry.get.return_value = MagicMock()
    app.state.template_registry = registry
    app.state.llm_client = MagicMock()
    app.state.world_service = MagicMock()
    return TestClient(app), pg, registry


@patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
def test_create_game_accepts_list_traits_and_returns_them(
    mock_genesis: AsyncMock,
) -> None:
    client, pg, _registry = _build_client()
    mock_genesis.return_value = _mock_genesis_result()
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(scalar=0),
            _make_result(),
            _make_result(),
        ]
    )
    pg.commit = AsyncMock()

    resp = client.post(
        "/api/v1/games",
        json={
            "preferences": {
                "tone": "dark",
                "character_name": "Nyx",
                "traits": ["curious", "bold", ""],
            }
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["character_name"] == "Nyx"
    assert data["character_traits"] == ["curious", "bold"]


@patch("tta.genesis.genesis_lite.run_genesis_lite", new_callable=AsyncMock)
def test_create_game_coerces_string_trait_to_singleton_list(
    mock_genesis: AsyncMock,
) -> None:
    client, pg, _registry = _build_client()
    mock_genesis.return_value = _mock_genesis_result()
    pg.execute = AsyncMock(
        side_effect=[
            _make_result(scalar=0),
            _make_result(),
            _make_result(),
        ]
    )
    pg.commit = AsyncMock()

    resp = client.post(
        "/api/v1/games",
        json={
            "preferences": {
                "character_name": "Nyx",
                "traits": "careful",
            }
        },
    )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["character_traits"] == ["careful"]
