"""SafetyHook adapter for the moderation service (S24 FR-24.01).

Bridges ``ModerationService`` into the pipeline's ``SafetyHook``
protocol so existing stage code (understand, generate) calls
moderation transparently.
"""

import hashlib

import structlog

from tta.models.turn import TurnState
from tta.moderation.models import (
    ContentCategory,
    ModerationContext,
    ModerationResult,
    ModerationVerdict,
)
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
    """

    def __init__(
        self,
        service: ModerationService,
        *,
        enabled: bool = True,
        fail_open: bool = True,
    ) -> None:
        self._service = service
        self._enabled = enabled
        self._fail_open = fail_open

    # ── SafetyHook protocol ─────────────────────────────────────

    async def pre_generation_check(self, turn_state: TurnState) -> SafetyResult:
        """Input moderation — runs in the understand stage."""
        if not self._enabled:
            return SafetyResult(safe=True)

        ctx = _build_context(turn_state, stage="input")
        content = turn_state.player_input

        result = await self._checked_call(self._service.moderate_input, content, ctx)
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
        return _to_safety_result(result, redirect=BLOCK_REDIRECT_OUTPUT)

    # ── internals ───────────────────────────────────────────────

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
