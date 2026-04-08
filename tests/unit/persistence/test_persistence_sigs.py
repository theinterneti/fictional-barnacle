"""Tests for persistence module function signatures.

Validates that all persistence stubs exist, are async-callable,
raise ``NotImplementedError``, and carry correct type annotations.
"""

import inspect
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from tta.models.game import GameSession, GameState, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.world import WorldEvent
from tta.persistence import postgres, redis_session

# ── helpers ──────────────────────────────────────────────────────


def _return_annotation(fn: object) -> object:
    """Extract the return annotation from a callable."""
    hints = inspect.get_annotations(fn, eval_str=True)
    return hints.get("return")


# ── existence & async checks ─────────────────────────────────────

POSTGRES_FUNCTIONS = [
    "create_player",
    "get_player",
    "get_player_by_handle",
    "create_session",
    "get_session",
    "delete_session",
    "create_game",
    "get_game",
    "update_game_status",
    "list_player_games",
    "create_turn",
    "get_turn",
    "complete_turn",
    "get_processing_turn",
    "get_turn_by_idempotency_key",
    "create_world_event",
    "get_recent_events",
]

REDIS_FUNCTIONS = [
    "get_active_session",
    "set_active_session",
    "delete_active_session",
]


@pytest.mark.parametrize("name", POSTGRES_FUNCTIONS)
def test_postgres_function_exists_and_is_async(name: str) -> None:
    fn = getattr(postgres, name, None)
    assert fn is not None, f"postgres.{name} not found"
    assert callable(fn), f"postgres.{name} is not callable"
    assert inspect.iscoroutinefunction(fn), f"postgres.{name} must be async"


@pytest.mark.parametrize("name", REDIS_FUNCTIONS)
def test_redis_function_exists_and_is_async(name: str) -> None:
    fn = getattr(redis_session, name, None)
    assert fn is not None, f"redis_session.{name} not found"
    assert callable(fn), f"redis_session.{name} is not callable"
    assert inspect.iscoroutinefunction(fn), f"redis_session.{name} must be async"


# ── NotImplementedError checks (postgres) ────────────────────────

_PLAYER_ID = uuid4()
_SESSION_ID = uuid4()
_GAME_ID = uuid4()
_TURN_ID = uuid4()
_KEY = uuid4()
_NOW = datetime.now()


@pytest.mark.parametrize(
    "fn, kwargs",
    [
        (postgres.create_player, {"handle": "alice"}),
        (postgres.get_player, {"player_id": _PLAYER_ID}),
        (postgres.get_player_by_handle, {"handle": "alice"}),
        (
            postgres.create_session,
            {
                "player_id": _PLAYER_ID,
                "token": "tok",
                "expires_at": _NOW,
            },
        ),
        (postgres.get_session, {"token": "tok"}),
        (postgres.delete_session, {"token": "tok"}),
        (
            postgres.create_game,
            {"player_id": _PLAYER_ID, "world_seed": {}},
        ),
        (postgres.get_game, {"game_id": _GAME_ID}),
        (
            postgres.update_game_status,
            {"game_id": _GAME_ID, "status": GameStatus.paused},
        ),
        (
            postgres.list_player_games,
            {"player_id": _PLAYER_ID},
        ),
        (
            postgres.create_turn,
            {
                "session_id": _SESSION_ID,
                "turn_number": 1,
                "player_input": "go north",
            },
        ),
        (postgres.get_turn, {"turn_id": _TURN_ID}),
        (
            postgres.complete_turn,
            {
                "turn_id": _TURN_ID,
                "narrative_output": "You walk north.",
                "model_used": "gpt-4",
                "latency_ms": 123.4,
                "token_count": {},
            },
        ),
        (
            postgres.get_processing_turn,
            {"session_id": _SESSION_ID},
        ),
        (
            postgres.get_turn_by_idempotency_key,
            {"session_id": _SESSION_ID, "key": _KEY},
        ),
        (
            postgres.create_world_event,
            {
                "session_id": _SESSION_ID,
                "turn_id": _TURN_ID,
                "event_type": "player_moved",
                "entity_id": "loc-1",
                "payload": {},
            },
        ),
        (
            postgres.get_recent_events,
            {"session_id": _SESSION_ID},
        ),
    ],
)
async def test_postgres_raises_not_implemented(fn: object, kwargs: dict) -> None:
    with pytest.raises(NotImplementedError):
        await fn(**kwargs)  # type: ignore[operator]


# ── NotImplementedError checks (redis) ───────────────────────────


# ── Signature checks (redis) ─────────────────────────────────────


def test_redis_get_active_session_accepts_redis_param() -> None:
    sig = inspect.signature(redis_session.get_active_session)
    params = list(sig.parameters)
    assert "redis" in params, "get_active_session must accept a redis param"
    assert "session_id" in params


def test_redis_set_active_session_accepts_redis_param() -> None:
    sig = inspect.signature(redis_session.set_active_session)
    params = list(sig.parameters)
    assert "redis" in params, "set_active_session must accept a redis param"
    assert "session_id" in params
    assert "state" in params


def test_redis_delete_active_session_accepts_redis_param() -> None:
    sig = inspect.signature(redis_session.delete_active_session)
    params = list(sig.parameters)
    assert "redis" in params, "delete_active_session must accept a redis param"
    assert "session_id" in params


# ── Type-annotation checks ───────────────────────────────────────


def test_create_player_returns_player() -> None:
    assert _return_annotation(postgres.create_player) is Player


def test_get_player_returns_optional_player() -> None:
    ann = _return_annotation(postgres.get_player)
    assert ann == Player | None


def test_create_session_returns_player_session() -> None:
    ann = _return_annotation(postgres.create_session)
    assert ann is PlayerSession


def test_get_session_returns_optional_session() -> None:
    ann = _return_annotation(postgres.get_session)
    assert ann == PlayerSession | None


def test_delete_session_returns_none() -> None:
    ann = _return_annotation(postgres.delete_session)
    assert ann is None


def test_create_game_returns_game_session() -> None:
    ann = _return_annotation(postgres.create_game)
    assert ann is GameSession


def test_get_game_returns_optional_game() -> None:
    ann = _return_annotation(postgres.get_game)
    assert ann == GameSession | None


def test_update_game_status_returns_none() -> None:
    ann = _return_annotation(postgres.update_game_status)
    assert ann is None


def test_list_player_games_returns_list() -> None:
    ann = _return_annotation(postgres.list_player_games)
    assert ann == list[GameSession]


def test_create_turn_returns_dict() -> None:
    ann = _return_annotation(postgres.create_turn)
    assert ann is dict


def test_get_turn_returns_optional_dict() -> None:
    ann = _return_annotation(postgres.get_turn)
    assert ann == dict | None


def test_complete_turn_returns_none() -> None:
    ann = _return_annotation(postgres.complete_turn)
    assert ann is None


def test_create_world_event_returns_world_event() -> None:
    ann = _return_annotation(postgres.create_world_event)
    assert ann is WorldEvent


def test_get_recent_events_returns_list() -> None:
    ann = _return_annotation(postgres.get_recent_events)
    assert ann == list[WorldEvent]


def test_redis_get_returns_optional_game_state() -> None:
    ann = _return_annotation(redis_session.get_active_session)
    assert ann == GameState | None


def test_redis_set_returns_none() -> None:
    ann = _return_annotation(redis_session.set_active_session)
    assert ann is None


def test_redis_delete_returns_none() -> None:
    ann = _return_annotation(redis_session.delete_active_session)
    assert ann is None


# ── Parameter-annotation spot checks ─────────────────────────────


def test_create_session_expires_at_is_datetime() -> None:
    hints = inspect.get_annotations(postgres.create_session, eval_str=True)
    assert hints["expires_at"] is datetime


def test_create_turn_idempotency_key_optional_uuid() -> None:
    hints = inspect.get_annotations(postgres.create_turn, eval_str=True)
    assert hints["idempotency_key"] == UUID | None


def test_redis_set_ttl_is_int() -> None:
    hints = inspect.get_annotations(redis_session.set_active_session, eval_str=True)
    assert hints["ttl"] is int
