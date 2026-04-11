"""Tests for moderation fail-closed mode (S24 AC-24.10).

When fail_open=False and the moderation service raises an exception,
the hook must return a BLOCK verdict, not silently pass content through.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.models.turn import TurnState
from tta.moderation.hook import ModerationHook
from tta.moderation.keyword_moderator import KeywordModerator


def _turn_state() -> TurnState:
    return TurnState(
        session_id=uuid4(),
        turn_number=1,
        player_input="hello world",
        game_state={"location": "tavern"},
    )


class TestFailClosedPreGeneration:
    """AC-24.10: fail_open=False blocks content on moderation error."""

    async def test_exception_blocks_in_fail_closed(self) -> None:
        """Service exception with fail_open=False → SafetyResult(safe=False)."""
        service = KeywordModerator()
        service.moderate_input = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("moderation unavailable"),
        )
        hook = ModerationHook(service, fail_open=False)

        result = await hook.pre_generation_check(_turn_state())

        assert not result.safe
        assert "moderation:unavailable" in result.flags

    async def test_exception_passes_in_fail_open(self) -> None:
        """Service exception with fail_open=True → SafetyResult(safe=True)."""
        service = KeywordModerator()
        service.moderate_input = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("moderation unavailable"),
        )
        hook = ModerationHook(service, fail_open=True)

        result = await hook.pre_generation_check(_turn_state())

        assert result.safe

    async def test_fail_closed_has_redirect_content(self) -> None:
        """Blocked result includes narrative redirect text."""
        service = KeywordModerator()
        service.moderate_input = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom"),
        )
        hook = ModerationHook(service, fail_open=False)

        result = await hook.pre_generation_check(_turn_state())

        assert not result.safe
        assert result.modified_content is not None
        assert len(result.modified_content) > 0


class TestFailClosedPostGeneration:
    """Fail-closed also applies to output moderation."""

    async def test_output_exception_blocks_in_fail_closed(self) -> None:
        """Output moderation error with fail_open=False → block."""
        service = KeywordModerator()
        service.moderate_output = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("moderation unavailable"),
        )
        hook = ModerationHook(service, fail_open=False)

        state = _turn_state()
        result = await hook.post_generation_check("some narrative output", state)

        assert not result.safe
        assert "moderation:unavailable" in result.flags

    async def test_output_exception_passes_in_fail_open(self) -> None:
        """Output moderation error with fail_open=True → pass."""
        service = KeywordModerator()
        service.moderate_output = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("moderation unavailable"),
        )
        hook = ModerationHook(service, fail_open=True)

        state = _turn_state()
        result = await hook.post_generation_check("some narrative output", state)

        assert result.safe


class TestFailClosedConfigFlow:
    """Verify the config → hook wiring is correct."""

    def test_fail_open_default_is_true(self) -> None:
        """Default ModerationHook is fail-open."""
        hook = ModerationHook(KeywordModerator())
        assert hook._fail_open is True

    def test_fail_open_false_sets_correctly(self) -> None:
        """Explicit fail_open=False is stored."""
        hook = ModerationHook(KeywordModerator(), fail_open=False)
        assert hook._fail_open is False

    def test_disabled_hook_always_passes(self) -> None:
        """Disabled hook ignores fail_open setting."""
        hook = ModerationHook(KeywordModerator(), enabled=False, fail_open=False)
        # enabled=False means _enabled is False
        assert hook._enabled is False
