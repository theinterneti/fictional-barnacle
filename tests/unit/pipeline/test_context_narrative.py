"""Wave 24 tests for context stage tone/summary injection (S03)."""

from __future__ import annotations

from uuid import uuid4

from tta.models.turn import TurnState
from tta.pipeline.stages.context import _inject_summary, _inject_tone


def _make_state(**overrides: object) -> TurnState:
    defaults: dict = {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {"location": "tavern"},
    }
    defaults.update(overrides)
    return TurnState(**defaults)


# ===================================================================
# Tone injection (S03 FR-6.1)
# ===================================================================


class TestInjectTone:
    """_inject_tone extracts tone/genre from world_seed."""

    def test_tone_injected_from_world_seed(self) -> None:
        state = _make_state(
            game_state={
                "world_seed": {"tone": "mysterious", "genre": "noir"},
            }
        )
        ctx: dict = {}
        result = _inject_tone(ctx, state)
        assert result["tone"] == "mysterious"
        assert result["genre"] == "noir"

    def test_no_world_seed_no_crash(self) -> None:
        state = _make_state(game_state={})
        ctx: dict = {}
        result = _inject_tone(ctx, state)
        assert "tone" not in result
        assert "genre" not in result

    def test_partial_world_seed_tone_only(self) -> None:
        state = _make_state(game_state={"world_seed": {"tone": "whimsical"}})
        ctx: dict = {}
        result = _inject_tone(ctx, state)
        assert result["tone"] == "whimsical"
        assert "genre" not in result

    def test_empty_tone_not_injected(self) -> None:
        state = _make_state(game_state={"world_seed": {"tone": "", "genre": ""}})
        ctx: dict = {}
        result = _inject_tone(ctx, state)
        assert "tone" not in result
        assert "genre" not in result

    def test_world_seed_not_dict(self) -> None:
        state = _make_state(game_state={"world_seed": "invalid"})
        ctx: dict = {}
        result = _inject_tone(ctx, state)
        assert "tone" not in result


# ===================================================================
# Summary injection (S03 FR-3.2)
# ===================================================================


class TestInjectSummary:
    """_inject_summary reads existing session summary."""

    def test_summary_injected_when_present(self) -> None:
        state = _make_state(game_state={"summary": "The hero found a magic sword."})
        ctx: dict = {}
        result = _inject_summary(ctx, state)
        assert result["session_summary"] == "The hero found a magic sword."

    def test_no_summary_no_injection(self) -> None:
        state = _make_state(game_state={})
        ctx: dict = {}
        result = _inject_summary(ctx, state)
        assert "session_summary" not in result

    def test_empty_summary_not_injected(self) -> None:
        state = _make_state(game_state={"summary": ""})
        ctx: dict = {}
        result = _inject_summary(ctx, state)
        assert "session_summary" not in result

    def test_preserves_existing_context(self) -> None:
        state = _make_state(game_state={"summary": "Previously..."})
        ctx = {"location": "tavern", "npcs_present": []}
        result = _inject_summary(ctx, state)
        assert result["session_summary"] == "Previously..."
        assert result["location"] == "tavern"
