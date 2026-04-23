"""World Memory Writer and Compressor (S37).

MemoryWriter records world-scoped MemoryRecord nodes to Neo4j and
assembles three-tier context for the LLM prompt. MemoryCompressor
fires asynchronously (fire-and-forget) when the active-tier token
count exceeds the configured threshold.

InMemoryMemoryWriter is the injectable test double.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ulid import ULID

from tta.simulation.types import (
    CompressionResult,
    MemoryContext,
    MemoryRecord,
)

if TYPE_CHECKING:
    from tta.simulation.types import WorldTime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Importance scoring helpers (S37 FR-37.04, Appendix B)
# ---------------------------------------------------------------------------

_SOURCE_WEIGHTS: dict[str, float] = {
    "player": 0.3,
    "world": 0.2,
    "narrator": 0.0,
    "npc": 0.0,
}
_NPC_TIER_WEIGHTS: dict[str, float] = {
    "KEY": 0.3,
    "SUPPORTING": 0.1,
    "BACKGROUND": 0.0,
}
_SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 0.3,
    "major": 0.2,
    "notable": 0.1,
    "minor": 0.0,
}
_TAG_WEIGHTS: dict[str, float] = {
    "quest": 0.2,
    "death": 0.1,
    "combat": 0.1,
}


def _score_importance(
    source: str,
    npc_tier: str | None,
    max_consequence_severity: str | None,
    tags: list[str],
) -> float:
    """Additive importance score clamped to [0.0, 1.0] (S37 Appendix B)."""
    score = _SOURCE_WEIGHTS.get(source, 0.0)
    if npc_tier:
        score += _NPC_TIER_WEIGHTS.get(npc_tier, 0.0)
    if max_consequence_severity:
        score += _SEVERITY_WEIGHTS.get(max_consequence_severity, 0.0)
    for tag in tags:
        score += _TAG_WEIGHTS.get(tag, 0.0)
    return min(1.0, max(0.0, score))


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars ≈ 1 token)."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class MemoryWriter(Protocol):
    """Injectable world-memory service (S37 FR-37.03)."""

    async def record(
        self,
        universe_id: str,
        session_id: UUID,
        turn_number: int,
        world_time: WorldTime,
        source: str,
        content: str,
        attributed_to: str | None,
        tags: list[str],
        consequence_ids: list[str],
        npc_tier: str | None,
        max_consequence_severity: str | None,
    ) -> MemoryRecord: ...

    async def get_context(
        self,
        universe_id: str,
        session_id: UUID,
        current_tick: int,
        budget_tokens: int,
        memory_config: dict,
    ) -> MemoryContext: ...

    async def compress_if_needed(
        self,
        universe_id: str,
        session_id: UUID,
        memory_config: dict,
    ) -> CompressionResult: ...


# ---------------------------------------------------------------------------
# In-memory test double
# ---------------------------------------------------------------------------


class InMemoryMemoryWriter:
    """In-process MemoryWriter backed by a list. Used in tests (S37 FR-37.03a)."""

    def __init__(self) -> None:
        self._records: list[MemoryRecord] = []

    async def record(
        self,
        universe_id: str,
        session_id: UUID,
        turn_number: int,
        world_time: WorldTime,
        source: str,
        content: str,
        attributed_to: str | None = None,
        tags: list[str] | None = None,
        consequence_ids: list[str] | None = None,
        npc_tier: str | None = None,
        max_consequence_severity: str | None = None,
    ) -> MemoryRecord:
        tags = tags or []
        consequence_ids = consequence_ids or []
        importance = _score_importance(source, npc_tier, max_consequence_severity, tags)

        # Determine tier: last 5 turns is "working" (default working_memory_size)
        working_memory_size = 5
        recent_turns = {r.turn_number for r in self._records}
        sorted_recent = sorted(recent_turns, reverse=True)[:working_memory_size]
        tier = (
            "working"
            if (not sorted_recent or turn_number >= min(sorted_recent))
            else "active"
        )

        rec = MemoryRecord(
            memory_id=str(ULID()),
            universe_id=universe_id,
            session_id=str(session_id),
            turn_number=turn_number,
            world_time_tick=world_time.total_ticks,
            source=source,  # type: ignore[arg-type]
            attributed_to=attributed_to,
            content=content,
            summary=None,
            importance_score=importance,
            tier=tier,  # type: ignore[arg-type]
            is_compressed=False,
            tags=tags,
            consequence_ids=consequence_ids,
        )
        self._records.append(rec)
        asyncio.create_task(self.compress_if_needed(universe_id, str(session_id), {}))
        return rec

    async def get_context(
        self,
        universe_id: str,
        session_id: UUID,
        current_tick: int,
        budget_tokens: int,
        memory_config: dict | None = None,
    ) -> MemoryContext:
        cfg = memory_config or {}
        working_memory_size: int = cfg.get("working_memory_size", 5)
        half_life: int = cfg.get("memory_half_life_ticks", 50)

        session_records = [
            r
            for r in self._records
            if r.universe_id == universe_id
            and r.session_id == str(session_id)
            and r.tier != "archived"
        ]
        if not session_records:
            return MemoryContext()

        # Working tier: last working_memory_size unique turn numbers
        all_turns = sorted({r.turn_number for r in session_records}, reverse=True)
        working_turns = set(all_turns[:working_memory_size])

        working = [r for r in session_records if r.turn_number in working_turns]
        active_candidates = [
            r
            for r in session_records
            if r.turn_number not in working_turns and not r.is_compressed
        ]
        compressed = [r for r in session_records if r.is_compressed]

        # Sort active by decayed importance desc
        active_candidates.sort(
            key=lambda r: r.current_importance(current_tick, half_life), reverse=True
        )

        # Fill budget
        used_tokens = sum(_estimate_tokens(r.content) for r in working + compressed)
        remaining = budget_tokens - used_tokens
        active: list[MemoryRecord] = []
        dropped = 0
        for r in active_candidates:
            t = _estimate_tokens(r.content)
            if remaining >= t:
                active.append(r)
                remaining -= t
            else:
                dropped += 1

        total = sum(_estimate_tokens(r.content) for r in working + active + compressed)
        return MemoryContext(
            working=working,
            active=active,
            compressed=compressed,
            total_tokens=total,
            dropped_count=dropped,
        )

    async def compress_if_needed(
        self,
        universe_id: str,
        session_id: str | UUID,
        memory_config: dict | None = None,
    ) -> CompressionResult:
        cfg = memory_config or {}
        threshold: int = cfg.get("compression_threshold_tokens", 4000)
        importance_threshold: float = cfg.get("compression_importance_threshold", 0.5)

        session_str = str(session_id)
        active = [
            r
            for r in self._records
            if r.universe_id == universe_id
            and r.session_id == session_str
            and not r.is_compressed
            and r.tier == "active"
        ]
        token_count = sum(_estimate_tokens(r.content) for r in active)
        if token_count <= threshold:
            return CompressionResult(compressed_count=0, skipped=True)

        # Compress low-importance active records
        to_compress = [r for r in active if r.importance_score < importance_threshold]
        if not to_compress:
            return CompressionResult(compressed_count=0, skipped=True)

        summary = f"[Compressed {len(to_compress)} memories]"
        new_id = str(ULID())
        compressed_ids = [r.memory_id for r in to_compress]

        new_rec = MemoryRecord(
            memory_id=new_id,
            universe_id=universe_id,
            session_id=session_str,
            turn_number=to_compress[-1].turn_number,
            world_time_tick=to_compress[-1].world_time_tick,
            source="narrator",  # type: ignore[arg-type]
            attributed_to=None,
            content=summary,
            summary=summary,
            importance_score=0.0,
            tier="compressed",  # type: ignore[arg-type]
            is_compressed=True,
            compressed_from=compressed_ids,
        )
        # Mark originals as archived
        for r in to_compress:
            idx = self._records.index(r)
            self._records[idx] = MemoryRecord(
                memory_id=r.memory_id,
                universe_id=r.universe_id,
                session_id=r.session_id,
                turn_number=r.turn_number,
                world_time_tick=r.world_time_tick,
                source=r.source,
                attributed_to=r.attributed_to,
                content=r.content,
                summary=r.summary,
                importance_score=r.importance_score,
                tier="archived",  # type: ignore[arg-type]
                is_compressed=True,
                compressed_from=r.compressed_from,
                tags=r.tags,
                consequence_ids=r.consequence_ids,
                created_at=r.created_at,
            )
        self._records.append(new_rec)
        return CompressionResult(compressed_count=len(to_compress), new_record=new_rec)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def all_records(self) -> list[MemoryRecord]:
        return list(self._records)
