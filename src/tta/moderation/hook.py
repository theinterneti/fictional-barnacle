"""SafetyHook adapter for the moderation service (S24 FR-24.01).

Bridges ``ModerationService`` into the pipeline's ``SafetyHook``
protocol so existing stage code (understand, generate) calls
moderation transparently.

After each moderation check, a ``ModerationRecord`` is persisted
(FR-24.09) and a structured ``moderation_action`` log is emitted
(FR-24.12).  The ``SessionFlagTracker`` watches for rapid-fire
blocks and flags sessions that exceed the threshold (FR-24.11).
"""

from __future__ import annotations

import hashlib

import structlog

from tta.models.turn import TurnState
from tta.moderation.flagging import SessionFlagTracker
from tta.moderation.models import (
    ContentCategory,
    ModerationContext,
    ModerationRecord,
    ModerationResult,
    ModerationVerdict,
)
from tta.moderation.recorder import ModerationRecorder
from tta.moderation.service import ModerationService
from tta.safety.hooks import SafetyResult

log = structlog.get_logger()

# Narrative redirection shown to the player on block (not an error).
BLOCK_REDIRECT_INPUT = (
    "The story pauses for a moment as the narrator considers your words. "
    "Perhaps we could explore a different direction…"
)
BLOCK_REDIRECT_OUTPUT = (
    "The story pauses for a moment as the narrator reconsiders the "
    "direction of the tale. Let's explore a different path…"
)


class ModerationHook:
    """Wraps a ``ModerationService`` to satisfy the ``SafetyHook`` protocol.

    Parameters
    ----------
    service:
        The underlying moderation implementation.
    enabled:
        Master switch — when ``False``, all checks pass through.
    fail_open:
        When ``True`` (default), moderation errors are logged at WARN
        and the content is allowed through.  When ``False``, errors
        cause a block verdict.
    recorder:
        Optional persistence layer for moderation records. ``None``
        disables persistence (unit-test friendly).
    flag_tracker:
        Optional session-level auto-flagging tracker. ``None``
        disables session flagging.
    """

    def __init__(
        self,
        service: ModerationService,
        *,
        enabled: bool = True,
        fail_open: bool = True,
        recorder: ModerationRecorder | None = None,
        flag_tracker: SessionFlagTracker | None = None,
    ) -> None:
        self._service = service
        self._enabled = enabled
        self._fail_open = fail_open
        self._recorder = recorder
        self._flag_tracker = flag_tracker

    # ── SafetyHook protocol ─────────────────────────────────────

    async def pre_generation_check(self, turn_state: TurnState) -> SafetyResult:
        """Input moderation — runs in the understand stage."""
        if not self._enabled:
            return SafetyResult(safe=True)

        ctx = _build_context(turn_state, stage="input")
        content = turn_state.player_input

        result = await self._checked_call(self._service.moderate_input, content, ctx)
        await self._post_check(result, content, ctx)
        return _to_safety_result(result, redirect=BLOCK_REDIRECT_INPUT)

    async def post_generation_check(
        self, narrative_output: str, turn_state: TurnState
    ) -> SafetyResult:
        """Output moderation — runs in the generate stage."""
        if not self._enabled:
            return SafetyResult(safe=True)

        ctx = _build_context(turn_state, stage="output")

        result = await self._checked_call(
            self._service.moderate_output, narrative_output, ctx
        )
        await self._post_check(result, narrative_output, ctx)
        return _to_safety_result(result, redirect=BLOCK_REDIRECT_OUTPUT)

    # ── internals ───────────────────────────────────────────────

    async def _post_check(
        self,
        result: ModerationResult,
        content: str,
        ctx: ModerationContext,
    ) -> None:
        """Persist record, emit structured log, track flagging."""
        record = ModerationRecord(
            turn_id=ctx.turn_id,
            game_id=ctx.game_id,
            player_id=ctx.player_id,
            stage=ctx.stage,
            content_hash=result.content_hash,
            content=content,
            verdict=result.verdict,
            category=result.category,
            confidence=result.confidence,
            reason=result.reason,
        )

        # FR-24.12: structured log — never log raw content
        log.info(
            "moderation_action",
            moderation_id=record.moderation_id,
            content_hash=record.content_hash,
            verdict=result.verdict.value,
            category=result.category.value,
            confidence=result.confidence,
            stage=ctx.stage,
            game_id=ctx.game_id,
            player_id=ctx.player_id,
        )

        # FR-24.09: persist full record
        if self._recorder is not None:
            await self._recorder.save(record)

        # FR-24.11: session auto-flagging on block
        if result.verdict == ModerationVerdict.BLOCK and self._flag_tracker is not None:
            self._flag_tracker.record_block(ctx.game_id, ctx.player_id)

    async def _checked_call(
        self,
        fn,  # noqa: ANN001 — callable with known signature
        content: str,
        ctx: ModerationContext,
    ) -> ModerationResult:
        """Call the moderation service with fail-open/closed semantics."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        try:
            return await fn(content, ctx)
        except Exception:
            if self._fail_open:
                log.warning(
                    "moderation_service_error",
                    stage=ctx.stage,
                    fail_mode="open",
                    exc_info=True,
                )
                return ModerationResult(
                    verdict=ModerationVerdict.PASS,
                    category=ContentCategory.SAFE,
                    confidence=0.0,
                    reason="moderation_unavailable",
                    content_hash=content_hash,
                )
            log.error(
                "moderation_service_error",
                stage=ctx.stage,
                fail_mode="closed",
                exc_info=True,
            )
            return ModerationResult(
                verdict=ModerationVerdict.BLOCK,
                category=ContentCategory.SAFE,
                confidence=0.0,
                reason="moderation_unavailable",
                content_hash=content_hash,
                flags=["moderation:unavailable"],
            )


# ── helpers ─────────────────────────────────────────────────────


def _build_context(state: TurnState, *, stage: str) -> ModerationContext:
    return ModerationContext(
        game_id=state.game_state.get("game_id", ""),
        player_id=state.game_state.get("player_id", ""),
        turn_id=str(state.turn_number),
        stage=stage,
    )


def _to_safety_result(result: ModerationResult, *, redirect: str) -> SafetyResult:
    if result.verdict == ModerationVerdict.BLOCK:
        flags = result.flags or [f"moderation:{result.category.value}"]
        return SafetyResult(
            safe=False,
            flags=flags,
            modified_content=redirect,
        )
    if result.verdict == ModerationVerdict.FLAG:
        log.info(
            "moderation_flagged",
            category=result.category.value,
            confidence=result.confidence,
            reason=result.reason,
        )
        return SafetyResult(safe=True, flags=[f"flagged:{result.category.value}"])
    return SafetyResult(safe=True)
