"""Comprehensive tests for in-memory repository implementations.

These exercise every protocol method without a database.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tta.models.game import GameSession, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.world import WorldEvent
from tta.persistence.memory import (
    InMemoryGameRepository,
    InMemoryPlayerRepository,
    InMemorySessionRepository,
    InMemoryTurnRepository,
    InMemoryWorldEventRepository,
)

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def player_repo() -> InMemoryPlayerRepository:
    return InMemoryPlayerRepository()


@pytest.fixture()
def session_repo() -> InMemorySessionRepository:
    return InMemorySessionRepository()


@pytest.fixture()
def game_repo() -> InMemoryGameRepository:
    return InMemoryGameRepository()


@pytest.fixture()
def turn_repo() -> InMemoryTurnRepository:
    return InMemoryTurnRepository()


@pytest.fixture()
def event_repo() -> InMemoryWorldEventRepository:
    return InMemoryWorldEventRepository()


# =====================================================================
# PlayerRepository
# =====================================================================


class TestInMemoryPlayerRepository:
    async def test_create_player(self, player_repo: InMemoryPlayerRepository) -> None:
        player = await player_repo.create_player("alice")
        assert isinstance(player, Player)
        assert player.handle == "alice"
        assert player.id is not None
        assert player.created_at is not None

    async def test_get_player(self, player_repo: InMemoryPlayerRepository) -> None:
        created = await player_repo.create_player("bob")
        fetched = await player_repo.get_player(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.handle == "bob"

    async def test_get_player_not_found(
        self, player_repo: InMemoryPlayerRepository
    ) -> None:
        result = await player_repo.get_player(uuid4())
        assert result is None

    async def test_get_player_by_handle(
        self, player_repo: InMemoryPlayerRepository
    ) -> None:
        created = await player_repo.create_player("charlie")
        fetched = await player_repo.get_player_by_handle("charlie")
        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_player_by_handle_not_found(
        self, player_repo: InMemoryPlayerRepository
    ) -> None:
        result = await player_repo.get_player_by_handle("nobody")
        assert result is None

    async def test_duplicate_handle_raises(
        self, player_repo: InMemoryPlayerRepository
    ) -> None:
        await player_repo.create_player("dupe")
        with pytest.raises(ValueError, match="handle already taken"):
            await player_repo.create_player("dupe")

    async def test_multiple_players(
        self, player_repo: InMemoryPlayerRepository
    ) -> None:
        p1 = await player_repo.create_player("one")
        p2 = await player_repo.create_player("two")
        assert p1.id != p2.id
        assert (await player_repo.get_player(p1.id)) is not None
        assert (await player_repo.get_player(p2.id)) is not None


# =====================================================================
# SessionRepository (player auth sessions)
# =====================================================================


class TestInMemorySessionRepository:
    async def test_create_session(
        self, session_repo: InMemorySessionRepository
    ) -> None:
        pid = uuid4()
        expires = datetime.now(UTC) + timedelta(hours=1)
        sess = await session_repo.create_session(pid, "tok-abc", expires)
        assert isinstance(sess, PlayerSession)
        assert sess.player_id == pid
        assert sess.token == "tok-abc"
        assert sess.expires_at == expires

    async def test_get_session(self, session_repo: InMemorySessionRepository) -> None:
        pid = uuid4()
        expires = datetime.now(UTC) + timedelta(hours=1)
        await session_repo.create_session(pid, "tok-1", expires)
        fetched = await session_repo.get_session("tok-1")
        assert fetched is not None
        assert fetched.token == "tok-1"

    async def test_get_session_not_found(
        self, session_repo: InMemorySessionRepository
    ) -> None:
        result = await session_repo.get_session("nonexistent")
        assert result is None

    async def test_delete_session(
        self, session_repo: InMemorySessionRepository
    ) -> None:
        pid = uuid4()
        expires = datetime.now(UTC) + timedelta(hours=1)
        await session_repo.create_session(pid, "tok-del", expires)
        await session_repo.delete_session("tok-del")
        assert await session_repo.get_session("tok-del") is None

    async def test_delete_nonexistent_is_noop(
        self, session_repo: InMemorySessionRepository
    ) -> None:
        # Should not raise
        await session_repo.delete_session("ghost")


# =====================================================================
# GameRepository
# =====================================================================


class TestInMemoryGameRepository:
    async def test_create_game(self, game_repo: InMemoryGameRepository) -> None:
        pid = uuid4()
        game = await game_repo.create_game(pid, {"theme": "forest"})
        assert isinstance(game, GameSession)
        assert game.player_id == pid
        assert game.world_seed == {"theme": "forest"}
        assert game.status == GameStatus.created

    async def test_get_game(self, game_repo: InMemoryGameRepository) -> None:
        pid = uuid4()
        created = await game_repo.create_game(pid, {})
        fetched = await game_repo.get_game(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_game_not_found(self, game_repo: InMemoryGameRepository) -> None:
        assert await game_repo.get_game(uuid4()) is None

    async def test_update_game_status(self, game_repo: InMemoryGameRepository) -> None:
        pid = uuid4()
        game = await game_repo.create_game(pid, {})
        assert game.status == GameStatus.created

        await game_repo.update_game_status(game.id, GameStatus.paused)
        updated = await game_repo.get_game(game.id)
        assert updated is not None
        assert updated.status == GameStatus.paused

    async def test_update_game_status_not_found_raises(
        self, game_repo: InMemoryGameRepository
    ) -> None:
        with pytest.raises(ValueError, match="game not found"):
            await game_repo.update_game_status(uuid4(), GameStatus.ended)

    async def test_list_player_games(self, game_repo: InMemoryGameRepository) -> None:
        p1 = uuid4()
        p2 = uuid4()
        await game_repo.create_game(p1, {"a": 1})
        await game_repo.create_game(p1, {"b": 2})
        await game_repo.create_game(p2, {"c": 3})

        p1_games = await game_repo.list_player_games(p1)
        assert len(p1_games) == 2
        assert all(g.player_id == p1 for g in p1_games)

        p2_games = await game_repo.list_player_games(p2)
        assert len(p2_games) == 1

    async def test_list_player_games_empty(
        self, game_repo: InMemoryGameRepository
    ) -> None:
        result = await game_repo.list_player_games(uuid4())
        assert result == []

    async def test_update_game_status_updates_timestamp(
        self, game_repo: InMemoryGameRepository
    ) -> None:
        pid = uuid4()
        game = await game_repo.create_game(pid, {})
        original_updated_at = game.updated_at
        await game_repo.update_game_status(game.id, GameStatus.ended)
        updated = await game_repo.get_game(game.id)
        assert updated is not None
        assert updated.updated_at >= original_updated_at


# =====================================================================
# TurnRepository
# =====================================================================


class TestInMemoryTurnRepository:
    async def test_create_turn(self, turn_repo: InMemoryTurnRepository) -> None:
        sid = uuid4()
        turn = await turn_repo.create_turn(sid, 1, "go north")
        assert turn["id"] is not None
        assert turn["session_id"] == sid
        assert turn["turn_number"] == 1
        assert turn["player_input"] == "go north"
        assert turn["status"] == "processing"
        assert turn["narrative_output"] is None
        assert turn["completed_at"] is None

    async def test_create_turn_with_idempotency_key(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid = uuid4()
        key = uuid4()
        turn = await turn_repo.create_turn(sid, 1, "look", idempotency_key=key)
        assert turn["idempotency_key"] == key

    async def test_get_turn(self, turn_repo: InMemoryTurnRepository) -> None:
        sid = uuid4()
        created = await turn_repo.create_turn(sid, 1, "look")
        fetched = await turn_repo.get_turn(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["player_input"] == "look"

    async def test_get_turn_not_found(self, turn_repo: InMemoryTurnRepository) -> None:
        assert await turn_repo.get_turn(uuid4()) is None

    async def test_complete_turn(self, turn_repo: InMemoryTurnRepository) -> None:
        sid = uuid4()
        turn = await turn_repo.create_turn(sid, 1, "go north")
        tokens = {"prompt": 100, "completion": 50, "total": 150}

        await turn_repo.complete_turn(
            turn["id"],
            narrative_output="You walk north.",
            model_used="gpt-4o",
            latency_ms=250.5,
            token_count=tokens,
        )

        updated = await turn_repo.get_turn(turn["id"])
        assert updated is not None
        assert updated["status"] == "complete"
        assert updated["narrative_output"] == "You walk north."
        assert updated["model_used"] == "gpt-4o"
        assert updated["latency_ms"] == 250.5
        assert updated["token_count"] == tokens
        assert updated["completed_at"] is not None

    async def test_complete_turn_not_found_raises(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        with pytest.raises(ValueError, match="turn not found"):
            await turn_repo.complete_turn(uuid4(), "text", "model", 100.0, {})

    async def test_update_status(self, turn_repo: InMemoryTurnRepository) -> None:
        sid = uuid4()
        turn = await turn_repo.create_turn(sid, 1, "wait")
        await turn_repo.update_status(turn["id"], "failed")
        updated = await turn_repo.get_turn(turn["id"])
        assert updated is not None
        assert updated["status"] == "failed"

    async def test_update_status_not_found_raises(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        with pytest.raises(ValueError, match="turn not found"):
            await turn_repo.update_status(uuid4(), "failed")

    async def test_get_processing_turn(self, turn_repo: InMemoryTurnRepository) -> None:
        sid = uuid4()
        t1 = await turn_repo.create_turn(sid, 1, "first")
        await turn_repo.complete_turn(t1["id"], "done", "m", 1.0, {})
        t2 = await turn_repo.create_turn(sid, 2, "second")

        processing = await turn_repo.get_processing_turn(sid)
        assert processing is not None
        assert processing["id"] == t2["id"]
        assert processing["status"] == "processing"

    async def test_get_processing_turn_none(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid = uuid4()
        t = await turn_repo.create_turn(sid, 1, "done")
        await turn_repo.complete_turn(t["id"], "ok", "m", 1.0, {})
        assert await turn_repo.get_processing_turn(sid) is None

    async def test_get_processing_turn_wrong_session(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid1 = uuid4()
        sid2 = uuid4()
        await turn_repo.create_turn(sid1, 1, "hello")
        assert await turn_repo.get_processing_turn(sid2) is None

    async def test_get_turn_by_idempotency_key(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid = uuid4()
        key = uuid4()
        created = await turn_repo.create_turn(sid, 1, "look", idempotency_key=key)
        found = await turn_repo.get_turn_by_idempotency_key(sid, key)
        assert found is not None
        assert found["id"] == created["id"]

    async def test_get_turn_by_idempotency_key_not_found(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid = uuid4()
        assert (await turn_repo.get_turn_by_idempotency_key(sid, uuid4())) is None

    async def test_get_turn_by_idempotency_key_wrong_session(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid1 = uuid4()
        sid2 = uuid4()
        key = uuid4()
        await turn_repo.create_turn(sid1, 1, "x", idempotency_key=key)
        assert (await turn_repo.get_turn_by_idempotency_key(sid2, key)) is None

    async def test_duplicate_turn_number_raises(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid = uuid4()
        await turn_repo.create_turn(sid, 1, "first")
        with pytest.raises(ValueError, match="duplicate turn"):
            await turn_repo.create_turn(sid, 1, "second")

    async def test_duplicate_idempotency_key_raises(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        sid = uuid4()
        key = uuid4()
        await turn_repo.create_turn(sid, 1, "first", idempotency_key=key)
        with pytest.raises(ValueError, match="duplicate idempotency_key"):
            await turn_repo.create_turn(sid, 2, "second", idempotency_key=key)

    async def test_same_idempotency_key_different_session_ok(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        key = uuid4()
        t1 = await turn_repo.create_turn(uuid4(), 1, "a", idempotency_key=key)
        t2 = await turn_repo.create_turn(uuid4(), 1, "b", idempotency_key=key)
        assert t1["id"] != t2["id"]

    async def test_turn_created_at_is_utc(
        self, turn_repo: InMemoryTurnRepository
    ) -> None:
        turn = await turn_repo.create_turn(uuid4(), 1, "go")
        assert turn["created_at"].tzinfo is not None


# =====================================================================
# WorldEventRepository
# =====================================================================


class TestInMemoryWorldEventRepository:
    async def test_create_world_event(
        self, event_repo: InMemoryWorldEventRepository
    ) -> None:
        sid = uuid4()
        tid = uuid4()
        event = await event_repo.create_world_event(
            session_id=sid,
            turn_id=tid,
            event_type="player_moved",
            entity_id="loc-1",
            payload={"name": "forest"},
        )
        assert isinstance(event, WorldEvent)
        assert event.session_id == sid
        assert event.turn_id == tid
        assert event.event_type == "player_moved"
        assert event.entity_id == "loc-1"
        assert event.payload == {"name": "forest"}

    async def test_get_recent_events(
        self, event_repo: InMemoryWorldEventRepository
    ) -> None:
        sid = uuid4()
        for i in range(7):
            await event_repo.create_world_event(
                session_id=sid,
                turn_id=uuid4(),
                event_type=f"event_{i}",
                entity_id=f"ent-{i}",
                payload={},
            )

        recent = await event_repo.get_recent_events(sid)
        assert len(recent) == 5  # default limit

    async def test_get_recent_events_custom_limit(
        self, event_repo: InMemoryWorldEventRepository
    ) -> None:
        sid = uuid4()
        for i in range(10):
            await event_repo.create_world_event(sid, uuid4(), f"evt_{i}", f"e-{i}", {})

        recent = await event_repo.get_recent_events(sid, limit=3)
        assert len(recent) == 3

    async def test_get_recent_events_empty(
        self, event_repo: InMemoryWorldEventRepository
    ) -> None:
        result = await event_repo.get_recent_events(uuid4())
        assert result == []

    async def test_get_recent_events_filters_by_session(
        self, event_repo: InMemoryWorldEventRepository
    ) -> None:
        s1 = uuid4()
        s2 = uuid4()
        await event_repo.create_world_event(s1, uuid4(), "a", "e1", {})
        await event_repo.create_world_event(s2, uuid4(), "b", "e2", {})

        events = await event_repo.get_recent_events(s1)
        assert len(events) == 1
        assert events[0].session_id == s1

    async def test_get_recent_events_ordered_newest_first(
        self, event_repo: InMemoryWorldEventRepository
    ) -> None:
        sid = uuid4()
        e1 = await event_repo.create_world_event(sid, uuid4(), "first", "e1", {})
        e2 = await event_repo.create_world_event(sid, uuid4(), "second", "e2", {})

        recent = await event_repo.get_recent_events(sid, limit=10)
        assert recent[0].created_at >= recent[-1].created_at
        # Most recent should be last created
        assert recent[0].id == e2.id
        assert recent[1].id == e1.id


# =====================================================================
# Protocol structural typing checks
# =====================================================================


class TestProtocolCompliance:
    """Verify in-memory repos satisfy protocol structural typing."""

    def test_player_repo_satisfies_protocol(self) -> None:
        from tta.persistence.repositories import PlayerRepository

        repo: PlayerRepository = InMemoryPlayerRepository()
        assert hasattr(repo, "create_player")
        assert hasattr(repo, "get_player")
        assert hasattr(repo, "get_player_by_handle")

    def test_session_repo_satisfies_protocol(self) -> None:
        from tta.persistence.repositories import SessionRepository

        repo: SessionRepository = InMemorySessionRepository()
        assert hasattr(repo, "create_session")
        assert hasattr(repo, "get_session")
        assert hasattr(repo, "delete_session")

    def test_game_repo_satisfies_protocol(self) -> None:
        from tta.persistence.repositories import GameRepository

        repo: GameRepository = InMemoryGameRepository()
        assert hasattr(repo, "create_game")
        assert hasattr(repo, "get_game")
        assert hasattr(repo, "update_game_status")
        assert hasattr(repo, "list_player_games")

    def test_turn_repo_satisfies_protocol(self) -> None:
        from tta.persistence.repositories import TurnRepository

        repo: TurnRepository = InMemoryTurnRepository()
        assert hasattr(repo, "create_turn")
        assert hasattr(repo, "get_turn")
        assert hasattr(repo, "complete_turn")
        assert hasattr(repo, "update_status")
        assert hasattr(repo, "get_processing_turn")
        assert hasattr(repo, "get_turn_by_idempotency_key")

    def test_world_event_repo_satisfies_protocol(self) -> None:
        from tta.persistence.repositories import (
            WorldEventRepository,
        )

        repo: WorldEventRepository = InMemoryWorldEventRepository()
        assert hasattr(repo, "create_world_event")
        assert hasattr(repo, "get_recent_events")
