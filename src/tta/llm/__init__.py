"""LLM integration layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tta.llm.litellm_client import LiteLLMClient  # noqa: F401

__all__ = ["LiteLLMClient"]


def __getattr__(name: str):
    if name == "LiteLLMClient":
        from tta.llm.litellm_client import LiteLLMClient

        return LiteLLMClient
    raise AttributeError(f"module 'tta.llm' has no attribute {name!r}")
