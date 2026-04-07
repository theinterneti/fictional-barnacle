"""Tests for core domain models.

Validates Pydantic v2 models defined in tta.models against
the contracts in system.md §4.3 and the spec acceptance criteria.
"""

from datetime import datetime
from uuid import UUID, uuid4

from tta.models import (
    GameSession,
    GameState,
    GameStatus,
    ParsedIntent,
    Player,
    PlayerSession,
    TokenCount,
    TurnRequest,
    TurnState,
    TurnStatus,
)

# ── TurnState ────────────────────────────────────────────────────────────


class TestTurnState:
    """TurnState is the pipeline's internal contract."""

    def test_instantiation_required_fields(self):
        sid = uuid4()
        ts = TurnState(
            session_id=sid,
            turn_number=1,
            player_input="look around",
            game_state={"location": "tavern"},
        )
        assert ts.session_id == sid
        assert ts.turn_number == 1
        assert ts.player_input == "look around"
        assert ts.game_state == {"location": "tavern"}

    def test_optional_fields_default_none(self):
        ts = TurnState(
            session_id=uuid4(),
            turn_number=0,
            player_input="",
            game_state={},
        )
        assert ts.parsed_intent is None
        assert ts.world_context is None
        assert ts.narrative_history is None
        assert ts.generation_prompt is None
        assert ts.narrative_output is None
        assert ts.model_used is None
        assert ts.token_count is None
        assert ts.latency_ms is None
        assert ts.delivered is False
        assert ts.safety_flags == []
        assert ts.status == TurnStatus.processing

    def test_all_optional_fields_populated(self):
        intent = ParsedIntent(
            intent="explore", confidence=0.95, entities={"dir": "north"}
        )
        tokens = TokenCount(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        ts = TurnState(
            session_id=uuid4(),
            turn_number=3,
            player_input="go north",
            game_state={"hp": 10},
            parsed_intent=intent,
            world_context={"biome": "forest"},
            narrative_history=[{"role": "assistant", "text": "..."}],
            generation_prompt="You are…",
            narrative_output="You walk north.",
            model_used="gpt-4o",
            token_count=tokens,
            delivered=True,
            latency_ms=123.4,
            safety_flags=["mild_violence"],
            status=TurnStatus.complete,
        )
        assert ts.parsed_intent == intent
        assert ts.token_count.total_tokens == 150
        assert ts.delivered is True
        assert ts.status == TurnStatus.complete
        assert ts.safety_flags == ["mild_violence"]

    def test_json_round_trip(self):
        ts = TurnState(
            session_id=uuid4(),
            turn_number=1,
            player_input="hello",
            game_state={"key": "val"},
            token_count=TokenCount(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
        json_str = ts.model_dump_json()
        restored = TurnState.model_validate_json(json_str)
        assert restored.session_id == ts.session_id
        assert restored.token_count is not None
        assert restored.token_count.total_tokens == 15

    def test_created_at_auto_populated(self):
        ts = TurnState(
            session_id=uuid4(),
            turn_number=0,
            player_input="",
            game_state={},
        )
        assert isinstance(ts.created_at, datetime)


# ── GameSession / GameState ──────────────────────────────────────────────


class TestGameSession:
    """GameSession represents a single play-through."""

    def test_with_status_enum(self):
        pid = uuid4()
        gs = GameSession(player_id=pid, status=GameStatus.paused)
        assert isinstance(gs.id, UUID)
        assert gs.player_id == pid
        assert gs.status == GameStatus.paused
        assert isinstance(gs.created_at, datetime)
        assert isinstance(gs.updated_at, datetime)

    def test_defaults(self):
        gs = GameSession(player_id=uuid4())
        assert gs.status == GameStatus.active
        assert gs.world_seed == {}


class TestGameState:
    """GameState is a snapshot of in-progress game state."""

    def test_defaults(self):
        sid = uuid4()
        state = GameState(session_id=sid)
        assert state.turn_number == 0
        assert state.current_location_id == "start"
        assert state.narrative_history == []


# ── Player / PlayerSession ───────────────────────────────────────────────


class TestPlayer:
    """Player identity model."""

    def test_uuid_id(self):
        p = Player(handle="adventurer")
        assert isinstance(p.id, UUID)
        assert p.handle == "adventurer"
        assert isinstance(p.created_at, datetime)


class TestPlayerSession:
    """Authenticated session token."""

    def test_fields(self):
        pid = uuid4()
        exp = datetime(2099, 1, 1)
        ps = PlayerSession(player_id=pid, token="tok_abc", expires_at=exp)
        assert isinstance(ps.id, UUID)
        assert ps.player_id == pid
        assert ps.token == "tok_abc"
        assert ps.expires_at == exp


# ── TurnRequest ──────────────────────────────────────────────────────────


class TestTurnRequest:
    """Player-facing turn input."""

    def test_without_idempotency_key(self):
        tr = TurnRequest(input="look around")
        assert tr.input == "look around"
        assert tr.idempotency_key is None

    def test_with_idempotency_key(self):
        key = uuid4()
        tr = TurnRequest(input="go north", idempotency_key=key)
        assert tr.idempotency_key == key


# ── Enums ────────────────────────────────────────────────────────────────


class TestEnums:
    """All enums expose expected string values."""

    def test_turn_status_values(self):
        assert TurnStatus.processing == "processing"
        assert TurnStatus.complete == "complete"
        assert TurnStatus.failed == "failed"

    def test_game_status_values(self):
        assert GameStatus.active == "active"
        assert GameStatus.paused == "paused"
        assert GameStatus.completed == "completed"
