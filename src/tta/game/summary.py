"""Context-summary and title generation via LLM (S27 FR-27.20–FR-27.22).

Both helpers are intentionally fire-and-forget safe — callers should catch
and log errors so that a summary failure never blocks gameplay.
"""

from __future__ import annotations

import logging
from typing import Any

import litellm

logger = logging.getLogger(__name__)

_TITLE_SYSTEM = (
    "You are a creative game narrator. "
    "Generate a short, evocative title (≤80 characters) "
    "for a text-adventure game based on the opening narrative. "
    "Reply with ONLY the title, no quotes or explanation."
)

_SUMMARY_SYSTEM = (
    "You are a concise story summariser. "
    "Given recent turns of a text adventure, produce a 1-3 sentence "
    "summary (≤200 characters) capturing key events and the current "
    "situation. Reply with ONLY the summary."
)


class ContextSummaryService:
    """Thin wrapper around LiteLLM for game summaries and titles."""

    def __init__(self, model: str = "") -> None:
        self._model = model or "openai/gpt-4o-mini"

    async def generate_title(self, opening_narrative: str) -> str:
        """Return a short game title derived from the opening text."""
        return await self._call(
            system=_TITLE_SYSTEM,
            user=opening_narrative[:2000],
            max_tokens=40,
        )

    async def generate_context_summary(self, turns: list[dict[str, Any]]) -> str:
        """Return a ≤200-char summary of recent turns."""
        # Build a compact transcript
        lines: list[str] = []
        for t in turns[-10:]:
            inp = (t.get("player_input") or "")[:200]
            out = (t.get("narrative_output") or "")[:300]
            lines.append(f"Player: {inp}\nNarrator: {out}")
        transcript = "\n---\n".join(lines)

        summary = await self._call(
            system=_SUMMARY_SYSTEM,
            user=transcript[:4000],
            max_tokens=100,
        )
        return summary[:200]

    # ------------------------------------------------------------------
    async def _call(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
    ) -> str:
        resp = await litellm.acompletion(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        content: str = resp.choices[0].message.content or ""  # type: ignore[union-attr]
        return content.strip()
