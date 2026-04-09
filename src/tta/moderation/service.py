"""Moderation service protocol (S24 FR-24.01)."""

from typing import Protocol, runtime_checkable

from tta.moderation.models import ModerationContext, ModerationResult


@runtime_checkable
class ModerationService(Protocol):
    """Interface for content moderation implementations.

    v1: keyword-based classification.
    v2+: LLM-based classification.
    """

    async def moderate_input(
        self,
        content: str,
        context: ModerationContext,
    ) -> ModerationResult:
        """Check player input before LLM processing."""
        ...

    async def moderate_output(
        self,
        content: str,
        context: ModerationContext,
    ) -> ModerationResult:
        """Check LLM output before delivery to player."""
        ...
