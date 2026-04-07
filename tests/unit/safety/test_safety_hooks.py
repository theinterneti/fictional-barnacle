"""Tests for safety hook protocol and pass-through implementation."""

from uuid import uuid4

import pytest

from tta.safety.hooks import PassthroughHook, SafetyHook, SafetyResult


def _make_turn_state() -> dict:
    """Minimal kwargs for a TurnState."""
    return {
        "session_id": uuid4(),
        "turn_number": 1,
        "player_input": "look around",
        "game_state": {},
    }


# ── SafetyResult defaults ──────────────────────────────────────


def test_safety_result_defaults() -> None:
    result = SafetyResult(safe=True)
    assert result.safe is True
    assert result.flags == []
    assert result.modified_content is None


def test_safety_result_with_flags() -> None:
    result = SafetyResult(safe=False, flags=["violence", "profanity"])
    assert result.safe is False
    assert result.flags == ["violence", "profanity"]


def test_safety_result_with_modified_content() -> None:
    result = SafetyResult(safe=True, modified_content="cleaned text")
    assert result.modified_content == "cleaned text"


# ── PassthroughHook ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_passthrough_pre_generation_check() -> None:
    from tta.models.turn import TurnState

    hook = PassthroughHook()
    ts = TurnState(**_make_turn_state())
    result = await hook.pre_generation_check(ts)
    assert result.safe is True
    assert result.flags == []


@pytest.mark.asyncio
async def test_passthrough_post_generation_check() -> None:
    from tta.models.turn import TurnState

    hook = PassthroughHook()
    ts = TurnState(**_make_turn_state())
    result = await hook.post_generation_check("some output", ts)
    assert result.safe is True
    assert result.flags == []


def test_passthrough_satisfies_protocol() -> None:
    assert isinstance(PassthroughHook(), SafetyHook)


# ── Audit smoke test ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_turn_does_not_raise() -> None:
    from tta.models.turn import TurnState
    from tta.safety.audit import log_turn

    ts = TurnState(**_make_turn_state())
    await log_turn(ts)  # should not raise
