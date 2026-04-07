"""Unit-test fixtures — model factory helpers.

Each factory returns a *callable* so tests can create instances
with sensible defaults while overriding individual fields.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from tta.models.game import GameSession, GameStatus
from tta.models.player import Player
from tta.models.turn import TurnState, TurnStatus


@pytest.fixture()
def create_player() -> Callable[..., Player]:
    """Factory that builds ``Player`` instances with sensible defaults."""

    def _factory(
        *,
        handle: str = "test-player",
        **overrides: object,
    ) -> Player:
        return Player(handle=handle, **overrides)

    return _factory


@pytest.fixture()
def create_game_session() -> Callable[..., GameSession]:
    """Factory that builds ``GameSession`` instances with sensible defaults."""

    def _factory(
        *,
        player_id=None,
        status: GameStatus = GameStatus.active,
        **overrides: object,
    ) -> GameSession:
        if player_id is None:
            player_id = uuid4()
        return GameSession(
            player_id=player_id,
            status=status,
            **overrides,
        )

    return _factory


@pytest.fixture()
def create_turn_state() -> Callable[..., TurnState]:
    """Factory that builds ``TurnState`` instances with sensible defaults."""

    def _factory(
        *,
        session_id=None,
        turn_number: int = 1,
        player_input: str = "look around",
        game_state: dict | None = None,
        status: TurnStatus = TurnStatus.processing,
        **overrides: object,
    ) -> TurnState:
        if session_id is None:
            session_id = uuid4()
        if game_state is None:
            game_state = {"location": "start"}
        return TurnState(
            session_id=session_id,
            turn_number=turn_number,
            player_input=player_input,
            game_state=game_state,
            status=status,
            **overrides,
        )

    return _factory
