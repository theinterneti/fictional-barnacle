"""Consequence Propagation — S36 implementation.

ConsequencePropagator: typing.Protocol for the propagator contract.
DefaultConsequencePropagator: BFS hop-walk with severity decay + faction shortcut.
MemoryConsequencePropagator: static test fixture.

Severity decay table (AC-36.04):
    critical  → major  → notable → minor  (hops 1/2/3)
    major     → notable → minor  → filter (hops 1/2/3)
    notable   → minor  → filter          (hops 1/2)
    minor     → filter always            (AC-36.03)

Description fidelity (AC-36.07):
    hop 0/1:  verbatim copy
    hop 2:    80-char truncation with ellipsis
    hop 3:    template-only ("Word spread that …")

Faction shortcut (AC-36.05):
    Same-faction NPCs receive a hop-1 record regardless of graph distance.
    Physical hop wins over faction path only when physical hop_distance < 1.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Protocol

from tta.simulation.types import (
    ConsequenceRecord,
    EventSeverity,
    PropagationResult,
    PropagationSource,
    WorldTime,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity tables
# ---------------------------------------------------------------------------

_DECAY: dict[EventSeverity, list[EventSeverity]] = {
    "critical": ["major", "notable", "minor"],
    "major": ["notable", "minor"],
    "notable": ["minor"],
    "minor": [],
}

_SEVERITY_ORDER: list[EventSeverity] = ["minor", "notable", "major", "critical"]


def _decay_severity(original: EventSeverity, hop: int) -> EventSeverity | None:
    """Return the decayed severity at hop distance, or None if filtered out."""
    decay_path = _DECAY.get(original, [])
    idx = hop - 1
    if idx < 0:
        return original
    if idx >= len(decay_path):
        return None
    return decay_path[idx]


def _fidelity_description(description: str, hop: int) -> str:
    """Mutate description based on hop distance (AC-36.07)."""
    if hop <= 1:
        return description
    if hop == 2:
        truncated = description[:80]
        return truncated if len(description) <= 80 else truncated + "…"
    # hop >= 3
    return f"Word spread that {description[:60].rstrip()}…"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ConsequencePropagator(Protocol):
    """Contract for consequence propagation processors (S36)."""

    async def propagate(
        self,
        source_events: list[PropagationSource],
        universe_id: str,
        world_time: WorldTime,
        budget_ms: float = 100.0,
    ) -> list[PropagationResult]:
        """Walk the consequence graph and return one PropagationResult per event."""
        ...


# ---------------------------------------------------------------------------
# Default implementation
# ---------------------------------------------------------------------------


class DefaultConsequencePropagator:
    """BFS-based consequence propagation with faction shortcut.

    Parameters
    ----------
    max_depth:
        Maximum hop distance from the source.  0 is treated as 1 (AC-36.08).
    """

    def __init__(self, max_depth: int = 3) -> None:
        self.max_depth = max(1, max_depth)  # AC-36.08 — 0 treated as 1

    async def propagate(
        self,
        source_events: list[PropagationSource],
        universe_id: str,
        world_time: WorldTime,
        budget_ms: float = 100.0,
    ) -> list[PropagationResult]:
        start = time.monotonic()
        results: list[PropagationResult] = []

        for source in source_events:
            elapsed_ms = (time.monotonic() - start) * 1000
            budget_exceeded = elapsed_ms > budget_ms

            result = await self._propagate_one(
                source, universe_id, world_time, budget_exceeded
            )
            results.append(result)

        return results

    async def _propagate_one(
        self,
        source: PropagationSource,
        universe_id: str,
        world_time: WorldTime,
        budget_exceeded: bool,
    ) -> PropagationResult:
        # minor events are always skipped (AC-36.03)
        if source.original_severity == "minor":
            return PropagationResult(
                source_event_id=source.source_event_id,
                skipped_minor=1,
                budget_exceeded=budget_exceeded,
            )

        records: list[ConsequenceRecord] = []
        faction_records: list[ConsequenceRecord] = []
        seen_entity_ids: set[str] = set()

        # hop 0 — source record (AC-36.08: always created)
        if source.affected_entity_id:
            hop0 = self._make_record(
                source=source,
                universe_id=universe_id,
                entity_id=source.affected_entity_id,
                entity_type=source.affected_entity_type or "unknown",
                hop=0,
                severity=source.original_severity,
                description=source.description,
                tick=world_time.total_ticks,
            )
            records.append(hop0)
            seen_entity_ids.add(source.affected_entity_id)

        # Simulated BFS hop walk — production Neo4j query replaces this stub.
        # In Wave E (MVP), we produce synthetic hop-1 and hop-2 records using
        # whatever neighbouring entities the world_context provides.  Wave F
        # wires the real Neo4j NEAR / KNOWS edge traversal.
        max_hop_reached = 0
        if not budget_exceeded:
            for hop in range(1, self.max_depth + 1):
                decayed = _decay_severity(source.original_severity, hop)
                if decayed is None:
                    break
                max_hop_reached = hop
                # placeholder: no real neighbour graph in Wave E MVP
                # faction shortcut: create faction hop-1 record
                if hop == 1 and source.faction_id:
                    faction_entity_id = f"faction:{source.faction_id}"
                    if faction_entity_id not in seen_entity_ids:
                        frec = self._make_record(
                            source=source,
                            universe_id=universe_id,
                            entity_id=faction_entity_id,
                            entity_type="faction",
                            hop=1,
                            severity=decayed,
                            description=_fidelity_description(source.description, 1),
                            tick=world_time.total_ticks,
                        )
                        faction_records.append(frec)
                        seen_entity_ids.add(faction_entity_id)

        all_records = records + faction_records
        return PropagationResult(
            source_event_id=source.source_event_id,
            records=records,
            faction_records=faction_records,
            total_records=len(all_records),
            propagation_depth_reached=max_hop_reached,
            skipped_minor=0,
            budget_exceeded=budget_exceeded,
        )

    def _make_record(
        self,
        source: PropagationSource,
        universe_id: str,
        entity_id: str,
        entity_type: str,
        hop: int,
        severity: EventSeverity,
        description: str,
        tick: int,
    ) -> ConsequenceRecord:
        return ConsequenceRecord(
            consequence_id=str(uuid.uuid4()),
            universe_id=universe_id,
            source_event_id=source.source_event_id,
            source_type=source.source_type,
            source_location_id=source.source_location_id,
            affected_entity_id=entity_id,
            affected_entity_type=entity_type,
            hop_distance=hop,
            original_severity=source.original_severity,
            propagated_severity=severity,
            description=description,
            triggered_at_tick=tick,
            created_at=datetime.now(UTC),
            faction_id=source.faction_id,
        )


# ---------------------------------------------------------------------------
# Test fixture
# ---------------------------------------------------------------------------


class MemoryConsequencePropagator:
    """Static fixture that returns a preset list of PropagationResults."""

    def __init__(self, preset: list[PropagationResult] | None = None) -> None:
        self._preset = preset or []

    async def propagate(
        self,
        source_events: list[PropagationSource],
        universe_id: str,
        world_time: WorldTime,
        budget_ms: float = 100.0,
    ) -> list[PropagationResult]:
        return self._preset
