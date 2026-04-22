"""Sentence-aligned narrative chunking (FR-32.05d — moved from games.py)."""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_narrative(text: str) -> list[str]:
    """Split narrative text into sentence-aligned chunks (S10 §6.4 FR-10.34).

    Splits on sentence boundaries (``. ``, ``! ``, ``? ``), keeping the terminal
    punctuation with its sentence.  Empty or whitespace-only input returns ``[]``.
    """
    stripped = text.strip()
    if not stripped:
        return []
    parts = _SENTENCE_SPLIT_RE.split(stripped)
    return [p.strip() for p in parts if p.strip()] or [stripped]
