"""Tests for Postgres repository classes — signatures and structure.

These tests verify the classes exist, have correct method signatures,
and accept the right constructor args. They do NOT connect to a
real database.
"""

import inspect
from unittest.mock import MagicMock

import pytest

from tta.persistence.postgres import (
    PostgresGameRepository,
    PostgresPlayerRepository,
    PostgresSessionRepository,
    PostgresTurnRepository,
    PostgresWorldEventRepository,
)

# A mock session factory used only to instantiate the repos.
_MOCK_SF = MagicMock()


# ── Class existence ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "cls",
    [
        PostgresPlayerRepository,
        PostgresSessionRepository,
        PostgresGameRepository,
        PostgresTurnRepository,
        PostgresWorldEventRepository,
    ],
)
def test_postgres_repo_class_exists(cls: type) -> None:
    assert isinstance(cls, type)


# ── Constructor accepts session_factory ──────────────────────────


@pytest.mark.parametrize(
    "cls",
    [
        PostgresPlayerRepository,
        PostgresSessionRepository,
        PostgresGameRepository,
        PostgresTurnRepository,
        PostgresWorldEventRepository,
    ],
)
def test_postgres_repo_accepts_session_factory(cls: type) -> None:
    repo = cls(_MOCK_SF)
    assert repo is not None


# ── Method signatures ────────────────────────────────────────────


PLAYER_METHODS = [
    "create_player",
    "get_player",
    "get_player_by_handle",
]

SESSION_METHODS = [
    "create_session",
    "get_session",
    "delete_session",
]

GAME_METHODS = [
    "create_game",
    "get_game",
    "update_game_status",
    "list_player_games",
]

TURN_METHODS = [
    "create_turn",
    "get_turn",
    "complete_turn",
    "update_status",
    "get_processing_turn",
    "get_turn_by_idempotency_key",
]

WORLD_EVENT_METHODS = [
    "create_world_event",
    "get_recent_events",
]


@pytest.mark.parametrize("method_name", PLAYER_METHODS)
def test_player_repo_has_async_method(
    method_name: str,
) -> None:
    repo = PostgresPlayerRepository(_MOCK_SF)
    method = getattr(repo, method_name, None)
    assert method is not None, f"missing {method_name}"
    assert inspect.iscoroutinefunction(method), (
        f"{method_name} must be async"
    )


@pytest.mark.parametrize("method_name", SESSION_METHODS)
def test_session_repo_has_async_method(
    method_name: str,
) -> None:
    repo = PostgresSessionRepository(_MOCK_SF)
    method = getattr(repo, method_name, None)
    assert method is not None, f"missing {method_name}"
    assert inspect.iscoroutinefunction(method), (
        f"{method_name} must be async"
    )


@pytest.mark.parametrize("method_name", GAME_METHODS)
def test_game_repo_has_async_method(
    method_name: str,
) -> None:
    repo = PostgresGameRepository(_MOCK_SF)
    method = getattr(repo, method_name, None)
    assert method is not None, f"missing {method_name}"
    assert inspect.iscoroutinefunction(method), (
        f"{method_name} must be async"
    )


@pytest.mark.parametrize("method_name", TURN_METHODS)
def test_turn_repo_has_async_method(
    method_name: str,
) -> None:
    repo = PostgresTurnRepository(_MOCK_SF)
    method = getattr(repo, method_name, None)
    assert method is not None, f"missing {method_name}"
    assert inspect.iscoroutinefunction(method), (
        f"{method_name} must be async"
    )


@pytest.mark.parametrize("method_name", WORLD_EVENT_METHODS)
def test_world_event_repo_has_async_method(
    method_name: str,
) -> None:
    repo = PostgresWorldEventRepository(_MOCK_SF)
    method = getattr(repo, method_name, None)
    assert method is not None, f"missing {method_name}"
    assert inspect.iscoroutinefunction(method), (
        f"{method_name} must be async"
    )


# ── Engine module ────────────────────────────────────────────────


def test_engine_module_exports() -> None:
    from tta.persistence.engine import (
        build_engine,
        build_session_factory,
    )

    assert callable(build_engine)
    assert callable(build_session_factory)


def test_build_engine_rejects_bad_url() -> None:
    from tta.persistence.engine import build_engine

    with pytest.raises(ValueError, match="database_url must start"):
        build_engine("mysql://localhost/db")


def test_build_engine_accepts_asyncpg_url() -> None:
    from tta.persistence.engine import _ensure_async_url

    url = "postgresql+asyncpg://user:pass@localhost/db"
    assert _ensure_async_url(url) == url


def test_build_engine_converts_plain_url() -> None:
    from tta.persistence.engine import _ensure_async_url

    url = "postgresql://user:pass@localhost/db"
    result = _ensure_async_url(url)
    assert result == "postgresql+asyncpg://user:pass@localhost/db"
