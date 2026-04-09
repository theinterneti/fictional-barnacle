"""Tests for ModerationHook — SafetyHook adapter (S24 FR-24.01)."""

from unittest.mock import AsyncMock
from uuid import uuid4

from tta.models.turn import TurnState
from tta.moderation.hook import (
    BLOCK_REDIRECT_INPUT,
    BLOCK_REDIRECT_OUTPUT,
    ModerationHook,
)
from tta.moderation.models import (
    ContentCategory,
    ModerationContext,
    ModerationResult,
    ModerationVerdict,
)


def _make_state(player_input: str = "hello") -> TurnState:
    return TurnState(
        session_id=uuid4(),
        turn_number=1,
        player_input=player_input,
        game_state={"game_id": "g1", "player_id": "p1"},
    )


def _pass_result() -> ModerationResult:
    return ModerationResult(
        verdict=ModerationVerdict.PASS,
        category=ContentCategory.SAFE,
        confidence=1.0,
        reason="safe",
        content_hash="abc",
    )


def _block_result(
    category: ContentCategory = ContentCategory.SELF_HARM,
) -> ModerationResult:
    return ModerationResult(
        verdict=ModerationVerdict.BLOCK,
        category=category,
        confidence=0.95,
        reason=category.value,
        content_hash="abc",
    )


def _flag_result(
    category: ContentCategory = ContentCategory.PERSONAL_INFO,
) -> ModerationResult:
    return ModerationResult(
        verdict=ModerationVerdict.FLAG,
        category=category,
        confidence=0.8,
        reason=category.value,
        content_hash="abc",
    )


# ── Enabled / Disabled ─────────────────────────────────────────


class TestEnabled:
    async def test_disabled_passes_through(self) -> None:
        svc = AsyncMock()
        hook = ModerationHook(svc, enabled=False)
        result = await hook.pre_generation_check(_make_state())
        assert result.safe is True
        svc.moderate_input.assert_not_called()

    async def test_enabled_calls_service(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        hook = ModerationHook(svc, enabled=True)
        result = await hook.pre_generation_check(_make_state())
        assert result.safe is True
        svc.moderate_input.assert_called_once()


# ── Input moderation ────────────────────────────────────────────


class TestInputModeration:
    async def test_pass_returns_safe(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        hook = ModerationHook(svc)
        result = await hook.pre_generation_check(_make_state("I open the door"))
        assert result.safe is True
        assert result.flags == []
        assert result.modified_content is None

    async def test_block_returns_unsafe_with_redirect(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _block_result()
        hook = ModerationHook(svc)
        result = await hook.pre_generation_check(_make_state("bad input"))
        assert result.safe is False
        assert "moderation:self_harm" in result.flags
        assert result.modified_content == BLOCK_REDIRECT_INPUT

    async def test_flag_returns_safe_with_flag(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _flag_result()
        hook = ModerationHook(svc)
        result = await hook.pre_generation_check(_make_state("my email is a@b.com"))
        assert result.safe is True
        assert "flagged:personal_info" in result.flags


# ── Output moderation ───────────────────────────────────────────


class TestOutputModeration:
    async def test_pass_returns_safe(self) -> None:
        svc = AsyncMock()
        svc.moderate_output.return_value = _pass_result()
        hook = ModerationHook(svc)
        result = await hook.post_generation_check("safe narrative", _make_state())
        assert result.safe is True

    async def test_block_returns_redirect(self) -> None:
        svc = AsyncMock()
        svc.moderate_output.return_value = _block_result(
            ContentCategory.GRAPHIC_VIOLENCE
        )
        hook = ModerationHook(svc)
        result = await hook.post_generation_check("violent output", _make_state())
        assert result.safe is False
        assert result.modified_content == BLOCK_REDIRECT_OUTPUT
        assert "moderation:graphic_violence" in result.flags


# ── Fail-open / fail-closed ─────────────────────────────────────


class TestFailModes:
    async def test_fail_open_on_error(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.side_effect = RuntimeError("service down")
        hook = ModerationHook(svc, fail_open=True)
        result = await hook.pre_generation_check(_make_state())
        assert result.safe is True  # fail-open: allow through

    async def test_fail_closed_on_error(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.side_effect = RuntimeError("service down")
        hook = ModerationHook(svc, fail_open=False)
        result = await hook.pre_generation_check(_make_state())
        assert result.safe is False  # fail-closed: block
        assert "moderation:unavailable" in result.flags
        assert result.modified_content is not None  # redirect narrative

    async def test_fail_open_output(self) -> None:
        svc = AsyncMock()
        svc.moderate_output.side_effect = RuntimeError("timeout")
        hook = ModerationHook(svc, fail_open=True)
        result = await hook.post_generation_check("narrative", _make_state())
        assert result.safe is True

    async def test_fail_closed_output(self) -> None:
        svc = AsyncMock()
        svc.moderate_output.side_effect = RuntimeError("timeout")
        hook = ModerationHook(svc, fail_open=False)
        result = await hook.post_generation_check("narrative", _make_state())
        assert result.safe is False
        assert "moderation:unavailable" in result.flags


# ── Context building ────────────────────────────────────────────


class TestContextBuilding:
    async def test_context_populated_from_state(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        hook = ModerationHook(svc)
        state = _make_state("hello")
        await hook.pre_generation_check(state)

        call_args = svc.moderate_input.call_args
        ctx: ModerationContext = call_args[0][1]
        assert ctx.game_id == "g1"
        assert ctx.player_id == "p1"
        assert ctx.stage == "input"

    async def test_output_context_stage(self) -> None:
        svc = AsyncMock()
        svc.moderate_output.return_value = _pass_result()
        hook = ModerationHook(svc)
        await hook.post_generation_check("narrative", _make_state())

        ctx: ModerationContext = svc.moderate_output.call_args[0][1]
        assert ctx.stage == "output"


# ── Protocol compliance ─────────────────────────────────────────


class TestProtocolCompliance:
    def test_moderation_hook_satisfies_safety_hook_protocol(self) -> None:
        """ModerationHook must be a valid SafetyHook implementation."""
        from tta.safety.hooks import SafetyHook

        svc = AsyncMock()
        hook = ModerationHook(svc)
        assert isinstance(hook, SafetyHook)
