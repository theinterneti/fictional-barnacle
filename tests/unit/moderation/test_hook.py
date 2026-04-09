"""Tests for ModerationHook — SafetyHook adapter (S24 FR-24.01)."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tta.models.turn import TurnState
from tta.moderation.flagging import SessionFlagTracker
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
from tta.moderation.recorder import ModerationRecorder


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


def _mock_recorder() -> ModerationRecorder:
    """Build a ModerationRecorder with a mock session factory."""
    recorder = ModerationRecorder.__new__(ModerationRecorder)
    recorder._session_factory = MagicMock()
    recorder.save = AsyncMock()  # type: ignore[method-assign]
    return recorder


def _mock_flag_tracker(
    threshold: int = 5,
) -> SessionFlagTracker:
    return SessionFlagTracker(threshold=threshold, window_minutes=10)


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


# ── Recording integration (FR-24.09) ───────────────────────────


class TestRecordingIntegration:
    async def test_pass_saves_record(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        recorder = _mock_recorder()
        hook = ModerationHook(svc, recorder=recorder)

        await hook.pre_generation_check(_make_state())

        recorder.save.assert_awaited_once()
        record = recorder.save.call_args[0][0]
        assert record.verdict == ModerationVerdict.PASS
        assert record.game_id == "g1"
        assert record.stage == "input"

    async def test_block_saves_record(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _block_result()
        recorder = _mock_recorder()
        hook = ModerationHook(svc, recorder=recorder)

        await hook.pre_generation_check(_make_state("bad stuff"))

        recorder.save.assert_awaited_once()
        record = recorder.save.call_args[0][0]
        assert record.verdict == ModerationVerdict.BLOCK
        assert record.content == "bad stuff"

    async def test_output_moderation_saves_record(self) -> None:
        svc = AsyncMock()
        svc.moderate_output.return_value = _block_result()
        recorder = _mock_recorder()
        hook = ModerationHook(svc, recorder=recorder)

        await hook.post_generation_check("violent text", _make_state())

        recorder.save.assert_awaited_once()
        record = recorder.save.call_args[0][0]
        assert record.stage == "output"
        assert record.content == "violent text"

    async def test_no_recorder_skips_persistence(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        hook = ModerationHook(svc, recorder=None)
        # Should not raise
        await hook.pre_generation_check(_make_state())


# ── Structured logging (FR-24.12) ──────────────────────────────


class TestStructuredLogging:
    async def test_log_emitted_on_pass(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        hook = ModerationHook(svc)

        with patch("tta.moderation.hook.log") as mock_log:
            await hook.pre_generation_check(_make_state())
            mock_log.info.assert_called_once()
            kw = mock_log.info.call_args[1]
            assert kw["verdict"] == "pass"
            assert kw["stage"] == "input"

    async def test_log_contains_hash_not_content(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _block_result()
        hook = ModerationHook(svc)

        with patch("tta.moderation.hook.log") as mock_log:
            await hook.pre_generation_check(_make_state("secret content"))
            kw = mock_log.info.call_args[1]
            assert "content_hash" in kw
            # Raw content must NEVER appear in log kwargs
            for v in kw.values():
                assert v != "secret content"

    async def test_log_event_name(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        hook = ModerationHook(svc)

        with patch("tta.moderation.hook.log") as mock_log:
            await hook.pre_generation_check(_make_state())
            assert mock_log.info.call_args[0][0] == "moderation_action"


# ── Flagging integration (FR-24.11) ────────────────────────────


class TestFlaggingIntegration:
    async def test_block_records_in_flag_tracker(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _block_result()
        tracker = _mock_flag_tracker(threshold=5)
        hook = ModerationHook(svc, flag_tracker=tracker)

        await hook.pre_generation_check(_make_state("bad"))

        assert len(tracker._blocks["g1"]) == 1

    async def test_pass_does_not_record_in_tracker(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _pass_result()
        tracker = _mock_flag_tracker()
        hook = ModerationHook(svc, flag_tracker=tracker)

        await hook.pre_generation_check(_make_state())

        assert len(tracker._blocks) == 0

    async def test_flag_verdict_does_not_record(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _flag_result()
        tracker = _mock_flag_tracker()
        hook = ModerationHook(svc, flag_tracker=tracker)

        await hook.pre_generation_check(_make_state())

        assert len(tracker._blocks) == 0

    async def test_no_tracker_skips_flagging(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _block_result()
        hook = ModerationHook(svc, flag_tracker=None)
        # Should not raise
        await hook.pre_generation_check(_make_state())

    @pytest.mark.asyncio
    async def test_threshold_triggers_on_rapid_blocks(self) -> None:
        svc = AsyncMock()
        svc.moderate_input.return_value = _block_result()
        tracker = _mock_flag_tracker(threshold=2)
        hook = ModerationHook(svc, flag_tracker=tracker)

        await hook.pre_generation_check(_make_state("bad1"))
        assert len(tracker._blocks["g1"]) == 1
        await hook.pre_generation_check(_make_state("bad2"))
        # Threshold=2 reached — record_block returned True internally
        assert len(tracker._blocks["g1"]) == 2
