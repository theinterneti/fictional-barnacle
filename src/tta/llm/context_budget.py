"""Context window budget management per S07 §5 FR-07.12–16.

Implements chunk-based priority fitting:
  P0 — system prompt & safety rules (never truncated)
  P1 — recent turns / player action (~20 % budget)
  P2 — world state / NPC context (~40 % budget)
  P3 — extended history / flavour (remainder)

The budget fitter removes P3 first, then P2, and never touches P0/P1.
Callers are responsible for replacing dropped chunks with a summary
stub if FR-07.15 placeholder text is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import structlog

from tta.observability.metrics import CONTEXT_CHUNKS_DROPPED

_log = structlog.get_logger(__name__)


class Priority(IntEnum):
    """Chunk priority tier (lower = more important)."""

    P0 = 0  # system prompt, safety — never truncated
    P1 = 1  # recent turns, player action
    P2 = 2  # world state, NPC context
    P3 = 3  # extended history, flavour


@dataclass(slots=True)
class ContextChunk:
    """A discrete piece of prompt context with a priority tier."""

    name: str
    content: str
    priority: Priority
    token_count: int = 0


@dataclass(slots=True)
class BudgetResult:
    """Outcome of fitting chunks to a token budget."""

    chunks: list[ContextChunk]
    total_tokens: int
    dropped: list[str] = field(default_factory=list)


def count_tokens(text: str) -> int:
    """Conservative token estimate.

    Uses ``len // 2`` which provably over-counts for English text
    (typical ratio is ~3.5–4 chars/token).  Over-counting is safe;
    under-counting risks exceeding the context window (FR-07.14).
    """
    return max(1, len(text) // 2)


def fit_chunks_to_budget(
    chunks: list[ContextChunk],
    budget_tokens: int,
) -> BudgetResult:
    """Select chunks that fit within *budget_tokens*.

    Chunks are sorted by priority (P0 first).  If the budget is
    exceeded, P3 chunks are dropped first, then P2.  P0 and P1 are
    never dropped.  Dropped chunks are recorded so callers can log
    the elision or replace with a summary stub.
    """
    # Compute token counts if missing
    for c in chunks:
        if c.token_count <= 0:
            c.token_count = count_tokens(c.content)

    # Sort by priority (P0 first) — stable sort keeps insertion order
    ordered = sorted(chunks, key=lambda c: c.priority)

    # Start with all chunks, then drop lowest-priority first (FR-07.13)
    kept = list(ordered)
    dropped: list[str] = []
    used = sum(c.token_count for c in kept)

    for priority in (Priority.P3, Priority.P2):
        idx = len(kept) - 1
        while used > budget_tokens and idx >= 0:
            chunk = kept[idx]
            if chunk.priority == priority:
                used -= chunk.token_count
                dropped.append(chunk.name)
                del kept[idx]
            idx -= 1

    if dropped:
        CONTEXT_CHUNKS_DROPPED.inc(len(dropped))
        _log.info(
            "context_chunks_dropped",
            dropped=dropped,
            budget=budget_tokens,
            used=used,
        )

    return BudgetResult(chunks=kept, total_tokens=used, dropped=dropped)
