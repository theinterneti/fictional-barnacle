"""Shared fixtures for pipeline tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from tta.prompts.registry import RenderedPrompt


def make_mock_registry(
    *,
    templates: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock prompt registry that satisfies pipeline stages.

    By default provides all three required templates with minimal content.
    """
    default_templates = {
        "narrative.generate": "You are a narrative engine.",
        "classification.intent": "Classify the player intent.",
        "extraction.world-changes": "Extract world changes as JSON.",
    }
    tpls = {**default_templates, **(templates or {})}

    registry = MagicMock()
    registry.has.side_effect = lambda tid: tid in tpls
    registry.render.side_effect = lambda tid, _vars: RenderedPrompt(
        text=tpls[tid],
        template_id=tid,
        template_version="v1.1.0",
    )
    return registry
