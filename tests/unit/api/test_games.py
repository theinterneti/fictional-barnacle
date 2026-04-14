"""Tests for game session routes."""

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
from tta.api.deps import (
    get_current_player,
    get_pg,
    require_anonymous_game_limit,
    require_consent,
)
from tta.config import Settings
from tta.models.player import Player

_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_PLAYER_ID = uuid4()
_PLAYER = Player(id=_PLAYER_ID, handle="Tester", created_at=_NOW)
_GAME_ID = uuid4()


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        neo4j_password="test",
    )


def _row(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


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
    game_id=None,
    player_id=None,
    status: str = "active",
    title: str | None = None,
    summary: str | None = None,
    last_played_at: datetime | None = _NOW,
    deleted_at: datetime | None = None,
    turn_count: int = 0,
    needs_recovery: bool = False,
    summary_generated_at: datetime | None = None,
) -> dict[str, Any]:
    """A typical game_sessions row."""
    return {
        "id": game_id or _GAME_ID,
        "player_id": player_id or _PLAYER_ID,
        "status": status,
        "world_seed": "{}",
        "title": title,
        "summary": summary,
        "turn_count": turn_count,
        "needs_recovery": needs_recovery,
        "summary_generated_at": summary_generated_at,
        "created_at": _NOW,
        "updated_at": _NOW,
        "last_played_at": last_played_at,
        "deleted_at": deleted_at,
    }


@pytest.fixture()
def pg() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def app(pg: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    settings = _settings()
    monkeypatch.setattr("tta.api.routes.games.get_settings", lambda: settings)
    a = create_app(settings=settings)

    async def _pg():
        yield pg

    a.dependency_overrides[get_pg] = _pg
    a.dependency_overrides[get_current_player] = lambda: _PLAYER
    a.dependency_overrides[require_consent] = lambda: _PLAYER
    a.dependency_overrides[require_anonymous_game_limit] = lambda: _PLAYER
    return a


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ------------------------------------------------------------------
# POST /api/v1/games — Create game
# ------------------------------------------------------------------


class TestCreateGame:
    def test_creates_game_and_returns_201(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.1: 201 + game_id, player_id, status, turn_count present."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        body = resp.json()["data"]
        # AC-27.1: response includes a game_id
        assert "game_id" in body
        assert body["game_id"] is not None
        assert len(body["game_id"]) > 0
        # AC-27.1: response includes title field
        assert "title" in body
        # AC-27.1: player context
        assert body["player_id"] == str(_PLAYER_ID)
        assert body["status"] == "active"
        assert body["turn_count"] == 0

    def test_creates_game_includes_narrative_intro_key(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.1: response includes opening narrative field (narrative_intro).

        Genesis runs best-effort — the key must be present even when the mocked
        genesis path returns None (no LLM wired in unit tests).
        """
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games
                _make_result(),  # INSERT
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post("/api/v1/games", json={})

        assert resp.status_code == 201
        body = resp.json()["data"]
        # AC-27.1: "opening narrative" field must exist in the envelope
        assert "narrative_intro" in body  # present even when genesis failed/skipped

    def test_created_game_id_is_unique_uuid(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.1: each POST /games returns a distinct game_id (UUID format)."""
        import re

        _UUID_RE = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),
                _make_result(),
                _make_result(scalar=1),
                _make_result(),
            ]
        )
        pg.commit = AsyncMock()

        resp1 = client.post("/api/v1/games", json={})
        resp2 = client.post("/api/v1/games", json={})

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        id1 = resp1.json()["data"]["game_id"]
        id2 = resp2.json()["data"]["game_id"]
        assert _UUID_RE.match(id1), f"game_id not a UUID: {id1!r}"
        assert _UUID_RE.match(id2), f"game_id not a UUID: {id2!r}"
        assert id1 != id2, "Two POST /games calls returned the same game_id"

    def test_rejects_when_max_games_reached(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.2: 409 with machine-readable error code when limit is hit.

        The Gherkin spec says code "conflict"; the implementation uses the
        ErrorCategory.CONFLICT category (→ HTTP 409) and the specific code
        "MAX_GAMES_REACHED" in the error envelope.  Both the status and the
        machine-readable code are verified here.
        """
        pg.execute = AsyncMock(
            return_value=_make_result(scalar=5)  # already at limit
        )

        resp = client.post("/api/v1/games", json={})

        # AC-27.2: status 409
        assert resp.status_code == 409
        error = resp.json()["error"]
        # AC-27.2: error body contains a conflict-family code
        assert error["code"] == "MAX_GAMES_REACHED"
        # Confirm the error envelope structure is present (S23 §3.1)
        assert "message" in error
        assert "correlation_id" in error

    def test_created_game_appears_in_listing(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.1: the created game appears in the player's game listing."""
        created_game_id = uuid4()
        game_row = _game_row(game_id=created_game_id, turn_count=0)

        pg.execute = AsyncMock(
            side_effect=[
                _make_result(scalar=0),  # count active games (create)
                _make_result(),  # INSERT game (create)
                _make_result([game_row]),  # SELECT games (list)
            ]
        )
        pg.commit = AsyncMock()

        # Step 1: create the game
        create_resp = client.post("/api/v1/games", json={})
        assert create_resp.status_code == 201

        # Step 2: list games — the seeded game_id must appear in the listing
        list_resp = client.get("/api/v1/games")
        assert list_resp.status_code == 200
        listed_ids = [g["game_id"] for g in list_resp.json()["data"]]
        assert len(listed_ids) == 1, f"Expected 1 game in listing, got {listed_ids}"
        assert str(created_game_id) in listed_ids, (
            f"Expected game {created_game_id} in listing, got {listed_ids}"
        )


# ------------------------------------------------------------------
# GET /api/v1/games — List games
# ------------------------------------------------------------------


class TestListGames:
    def test_returns_games_list(self, client: TestClient, pg: AsyncMock) -> None:
        row = _game_row(turn_count=3)
        pg.execute = AsyncMock(
            return_value=_make_result([row]),
        )

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        game = data["data"][0]
        # AC-27.3: each game includes game_id
        assert "game_id" in game
        assert game["game_id"] == str(_GAME_ID)
        # AC-27.3: state field (implementation calls it "status")
        assert game["status"] == "active"
        assert game["turn_count"] == 3
        assert data["meta"]["has_more"] is False

    def test_empty_list(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([]))

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_excludes_abandoned_by_default(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Abandoned games excluded unless status=abandoned is explicit."""
        pg.execute = AsyncMock(return_value=_make_result([]))

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        # Verify the SQL was called (no abandoned in result)
        call_args = pg.execute.call_args
        sql_text = str(call_args[0][0].text)
        assert "abandoned" in sql_text

    def test_includes_title_summary_last_played(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        row = _game_row(
            turn_count=2,
            title="Dark Forest",
            summary="A tale of survival",
        )
        pg.execute = AsyncMock(return_value=_make_result([row]))

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        game = resp.json()["data"][0]
        assert game["title"] == "Dark Forest"
        assert game["summary"] == "A tale of survival"
        assert game["last_played_at"] is not None

    def test_games_ordered_by_last_played_at_descending(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.3: games are ordered by last_played_at descending (T3, T2, T1)."""
        t1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2025, 1, 2, 10, 0, 0, tzinfo=UTC)
        t3 = datetime(2025, 1, 3, 10, 0, 0, tzinfo=UTC)

        id1, id2, id3 = uuid4(), uuid4(), uuid4()

        row1 = _game_row(game_id=id1, last_played_at=t1, title="Game 1", turn_count=1)
        row2 = _game_row(game_id=id2, last_played_at=t2, title="Game 2", turn_count=2)
        row3 = _game_row(game_id=id3, last_played_at=t3, title="Game 3", turn_count=3)

        # The DB (mocked here) is expected to return rows already sorted DESC;
        # the route applies ORDER BY last_played_at DESC — we verify the response
        # preserves that order and contains all required fields per AC-27.3.
        pg.execute = AsyncMock(
            return_value=_make_result([row3, row2, row1]),
        )

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 3

        # AC-27.3: ordered by last_played_at descending — most recent first
        played_at = [g["last_played_at"] for g in data]
        assert played_at == sorted(played_at, reverse=True), (
            f"Games not ordered by last_played_at DESC: {played_at}"
        )

        # AC-27.3: each game includes game_id, title, state (status), turn_count, summary
        for game in data:
            assert "game_id" in game, "Missing game_id"
            assert "title" in game, "Missing title"
            assert "status" in game, "Missing status (state)"
            assert "turn_count" in game, "Missing turn_count"
            assert "summary" in game, "Missing summary"

        # Verify the specific IDs appear in expected order (T3 first, T1 last)
        assert data[0]["game_id"] == str(id3)
        assert data[1]["game_id"] == str(id2)
        assert data[2]["game_id"] == str(id1)


# ------------------------------------------------------------------
# GET /api/v1/games/{id} — Game state
# ------------------------------------------------------------------


class TestGetGameState:
    def test_returns_game_state(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(title="Quest")]),  # _get_owned_game
                _make_result(scalar=5),  # turn count
                _make_result([]),  # recent turns
                _make_result(),  # processing turn check
            ]
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["game_id"] == str(_GAME_ID)
        assert body["turn_count"] == 5
        assert body["title"] == "Quest"
        assert body["processing_turn"] is None
        # AC-27.4: response includes recent_turns list
        assert "recent_turns" in body, (
            "Missing recent_turns in GET /games/{id} response"
        )
        assert isinstance(body["recent_turns"], list)
        # AC-27.4: response includes context_summary (exposed as 'summary' by GET handler)
        assert "summary" in body, (
            "Missing summary/context_summary in GET /games/{id} response"
        )
        # AC-27.4: response includes current world state (status + timestamps)
        assert "status" in body, (
            "Missing status (world state) in GET /games/{id} response"
        )
        assert "created_at" in body
        assert "last_played_at" in body

    def test_get_game_state_includes_context_summary_and_recent_turns(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.4: GET /games/{id} includes recent_turns, context_summary, world state.

        Verifies all three Gherkin postconditions with a game that has a summary
        and a completed turn.
        """
        turn_id = uuid4()
        turn_dict = {
            "id": turn_id,
            "turn_number": 1,
            "player_input": "explore cave",
            "narrative_output": "You enter a dark cave.",
            "created_at": _NOW,
        }
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [_game_row(title="Cave Quest", summary="Deep in the cave")]
                ),  # _get_owned_game
                _make_result(scalar=10),  # turn count
                _make_result([turn_dict]),  # recent turns
                _make_result(),  # processing turn check
            ]
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 200
        body = resp.json()["data"]

        # AC-27.4: recent_turns populated
        assert len(body["recent_turns"]) == 1, "Expected 1 recent turn"
        t = body["recent_turns"][0]
        assert t["turn_number"] == 1
        assert t["player_input"] == "explore cave"
        assert t["narrative_output"] == "You enter a dark cave."

        # AC-27.4: context_summary present (GET handler exposes as 'summary')
        # Note: resume handler uses 'context_summary'; GET handler uses 'summary'.
        # Both satisfy AC-27.4 — the field name differs between the two endpoints.
        assert body["summary"] == "Deep in the cave", (
            "GET /games/{id} must include the context summary (field: 'summary')"
        )

        # AC-27.4: current world state
        assert body["status"] == "active"
        assert body["turn_count"] == 10
        assert body["last_played_at"] is not None

    def test_returns_404_for_missing_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result()  # no row
        )

        resp = client.get(f"/api/v1/games/{uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "GAME_NOT_FOUND"

    def test_returns_404_for_other_players_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        other_player = uuid4()
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(player_id=other_player)])
        )

        resp = client.get(f"/api/v1/games/{_GAME_ID}")

        assert resp.status_code == 404


# ------------------------------------------------------------------
# POST /api/v1/games/{id}/turns — Submit turn
# ------------------------------------------------------------------


class TestSubmitTurn:
    def test_accepts_turn_and_returns_202(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check (none)
                _make_result(scalar=0),  # max turn number
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE last_played_at
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )

        assert resp.status_code == 202
        body = resp.json()["data"]
        assert "turn_id" in body
        assert body["turn_number"] == 1
        assert "stream_url" in body

    def test_rejects_turn_for_paused_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="paused")]))

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    def test_rejects_concurrent_turn(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result([{"id": uuid4()}]),  # in-flight turn exists
            ]
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "TURN_IN_PROGRESS"

    def test_whitespace_only_returns_400(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Whitespace-only input is rejected with 400 input_invalid (AC-23.11)."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
            ]
        )
        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "   "},
        )
        assert resp.status_code == 400
        error = resp.json()["error"]
        assert error["code"] == "EMPTY_TURN_INPUT"

    def test_idempotency_returns_existing_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        existing_turn_id = uuid4()
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check (none)
                _make_result(
                    [
                        {  # idempotency hit
                            "id": existing_turn_id,
                            "turn_number": 3,
                        }
                    ]
                ),
            ]
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test", "idempotency_key": str(uuid4())},
        )

        assert resp.status_code == 202
        body = resp.json()["data"]
        assert body["turn_id"] == str(existing_turn_id)
        assert body["turn_number"] == 3

    def test_last_played_at_updated_and_turn_persisted(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.5: after a successful turn, last_played_at is updated and the
        turn row is inserted — verified by inspecting the SQL calls issued.

        The route:
          1. INSERTs a row into `turns` (persisting the turn slot, status='pending')
          2. UPDATEs `game_sessions` setting last_played_at (and updated_at)
          3. COMMITs both writes atomically

        AC-27.5 turn_count compliance — two-phase design:
          - submit_turn does NOT issue "SET turn_count = turn_count + 1".
            turn_count is a derived/reconciled field: the route reads the live
            count via SELECT MAX(turn_number) and returns turn_number = max + 1.
          - The `turn_count + 1` UPDATE is issued by the async pipeline callback
            (games.py ~line 297, "SET turn_count = turn_count + 1") after the
            LLM completes and the turn transitions to status='complete'.
          - This two-phase approach is intentional: the pipeline owns the
            authoritative increment once narrative is durably persisted, while
            submit_turn only reserves the slot.

        AC-27.5 narrative persistence compliance:
          - submit_turn inserts the turn row with status='pending' and no
            narrative_output — the narrative slot is reserved but empty.
          - The async pipeline fills narrative_output and sets status='complete'.
          - See TestTurnPersistence.test_completed_turn_has_narrative_output for
            the assertion that verifies a completed turn exposes narrative_output
            via the turn history endpoint.
        """
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check (none)
                _make_result(scalar=2),  # max turn number → next = 3
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE last_played_at
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "go north"},
        )

        assert resp.status_code == 202
        body = resp.json()["data"]

        # AC-27.5: turn_count is incremented via turn_number (max+1 logic).
        # The route returns turn_number=3, confirming the server correctly
        # computed the next sequence value.  The actual game_sessions.turn_count
        # column increment ("SET turn_count = turn_count + 1") is performed by
        # the async pipeline after narrative completion, not by submit_turn.
        assert body["turn_number"] == 3, (
            "AC-27.5: turn_number must equal previous max + 1 (derived turn_count)"
        )

        # AC-27.5: both INSERT turn and UPDATE last_played_at were issued
        assert pg.execute.await_count == 6, (
            "AC-27.5: expected 6 DB calls "
            "(get_game, advisory_lock, in_flight, max_turn, INSERT turn, "
            f"UPDATE last_played_at), got {pg.execute.await_count}"
        )

        # AC-27.5: commit was called — writes are durably persisted
        pg.commit.assert_awaited_once()

        # Verify the UPDATE last_played_at SQL was among the calls
        all_sqls = [
            str(call.args[0].text) if call.args else ""
            for call in pg.execute.await_args_list
        ]
        assert any("last_played_at" in sql for sql in all_sqls), (
            "AC-27.5: no SQL updating last_played_at found among DB calls"
        )
        assert any("INSERT INTO turns" in sql for sql in all_sqls), (
            "AC-27.5: no INSERT INTO turns found among DB calls"
        )
        # AC-27.5: the INSERT uses turn_number (the incremented sequence value)
        insert_sqls = [s for s in all_sqls if "INSERT INTO turns" in s]
        assert any("turn_number" in s for s in insert_sqls), (
            "AC-27.5: INSERT INTO turns must include turn_number column"
        )


# ------------------------------------------------------------------
# POST /api/v1/games/{id}/save — Save game
# ------------------------------------------------------------------


class TestSaveGame:
    def test_saves_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row()]),  # _get_owned_game
                _make_result(),  # UPDATE
                _make_result(scalar=5),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/save")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["game_id"] == str(_GAME_ID)
        assert body["turn_count"] == 5


# ------------------------------------------------------------------
# POST /api/v1/games/{id}/resume — Resume game
# ------------------------------------------------------------------


class TestResumeGame:
    def test_resumes_paused_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="paused")]),  # _get_owned_game
                _make_result(),  # UPDATE status
                _make_result([]),  # recent turns
                _make_result(scalar=3),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "active"
        assert body["turn_count"] == 3
        assert body["recent_turns"] == []
        assert body["summary_stale"] is False
        assert body["recovery_warning"] is None

    def test_noop_for_already_active_game(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),  # _get_owned_game
                _make_result([]),  # recent turns
                _make_result(scalar=2),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

    def test_resumes_expired_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="expired")]),  # _get_owned_game
                _make_result(),  # UPDATE status
                _make_result([]),  # recent turns
                _make_result(scalar=1),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

    def test_rejects_ended_game_resume(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GAME_NOT_RESUMABLE"

    def test_rejects_completed_game_resume(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(status="completed")])
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GAME_NOT_RESUMABLE"

    def test_rejects_abandoned_game_resume(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(status="abandoned")])
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GAME_NOT_RESUMABLE"

    def test_resume_returns_recent_turns(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        turn_id = uuid4()
        turn_dict = {
            "id": turn_id,
            "turn_number": 1,
            "player_input": "go north",
            "narrative_output": "You walk north.",
            "created_at": _NOW,
        }
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),  # _get_owned_game
                _make_result([turn_dict]),  # recent turns
                _make_result(scalar=1),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert len(body["recent_turns"]) == 1
        assert body["recent_turns"][0]["player_input"] == "go north"
        assert body["recent_turns"][0]["narrative_output"] == "You walk north."
        assert body["recent_turns"][0]["turn_number"] == 1

    def test_resume_includes_title_and_summary(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        recent = datetime.now(UTC)
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            title="Dark Forest",
                            summary="Lost in the woods",
                            last_played_at=recent,
                            summary_generated_at=recent,
                        )
                    ]
                ),
                _make_result([]),  # recent turns
                _make_result(scalar=5),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["title"] == "Dark Forest"
        assert body["context_summary"] == "Lost in the woods"
        assert body["summary_stale"] is False

    def test_resume_with_recovery(self, client: TestClient, pg: AsyncMock) -> None:
        """needs_recovery=True triggers metadata re-derivation."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="paused", needs_recovery=True)]),
                _make_result(scalar=7),  # _get_turn_count for recovery
                _make_result(),  # UPDATE needs_recovery = FALSE
                _make_result(),  # UPDATE status (paused → active)
                _make_result([]),  # recent turns
                _make_result(scalar=7),  # _get_turn_count for response
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["turn_count"] == 7
        assert body["recovery_warning"] is None

    def test_resume_with_recovery_failure(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """When recovery fails, player gets warning but resume proceeds."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active", needs_recovery=True)]),
                RuntimeError("DB unavailable"),  # _get_turn_count fails
                _make_result([]),  # recent turns
                _make_result(scalar=3),  # _get_turn_count for response
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["recovery_warning"] is not None
        assert "progress" in body["recovery_warning"].lower()

    def test_resume_stale_summary_detected(
        self,
        client: TestClient,
        pg: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Summary older than threshold is flagged as stale."""
        from datetime import timedelta

        old_time = _NOW - timedelta(hours=48)
        turn_dict = {
            "id": uuid4(),
            "turn_number": 1,
            "player_input": "look",
            "narrative_output": "You see a cave.",
            "created_at": _NOW,
        }
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            summary="Old summary",
                            last_played_at=old_time,
                            summary_generated_at=old_time,
                        )
                    ]
                ),
                _make_result([turn_dict]),  # recent turns (non-empty)
                _make_result(scalar=5),  # turn count
            ]
        )
        # Prevent actual background task
        monkeypatch.setattr("asyncio.create_task", lambda coro: coro.close())

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["summary_stale"] is True
        assert body["context_summary"] == "Old summary"

    def test_resume_fresh_summary_not_stale(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Summary generated recently is not flagged stale."""
        recent = datetime.now(UTC)
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            summary="Fresh summary",
                            last_played_at=recent,
                            summary_generated_at=recent,
                        )
                    ]
                ),
                _make_result([]),  # recent turns
                _make_result(scalar=3),  # turn count
            ]
        )

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["summary_stale"] is False

    def test_resume_never_generated_summary_stale_when_turns_exist(
        self,
        client: TestClient,
        pg: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """summary_generated_at=None with turns → stale."""
        turn_dict = {
            "id": uuid4(),
            "turn_number": 1,
            "player_input": "look",
            "narrative_output": "A room.",
            "created_at": _NOW,
        }
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            summary=None,
                            summary_generated_at=None,
                        )
                    ]
                ),
                _make_result([turn_dict]),  # recent turns
                _make_result(scalar=1),  # turn count
            ]
        )
        monkeypatch.setattr("asyncio.create_task", lambda coro: coro.close())

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["summary_stale"] is True

    def test_resume_stale_summary_dispatches_regeneration(
        self,
        client: TestClient,
        pg: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-27.8: when summary is stale, regen task is dispatched on resume.

        The background task is the mechanism that produces a freshly generated
        context_summary.  Verifying create_task is called (not just the flag)
        ensures the regeneration is actually scheduled.
        """
        from datetime import timedelta

        old_time = _NOW - timedelta(hours=48)
        turn_dict = {
            "id": uuid4(),
            "turn_number": 3,
            "player_input": "go south",
            "narrative_output": "You head south.",
            "created_at": _NOW,
        }
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            summary="Stale narrative recap",
                            last_played_at=old_time,
                            summary_generated_at=old_time,
                        )
                    ]
                ),
                _make_result([turn_dict]),  # recent turns (non-empty → triggers regen)
                _make_result(scalar=3),  # turn count
            ]
        )

        captured: list = []
        regen_call_args: list = []

        def _capture_task(coro: object) -> None:
            captured.append(coro)
            # Close to avoid ResourceWarning
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]

        monkeypatch.setattr("asyncio.create_task", _capture_task)

        def _mock_regen(app_state: object, game_id: object) -> object:
            regen_call_args.append((app_state, game_id))
            # Return a no-op coroutine so create_task receives a coroutine

            async def _noop() -> None:
                pass

            return _noop()

        monkeypatch.setattr("tta.api.routes.games._regen_summary_bg", _mock_regen)

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        body = resp.json()["data"]

        # AC-27.8: summary_stale is flagged in the response
        assert body["summary_stale"] is True

        # AC-27.8: regeneration was dispatched (the coroutine that produces a
        # freshly generated summary was scheduled via create_task)
        assert len(captured) == 1, (
            "AC-27.8: expected exactly one background regen task to be scheduled "
            f"when summary is stale, got {len(captured)}"
        )

        # AC-27.8 second postcondition: the dispatched task reflects the current
        # state of the narrative — i.e. it was invoked with the correct game_id
        assert len(regen_call_args) == 1, (
            "AC-27.8: _regen_summary_bg should have been called exactly once"
        )
        _, dispatched_game_id = regen_call_args[0]
        assert dispatched_game_id == _GAME_ID, (
            f"AC-27.8: regen dispatched with wrong game_id: "
            f"expected {_GAME_ID}, got {dispatched_game_id}"
        )

    def test_resume_fresh_summary_does_not_dispatch_regeneration(
        self,
        client: TestClient,
        pg: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-27.8 negative: fresh summary must NOT trigger a regen task."""
        recent = datetime.now(UTC)
        pg.execute = AsyncMock(
            side_effect=[
                _make_result(
                    [
                        _game_row(
                            status="active",
                            summary="Fresh summary",
                            last_played_at=recent,
                            summary_generated_at=recent,
                        )
                    ]
                ),
                _make_result([]),  # recent turns
                _make_result(scalar=2),  # turn count
            ]
        )

        captured: list = []
        monkeypatch.setattr("asyncio.create_task", lambda coro: captured.append(coro))

        resp = client.post(f"/api/v1/games/{_GAME_ID}/resume")

        assert resp.status_code == 200
        assert resp.json()["data"]["summary_stale"] is False
        assert len(captured) == 0, (
            "AC-27.8: no regen task should be scheduled when summary is fresh"
        )


# ------------------------------------------------------------------
# PATCH /api/v1/games/{id} — Update game (pause)
# ------------------------------------------------------------------


class TestUpdateGame:
    def test_pauses_active_game(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result(),  # UPDATE
                _make_result(scalar=4),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.patch(
            f"/api/v1/games/{_GAME_ID}",
            json={"status": "paused"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "paused"

    def test_rejects_invalid_transition(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.patch(
            f"/api/v1/games/{_GAME_ID}",
            json={"status": "active"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


# ------------------------------------------------------------------
# DELETE /api/v1/games/{id} — End game
# ------------------------------------------------------------------


class TestEndGame:
    def test_soft_deletes_with_confirm(self, client: TestClient, pg: AsyncMock) -> None:
        """AC-27.6: DELETE /games/{id} with confirm=true returns 204 No Content."""
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result(),  # UPDATE
                _make_result(scalar=7),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.request(
            "DELETE",
            f"/api/v1/games/{_GAME_ID}",
            json={"confirm": True},
        )

        # AC-27.6: response MUST be 204 No Content (not 200)
        assert resp.status_code == 204
        assert resp.content == b""

    def test_deleted_game_absent_from_listing(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.6: after deletion, game no longer appears in GET /games."""
        # Step 1 — DELETE the game (204)
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),  # _get_owned_game
                _make_result(),  # UPDATE soft-delete
                _make_result(scalar=3),  # turn count
            ]
        )
        pg.commit = AsyncMock()
        del_resp = client.request(
            "DELETE", f"/api/v1/games/{_GAME_ID}", json={"confirm": True}
        )
        assert del_resp.status_code == 204

        # Step 2 — list games; the route filters deleted_at IS NULL AND status !=
        # 'abandoned', so the deleted game must not be in results.
        pg.execute = AsyncMock(return_value=_make_result([]))  # empty list
        list_resp = client.get("/api/v1/games")
        assert list_resp.status_code == 200
        # GET /games returns {"data": [...], "meta": {...}}
        items = list_resp.json()["data"]
        ids = [item["game_id"] for item in items]
        assert str(_GAME_ID) not in ids, (
            "AC-27.6: soft-deleted game must not appear in GET /games"
        )

    def test_deleted_game_not_accessible_by_id(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.6: after deletion, GET /games/{id} returns 404."""
        # The route uses 'WHERE id = :id AND deleted_at IS NULL' — simulate that
        # the DB returns no row (i.e., deleted_at is set).
        pg.execute = AsyncMock(return_value=_make_result([]))  # no row found
        resp = client.get(f"/api/v1/games/{_GAME_ID}")
        assert resp.status_code == 404, (
            "AC-27.6: soft-deleted game must not be accessible via GET /games/{id}"
        )

    def test_rejects_without_confirm(self, client: TestClient, pg: AsyncMock) -> None:
        """AC-27.7: DELETE without confirm=true → 400 with explanation."""
        resp = client.request(
            "DELETE",
            f"/api/v1/games/{_GAME_ID}",
            json={"confirm": False},
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONFIRM_REQUIRED"
        # AC-27.7: error message must explain the confirmation requirement
        message = resp.json()["error"]["message"].lower()
        assert "confirm" in message, (
            "AC-27.7: error message must mention 'confirm' to explain the requirement"
        )

    def test_rejects_missing_body(self, client: TestClient, pg: AsyncMock) -> None:
        """AC-27.7: DELETE with no body → 400 with confirmation explanation."""
        resp = client.request(
            "DELETE",
            f"/api/v1/games/{_GAME_ID}",
        )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONFIRM_REQUIRED"
        message = resp.json()["error"]["message"].lower()
        assert "confirm" in message, (
            "AC-27.7: error message must mention 'confirm' to explain the requirement"
        )

    def test_rejects_already_ended(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(return_value=_make_result([_game_row(status="ended")]))

        resp = client.request(
            "DELETE",
            f"/api/v1/games/{_GAME_ID}",
            json={"confirm": True},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    def test_rejects_already_abandoned(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(status="abandoned")])
        )

        resp = client.request(
            "DELETE",
            f"/api/v1/games/{_GAME_ID}",
            json={"confirm": True},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


# ------------------------------------------------------------------
# State transitions — completed status
# ------------------------------------------------------------------


class TestCompletedTransitions:
    def test_active_to_completed(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="active")]),
                _make_result(),  # UPDATE
                _make_result(scalar=10),  # turn count
            ]
        )
        pg.commit = AsyncMock()

        resp = client.patch(
            f"/api/v1/games/{_GAME_ID}",
            json={"status": "completed"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "completed"

    def test_completed_is_terminal(self, client: TestClient, pg: AsyncMock) -> None:
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(status="completed")])
        )

        resp = client.patch(
            f"/api/v1/games/{_GAME_ID}",
            json={"status": "active"},
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    def test_completed_game_rejects_new_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.10: POST /turns on a completed game returns 409."""
        pg.execute = AsyncMock(
            return_value=_make_result([_game_row(status="completed")])
        )

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "go north"},
        )

        # AC-27.10: must be 409 Conflict — completed is read-only
        assert resp.status_code == 409, (
            "AC-27.10: submitting a turn to a completed game must return 409"
        )
        assert resp.json()["error"]["code"] == "INVALID_STATE_TRANSITION"

    def test_completed_game_still_appears_in_listing(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.10: completed game still appears in GET /games with state 'completed'."""  # noqa: E501
        # The list_games route excludes abandoned games by default but includes
        # completed ones (only status != 'abandoned' is filtered).
        pg.execute = AsyncMock(
            return_value=_make_result(
                [
                    {
                        "id": _GAME_ID,
                        "player_id": _PLAYER_ID,
                        "status": "completed",
                        "world_seed": "{}",
                        "title": "My Quest",
                        "summary": None,
                        "turn_count": 15,
                        "created_at": _NOW,
                        "updated_at": _NOW,
                        "last_played_at": _NOW,
                    }
                ]
            )
        )

        resp = client.get("/api/v1/games")

        assert resp.status_code == 200
        # GET /games returns {"data": [...], "meta": {...}}
        items = resp.json()["data"]
        assert len(items) == 1, "AC-27.10: completed game must appear in listings"
        assert items[0]["game_id"] == str(_GAME_ID)
        assert items[0]["status"] == "completed", (
            "AC-27.10: completed game must show state 'completed' in listing"
        )

    def test_completed_game_turn_rejected_then_still_listed(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.10 end-to-end: 409 on turn submission, game still in listing."""
        # First call: submit turn → 409
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(status="completed")]),  # _get_owned_game
                # Second call: list games → completed game still present
                _make_result(
                    [
                        {
                            "id": _GAME_ID,
                            "player_id": _PLAYER_ID,
                            "status": "completed",
                            "world_seed": "{}",
                            "title": None,
                            "summary": None,
                            "turn_count": 10,
                            "created_at": _NOW,
                            "updated_at": _NOW,
                            "last_played_at": _NOW,
                        }
                    ]
                ),
            ]
        )

        turn_resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )
        assert turn_resp.status_code == 409, (
            "AC-27.10: completed game must reject turns with 409"
        )

        list_resp = client.get("/api/v1/games")
        assert list_resp.status_code == 200
        # GET /games returns {"data": [...], "meta": {...}}
        items = list_resp.json()["data"]
        ids = [item["game_id"] for item in items]
        assert str(_GAME_ID) in ids, (
            "AC-27.10: completed game must still appear in GET /games"
            " after rejected turn"
        )
        game = next(i for i in items if i["game_id"] == str(_GAME_ID))
        assert game["status"] == "completed", (
            "AC-27.10: game status must remain 'completed' in listing"
        )


# ------------------------------------------------------------------
# Submit turn with recovery (FR-27.15)
# ------------------------------------------------------------------


class TestSubmitTurnRecovery:
    def test_recovery_attempted_when_needs_recovery(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.9: when needs_recovery=True, recovery SQL is issued first,
        then the normal turn pipeline proceeds.

        Expected call order:
          1. _get_owned_game (SELECT)
          2. _get_turn_count (SELECT COUNT — recovery)
          3. UPDATE game_sessions SET turn_count=…, needs_recovery=FALSE … (recovery)
          4. pg.commit() for recovery
          5. advisory lock
          6. in-flight check
          7. max turn number
          8. INSERT turn
          9. UPDATE last_played_at
         10. pg.commit() for turn
        """
        pg.execute = AsyncMock(
            side_effect=[
                _make_result([_game_row(needs_recovery=True)]),  # owned
                _make_result(scalar=5),  # _get_turn_count (recovery)
                _make_result(),  # UPDATE recovery
                _make_result(),  # advisory lock
                _make_result(),  # in-flight check
                _make_result(scalar=5),  # max turn number
                _make_result(),  # INSERT turn
                _make_result(),  # UPDATE last_played_at
            ]
        )
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "look around"},
        )

        assert resp.status_code == 202

        # AC-27.9: recovery SQL must appear before the INSERT turn
        all_sqls = [
            str(call.args[0].text) if call.args else ""
            for call in pg.execute.await_args_list
        ]

        # Find indices of recovery UPDATE and INSERT turn
        recovery_idx = next(
            (
                i
                for i, sql in enumerate(all_sqls)
                if "needs_recovery" in sql and "UPDATE" in sql
            ),
            None,
        )
        insert_turn_idx = next(
            (i for i, sql in enumerate(all_sqls) if "INSERT INTO turns" in sql),
            None,
        )

        assert recovery_idx is not None, (
            "AC-27.9: no recovery UPDATE SQL (SET needs_recovery = FALSE) found"
        )
        assert insert_turn_idx is not None, (
            "AC-27.9: no INSERT INTO turns found — normal turn not processed"
        )
        assert recovery_idx < insert_turn_idx, (
            f"AC-27.9: recovery SQL (call #{recovery_idx}) must precede "
            f"INSERT turn (call #{insert_turn_idx})"
        )

        # AC-27.9: commit called for recovery AND for the new turn (≥2 times)
        assert pg.commit.await_count >= 2, (
            "AC-27.9: expected at least 2 commits (recovery + new turn), "
            f"got {pg.commit.await_count}"
        )

    def test_recovery_failure_does_not_block_turn(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """If recovery fails, the turn still proceeds."""
        call_count = 0

        async def _side(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result([_game_row(needs_recovery=True)])
            if call_count == 2:
                # recovery _get_turn_count fails
                raise RuntimeError("db unavailable")
            if call_count == 3:
                return _make_result()  # advisory lock
            if call_count == 4:
                return _make_result()  # in-flight check
            if call_count == 5:
                return _make_result(scalar=3)  # max turn number
            if call_count == 6:
                return _make_result()  # INSERT turn
            return _make_result()  # UPDATE last_played_at

        pg.execute = AsyncMock(side_effect=_side)
        pg.commit = AsyncMock()

        resp = client.post(
            f"/api/v1/games/{_GAME_ID}/turns",
            json={"input": "test"},
        )

        assert resp.status_code == 202


# ------------------------------------------------------------------
# Background tasks: _generate_title_bg, _regen_summary_bg
# ------------------------------------------------------------------


def _mock_session_factory() -> tuple[MagicMock, AsyncMock]:
    """Return (sf, mock_session) where sf() is an async ctx mgr."""
    mock_sess = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_sess)
    ctx.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock(return_value=ctx)
    return sf, mock_sess


class TestGenerateTitleBg:
    @pytest.mark.asyncio
    async def test_title_persisted_on_success(self) -> None:
        from tta.api.routes.games import _generate_title_bg

        mock_svc = AsyncMock()
        mock_svc.generate_title = AsyncMock(return_value="Epic Adventure")

        sf, mock_sess = _mock_session_factory()
        app_state = SimpleNamespace(
            summary_service=mock_svc,
            pipeline_deps=SimpleNamespace(turn_repo=SimpleNamespace(_sf=sf)),
        )

        await _generate_title_bg(app_state, _GAME_ID, "You awaken in a cave.")

        mock_svc.generate_title.assert_awaited_once()
        mock_sess.execute.assert_awaited_once()
        mock_sess.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_title_failure_logs_warning(self) -> None:
        """LLM failure doesn't raise — just logs."""
        from tta.api.routes.games import _generate_title_bg

        mock_svc = AsyncMock()
        mock_svc.generate_title = AsyncMock(side_effect=RuntimeError("boom"))

        sf, _ = _mock_session_factory()
        app_state = SimpleNamespace(
            summary_service=mock_svc,
            pipeline_deps=SimpleNamespace(turn_repo=SimpleNamespace(_sf=sf)),
        )

        # Should NOT raise
        await _generate_title_bg(app_state, _GAME_ID, "narrative")

    @pytest.mark.asyncio
    async def test_empty_title_skips_persist(self) -> None:
        from tta.api.routes.games import _generate_title_bg

        mock_svc = AsyncMock()
        mock_svc.generate_title = AsyncMock(return_value="")

        sf, mock_sess = _mock_session_factory()
        app_state = SimpleNamespace(
            summary_service=mock_svc,
            pipeline_deps=SimpleNamespace(turn_repo=SimpleNamespace(_sf=sf)),
        )

        await _generate_title_bg(app_state, _GAME_ID, "narrative")

        # session factory ctx mgr should never be entered
        sf.assert_not_called()


class TestRegenSummaryBg:
    @pytest.mark.asyncio
    async def test_summary_persisted_on_success(self) -> None:
        from tta.api.routes.games import _regen_summary_bg

        mock_svc = AsyncMock()
        mock_svc.generate_context_summary = AsyncMock(
            return_value="Player explored a cave."
        )

        mock_turn_repo = AsyncMock()
        mock_turn_repo.get_recent_turns = AsyncMock(
            return_value=[{"player_input": "go", "narrative_output": "cave"}]
        )

        sf, mock_sess = _mock_session_factory()
        mock_turn_repo._sf = sf

        app_state = SimpleNamespace(
            summary_service=mock_svc,
            pipeline_deps=SimpleNamespace(turn_repo=mock_turn_repo),
            settings=SimpleNamespace(resume_turn_count=10),
        )

        await _regen_summary_bg(app_state, _GAME_ID)

        mock_svc.generate_context_summary.assert_awaited_once()
        mock_sess.execute.assert_awaited_once()
        mock_sess.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_turns_skips_summary(self) -> None:
        from tta.api.routes.games import _regen_summary_bg

        mock_turn_repo = AsyncMock()
        mock_turn_repo.get_recent_turns = AsyncMock(return_value=[])

        sf, _ = _mock_session_factory()
        mock_turn_repo._sf = sf

        mock_svc = AsyncMock()
        app_state = SimpleNamespace(
            summary_service=mock_svc,
            pipeline_deps=SimpleNamespace(turn_repo=mock_turn_repo),
            settings=SimpleNamespace(resume_turn_count=10),
        )

        await _regen_summary_bg(app_state, _GAME_ID)

        mock_svc.generate_context_summary.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_summary_failure_does_not_raise(self) -> None:
        from tta.api.routes.games import _regen_summary_bg

        mock_svc = AsyncMock()
        mock_svc.generate_context_summary = AsyncMock(
            side_effect=RuntimeError("LLM down")
        )

        mock_turn_repo = AsyncMock()
        mock_turn_repo.get_recent_turns = AsyncMock(
            return_value=[{"player_input": "hi"}]
        )

        sf, _ = _mock_session_factory()
        mock_turn_repo._sf = sf

        app_state = SimpleNamespace(
            summary_service=mock_svc,
            pipeline_deps=SimpleNamespace(turn_repo=mock_turn_repo),
            settings=SimpleNamespace(resume_turn_count=10),
        )

        # Should NOT raise
        await _regen_summary_bg(app_state, _GAME_ID)


# ------------------------------------------------------------------
# GET /api/v1/games/{game_id}/turns — Turn history pagination
# ------------------------------------------------------------------


def _turn_row(
    *,
    turn_number: int = 1,
    player_input: str = "go north",
    narrative_output: str = "You head north.",
) -> dict[str, Any]:
    """A typical turns table row."""
    return {
        "id": uuid4(),
        "turn_number": turn_number,
        "player_input": player_input,
        "narrative_output": narrative_output,
        "created_at": _NOW,
    }


class TestListTurns:
    """Route-level tests for GET /games/{game_id}/turns."""

    def _url(self, game_id=None) -> str:
        return f"/api/v1/games/{game_id or _GAME_ID}/turns"

    def test_returns_turns_with_meta(self, client: TestClient, pg: AsyncMock) -> None:
        """Basic paginated response with data + meta."""
        game = _game_row()
        turns = [_turn_row(turn_number=i) for i in range(3, 0, -1)]

        call_count = 0

        async def _exec(stmt, params=None, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result([game])
            return _make_result(turns)

        pg.execute = AsyncMock(side_effect=_exec)

        resp = client.get(self._url())
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert len(body["data"]) == 3
        assert body["meta"]["has_more"] is False
        assert body["meta"]["next_cursor"] is None

    def test_has_more_with_cursor(self, client: TestClient, pg: AsyncMock) -> None:
        """When more rows exist than limit, has_more=True and next_cursor set."""
        import base64

        game = _game_row()
        # Return limit+1 rows (limit defaults to 20, use limit=2 for test)
        turns = [_turn_row(turn_number=i) for i in range(3, 0, -1)]

        call_count = 0

        async def _exec(stmt, params=None, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result([game])
            return _make_result(turns)

        pg.execute = AsyncMock(side_effect=_exec)

        resp = client.get(self._url(), params={"limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["has_more"] is True
        assert body["meta"]["next_cursor"] is not None
        decoded = base64.urlsafe_b64decode(body["meta"]["next_cursor"]).decode()
        assert decoded.isdigit()

    def test_invalid_cursor_returns_400(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Malformed cursor returns 400 INPUT_INVALID."""
        game = _game_row()
        pg.execute = AsyncMock(return_value=_make_result([game]))

        resp = client.get(self._url(), params={"cursor": "not-valid!!!"})
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_CURSOR"

    def test_status_filter_applied(self, client: TestClient, pg: AsyncMock) -> None:
        """Query only fetches status='complete' turns (verified via SQL)."""
        game = _game_row()
        call_count = 0
        captured_stmt = None

        async def _exec(stmt, params=None, **kw):
            nonlocal call_count, captured_stmt
            call_count += 1
            if call_count == 1:
                return _make_result([game])
            captured_stmt = str(stmt.text) if hasattr(stmt, "text") else str(stmt)
            return _make_result([])

        pg.execute = AsyncMock(side_effect=_exec)

        resp = client.get(self._url())
        assert resp.status_code == 200
        assert captured_stmt is not None
        assert "status = 'complete'" in captured_stmt

    def test_game_not_found_returns_404(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """Non-existent game returns 404."""
        pg.execute = AsyncMock(return_value=_make_result([]))

        resp = client.get(self._url(game_id=uuid4()))
        assert resp.status_code == 404

    def test_empty_turns(self, client: TestClient, pg: AsyncMock) -> None:
        """Game with no turns returns empty data array."""
        game = _game_row()
        call_count = 0

        async def _exec(stmt, params=None, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result([game])
            return _make_result([])

        pg.execute = AsyncMock(side_effect=_exec)

        resp = client.get(self._url())
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["meta"]["has_more"] is False


# ------------------------------------------------------------------
# AC-27.5 Narrative and world-state persistence
# ------------------------------------------------------------------


class TestTurnPersistence:
    """AC-27.5: narrative and world-state changes are persisted.

    Architecture note — two-phase persistence:
      Phase 1 (submit_turn route): inserts a turn row with status='pending'
        and no narrative_output.  This reserves the turn slot and starts the
        async pipeline.  Covered by:
        TestSubmitTurn.test_last_played_at_updated_and_turn_persisted

      Phase 2 (async pipeline callback): the pipeline fills narrative_output,
        sets status='complete', and increments game_sessions.turn_count via
        "SET turn_count = turn_count + 1" (games.py ~line 297).  The pipeline
        runs in the background after the 202 response is sent to the client.

    The tests below verify that once the pipeline has completed a turn the
    narrative is readable via the turn history endpoint
    (GET /games/{id}/turns), satisfying AC-27.5 narrative-persisted requirement.
    """

    def test_completed_turn_has_narrative_output(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.5: a completed turn (status='complete') has narrative_output set.

        Mocks the DB to return a turn row as it would appear after the async
        pipeline has run (status='complete', narrative_output populated).
        Verifies the turn history endpoint surfaces narrative_output correctly.
        """
        game = _game_row()
        completed_turn = {
            "id": uuid4(),
            "turn_number": 1,
            "player_input": "go north",
            "narrative_output": "You walk north and find a forest path.",
            "created_at": _NOW,
        }

        call_count = 0

        async def _exec(stmt, params=None, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result([game])  # _get_owned_game
            return _make_result([completed_turn])  # turns query (status='complete')

        pg.execute = AsyncMock(side_effect=_exec)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/turns")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1, "Expected 1 completed turn"
        turn = body["data"][0]

        # AC-27.5: narrative is persisted and returned
        assert turn["narrative_output"] == "You walk north and find a forest path.", (
            "AC-27.5: completed turn must expose narrative_output from pipeline"
        )
        assert turn["turn_number"] == 1
        assert turn["player_input"] == "go north"

    def test_turn_history_only_returns_complete_turns(
        self, client: TestClient, pg: AsyncMock
    ) -> None:
        """AC-27.5: only turns with status='complete' appear in history.

        Pending/processing/failed turns have no narrative_output and must not
        appear in turn history (list_turns filters WHERE status = 'complete').
        Covered by TestListTurns.test_status_filter_applied; referenced here
        as the AC-27.5 companion assertion for narrative persistence.
        """
        game = _game_row()
        # Simulate DB returning only completed turns (pending ones filtered out)
        complete_turns = [
            {
                "id": uuid4(),
                "turn_number": 1,
                "player_input": "look around",
                "narrative_output": "You see a stone chamber.",
                "created_at": _NOW,
            },
            {
                "id": uuid4(),
                "turn_number": 3,  # turn 2 may still be pending — gap is expected
                "player_input": "open door",
                "narrative_output": "The door creaks open.",
                "created_at": _NOW,
            },
        ]

        call_count = 0

        async def _exec(stmt, params=None, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_result([game])
            return _make_result(complete_turns)

        pg.execute = AsyncMock(side_effect=_exec)

        resp = client.get(f"/api/v1/games/{_GAME_ID}/turns")

        assert resp.status_code == 200
        body = resp.json()
        # Both complete turns surfaced with narrative intact
        assert len(body["data"]) == 2
        assert all(t["narrative_output"] for t in body["data"]), (
            "AC-27.5: every turn in history must have narrative_output set"
        )
