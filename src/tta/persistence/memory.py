"""In-memory repository implementations for testing.

These classes satisfy the persistence protocols without requiring
a database, making them ideal for unit tests and local development.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from tta.models.game import GameSession, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.world import WorldEvent


class InMemoryPlayerRepository:
    """Dict-backed player store."""

    def __init__(self) -> None:
        self._players: dict[UUID, Player] = {}
        self._by_handle: dict[str, UUID] = {}

    async def create_player(self, handle: str) -> Player:
        if handle in self._by_handle:
            msg = f"handle already taken: {handle}"
            raise ValueError(msg)
        player = Player(handle=handle)
        self._players[player.id] = player
        self._by_handle[handle] = player.id
        return player

    async def get_player(self, player_id: UUID) -> Player | None:
        return self._players.get(player_id)

    async def get_player_by_handle(self, handle: str) -> Player | None:
        pid = self._by_handle.get(handle)
        if pid is None:
            return None
        return self._players.get(pid)


class InMemorySessionRepository:
    """Dict-backed player-session (auth token) store."""

    def __init__(self) -> None:
        self._sessions: dict[str, PlayerSession] = {}

    async def create_session(
        self,
        player_id: UUID,
        token: str,
        expires_at: datetime,
    ) -> PlayerSession:
        session = PlayerSession(
            player_id=player_id,
            token=token,
            expires_at=expires_at,
        )
        self._sessions[token] = session
        return session

    async def get_session(self, token: str) -> PlayerSession | None:
        return self._sessions.get(token)

    async def delete_session(self, token: str) -> None:
        self._sessions.pop(token, None)


class InMemoryGameRepository:
    """Dict-backed game-session store."""

    def __init__(self) -> None:
        self._games: dict[UUID, GameSession] = {}

    async def create_game(self, player_id: UUID, world_seed: dict) -> GameSession:
        game = GameSession(player_id=player_id, world_seed=world_seed)
        self._games[game.id] = game
        return game

    async def get_game(self, game_id: UUID) -> GameSession | None:
        return self._games.get(game_id)

    async def update_game_status(self, game_id: UUID, status: GameStatus) -> None:
        game = self._games.get(game_id)
        if game is None:
            msg = f"game not found: {game_id}"
            raise ValueError(msg)
        game.status = status
        game.updated_at = datetime.now(UTC)

    async def list_player_games(self, player_id: UUID) -> list[GameSession]:
        return [g for g in self._games.values() if g.player_id == player_id]


class InMemoryTurnRepository:
    """Dict-backed turn store."""

    def __init__(self) -> None:
        self._turns: dict[UUID, dict] = {}
        self._by_session_turn: dict[tuple[UUID, int], UUID] = {}
        self._by_idempotency: dict[tuple[UUID, UUID], UUID] = {}

    async def create_turn(
        self,
        session_id: UUID,
        turn_number: int,
        player_input: str,
        idempotency_key: UUID | None = None,
    ) -> dict:
        key = (session_id, turn_number)
        if key in self._by_session_turn:
            msg = f"duplicate turn: session={session_id}, turn_number={turn_number}"
            raise ValueError(msg)
        if (
            idempotency_key is not None
            and (session_id, idempotency_key) in self._by_idempotency
        ):
            msg = (
                f"duplicate idempotency_key: "
                f"session={session_id}, key={idempotency_key}"
            )
            raise ValueError(msg)

        turn_id = uuid4()
        now = datetime.now(UTC)
        turn: dict = {
            "id": turn_id,
            "session_id": session_id,
            "turn_number": turn_number,
            "player_input": player_input,
            "idempotency_key": idempotency_key,
            "status": "processing",
            "narrative_output": None,
            "model_used": None,
            "latency_ms": None,
            "token_count": None,
            "created_at": now,
            "completed_at": None,
        }
        self._turns[turn_id] = turn
        self._by_session_turn[key] = turn_id
        if idempotency_key is not None:
            self._by_idempotency[(session_id, idempotency_key)] = turn_id
        return turn

    async def get_turn(self, turn_id: UUID) -> dict | None:
        return self._turns.get(turn_id)

    async def complete_turn(
        self,
        turn_id: UUID,
        narrative_output: str,
        model_used: str,
        latency_ms: float,
        token_count: dict,
    ) -> None:
        turn = self._turns.get(turn_id)
        if turn is None:
            msg = f"turn not found: {turn_id}"
            raise ValueError(msg)
        turn["narrative_output"] = narrative_output
        turn["model_used"] = model_used
        turn["latency_ms"] = latency_ms
        turn["token_count"] = token_count
        turn["status"] = "complete"
        turn["completed_at"] = datetime.now(UTC)

    async def update_status(self, turn_id: UUID, status: str) -> None:
        turn = self._turns.get(turn_id)
        if turn is None:
            msg = f"turn not found: {turn_id}"
            raise ValueError(msg)
        turn["status"] = status

    async def fail_turn(
        self,
        turn_id: UUID,
        narrative_output: str | None = None,
    ) -> None:
        turn = self._turns.get(turn_id)
        if turn is None:
            msg = f"turn not found: {turn_id}"
            raise ValueError(msg)
        turn["status"] = "failed"
        if narrative_output is not None:
            turn["narrative_output"] = narrative_output

    async def get_processing_turn(self, session_id: UUID) -> dict | None:
        for turn in self._turns.values():
            if turn["session_id"] == session_id and turn["status"] == "processing":
                return turn
        return None

    async def get_turn_by_idempotency_key(
        self, session_id: UUID, key: UUID
    ) -> dict | None:
        turn_id = self._by_idempotency.get((session_id, key))
        if turn_id is None:
            return None
        return self._turns.get(turn_id)


class InMemoryWorldEventRepository:
    """Dict-backed world-event store."""

    def __init__(self) -> None:
        self._events: list[WorldEvent] = []

    async def create_world_event(
        self,
        session_id: UUID,
        turn_id: UUID,
        event_type: str,
        entity_id: str,
        payload: dict,
    ) -> WorldEvent:
        event = WorldEvent(
            session_id=session_id,
            turn_id=turn_id,
            event_type=event_type,
            entity_id=entity_id,
            payload=payload,
        )
        self._events.append(event)
        return event

    async def get_recent_events(
        self, session_id: UUID, limit: int = 5
    ) -> list[WorldEvent]:
        matching = [e for e in self._events if e.session_id == session_id]
        matching.sort(key=lambda e: e.created_at, reverse=True)
        return matching[:limit]
