"""Property-based tests for Pydantic domain models (S16 §10).

Uses Hypothesis to verify model invariants:
- Valid inputs always produce valid instances
- Round-trip JSON serialization preserves data
- Validation rejects known-invalid inputs
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from tta.api.routes.games import SubmitTurnRequest
from tta.api.routes.players import CreatePlayerRequest
from tta.models.choice import (
    ChoiceClassification,
    ChoiceType,
    ImpactLevel,
    Reversibility,
)
from tta.models.game import GameSession, GameState, GameStatus
from tta.models.player import Player, PlayerSession
from tta.models.turn import ParsedIntent, TokenCount, TurnRequest

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
_uuids = st.uuids()
_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 1, 1),
    timezones=st.just(UTC),
)
_handles = st.from_regex(r"^[a-zA-Z0-9 _\-\.]{1,50}$", fullmatch=True)
_player_input = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# TokenCount
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestTokenCount:
    @given(
        prompt=st.integers(min_value=0, max_value=100_000),
        completion=st.integers(min_value=0, max_value=100_000),
    )
    @settings(max_examples=50)
    def test_valid_construction(self, prompt: int, completion: int) -> None:
        tc = TokenCount(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )
        assert tc.prompt_tokens == prompt
        assert tc.completion_tokens == completion

    @given(
        prompt=st.integers(min_value=0, max_value=10_000),
        completion=st.integers(min_value=0, max_value=10_000),
    )
    @settings(max_examples=50)
    def test_json_round_trip(self, prompt: int, completion: int) -> None:
        tc = TokenCount(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )
        restored = TokenCount.model_validate_json(tc.model_dump_json())
        assert restored == tc


# ---------------------------------------------------------------------------
# ParsedIntent
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestParsedIntent:
    @given(
        intent=st.text(min_size=1, max_size=50),
        confidence=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=50)
    def test_valid_construction(self, intent: str, confidence: float) -> None:
        pi = ParsedIntent(intent=intent, confidence=confidence)
        assert pi.intent == intent


# ---------------------------------------------------------------------------
# TurnRequest
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestTurnRequest:
    @given(text=_player_input)
    @settings(max_examples=50)
    def test_valid_input(self, text: str) -> None:
        req = TurnRequest(input=text)
        assert req.input == text

    @given(text=_player_input, key=_uuids)
    @settings(max_examples=50)
    def test_json_round_trip(self, text: str, key: object) -> None:
        req = TurnRequest(input=text, idempotency_key=key)
        restored = TurnRequest.model_validate_json(req.model_dump_json())
        assert restored == req


# ---------------------------------------------------------------------------
# GameSession
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestGameSession:
    @given(pid=_uuids, status=st.sampled_from(list(GameStatus)))
    @settings(max_examples=50)
    def test_valid_construction(self, pid: object, status: GameStatus) -> None:
        gs = GameSession(player_id=pid, status=status)
        assert gs.player_id == pid
        assert gs.status == status

    @given(pid=_uuids)
    @settings(max_examples=50)
    def test_json_round_trip(self, pid: object) -> None:
        gs = GameSession(player_id=pid)
        restored = GameSession.model_validate_json(gs.model_dump_json())
        assert restored.player_id == gs.player_id
        assert restored.status == gs.status


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestGameState:
    @given(
        sid=_uuids,
        turn=st.integers(min_value=0, max_value=10_000),
        loc=st.text(min_size=1, max_size=30),
    )
    @settings(max_examples=50)
    def test_valid_construction(self, sid: object, turn: int, loc: str) -> None:
        state = GameState(session_id=sid, turn_number=turn, current_location_id=loc)
        assert state.turn_number == turn


# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestPlayer:
    @given(handle=_handles)
    @settings(max_examples=50)
    def test_valid_construction(self, handle: str) -> None:
        p = Player(handle=handle)
        assert p.handle == handle

    @given(handle=_handles)
    @settings(max_examples=50)
    def test_json_round_trip(self, handle: str) -> None:
        p = Player(handle=handle)
        restored = Player.model_validate_json(p.model_dump_json())
        assert restored.handle == p.handle


# ---------------------------------------------------------------------------
# PlayerSession
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestPlayerSession:
    @given(
        token=st.text(min_size=10, max_size=100),
        expires=_datetimes,
    )
    @settings(max_examples=50)
    def test_valid_construction(self, token: str, expires: datetime) -> None:
        ps = PlayerSession(player_id=uuid4(), token=token, expires_at=expires)
        assert ps.token == token


# ---------------------------------------------------------------------------
# ChoiceClassification
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestChoiceClassification:
    @given(
        types=st.lists(st.sampled_from(list(ChoiceType)), min_size=1, max_size=3),
        impact=st.sampled_from(list(ImpactLevel)),
        rev=st.sampled_from(list(Reversibility)),
        confidence=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=50)
    def test_valid_construction(
        self,
        types: list[ChoiceType],
        impact: ImpactLevel,
        rev: Reversibility,
        confidence: float,
    ) -> None:
        cc = ChoiceClassification(
            types=types,
            impact_level=impact,
            reversibility=rev,
            confidence=confidence,
        )
        assert cc.primary_type == types[0]


# ---------------------------------------------------------------------------
# SubmitTurnRequest (API-level validation)
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestSubmitTurnRequest:
    @given(text=_player_input)
    @settings(max_examples=50)
    def test_valid_input_accepted(self, text: str) -> None:
        req = SubmitTurnRequest(input=text)
        assert req.input == text

    @given(text=st.just(""))
    def test_empty_input_passes_model_validation(self, text: str) -> None:
        """Model accepts empty string; route handler enforces non-empty (AC-23.11)."""
        req = SubmitTurnRequest(input=text)
        assert req.input == text

    @given(text=st.text(min_size=2001, max_size=2100))
    @settings(max_examples=10)
    def test_too_long_rejected(self, text: str) -> None:
        with pytest.raises(ValidationError):
            SubmitTurnRequest(input=text)

    @given(text=st.from_regex(r"^\s+$", fullmatch=True))
    @settings(max_examples=20)
    def test_whitespace_only_accepted(self, text: str) -> None:
        req = SubmitTurnRequest(input=text)
        assert req.input == text


# ---------------------------------------------------------------------------
# CreatePlayerRequest (handle validation)
# ---------------------------------------------------------------------------
@pytest.mark.hypothesis
class TestCreatePlayerRequest:
    @given(handle=_handles)
    @settings(max_examples=50)
    def test_valid_handle_accepted(self, handle: str) -> None:
        req = CreatePlayerRequest(
            handle=handle,
            age_13_plus_confirmed=True,
            consent_version="1.0",
            consent_categories={"core_gameplay": True, "llm_processing": True},
        )
        assert req.handle == handle

    @given(handle=st.just(""))
    def test_empty_handle_rejected(self, handle: str) -> None:
        with pytest.raises(ValidationError):
            CreatePlayerRequest(
                handle=handle,
                age_13_plus_confirmed=True,
                consent_version="1.0",
                consent_categories={"core_gameplay": True, "llm_processing": True},
            )

    @given(handle=st.text(min_size=51, max_size=100))
    @settings(max_examples=10)
    def test_too_long_handle_rejected(self, handle: str) -> None:
        with pytest.raises(ValidationError):
            CreatePlayerRequest(
                handle=handle,
                age_13_plus_confirmed=True,
                consent_version="1.0",
                consent_categories={"core_gameplay": True, "llm_processing": True},
            )

    @given(handle=st.from_regex(r"^[!@#$%^&*()]{1,10}$", fullmatch=True))
    @settings(max_examples=20)
    def test_special_chars_rejected(self, handle: str) -> None:
        with pytest.raises(ValidationError):
            CreatePlayerRequest(handle=handle)
