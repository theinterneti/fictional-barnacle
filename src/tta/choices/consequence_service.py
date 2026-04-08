"""ConsequenceService — protocol and in-memory implementation.

Session-scoped service that is the authoritative source of truth for
consequence chains. TurnState holds snapshots only; this service owns
the mutable state. (S05 FR-3, FR-7, FR-8)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

import structlog

from tta.models.choice import ImpactLevel, Reversibility
from tta.models.consequence import (
    MAX_ACTIVE_CHAINS,
    ConsequenceChain,
    ConsequenceEntry,
    ConsequenceStatus,
    ConsequenceTimescale,
    ConsequenceVisibility,
    DivergenceScore,
    NarrativeAnchor,
)
from tta.models.world import WorldChange, WorldChangeType

log = structlog.get_logger()


# --- Evaluate result bundle (atomic commit) ---


class EvaluateResult:
    """Bundle returned by evaluate() for atomic commit.

    Contains chain updates, world changes, and foreshadowing hints
    from a single turn's consequence evaluation.
    """

    __slots__ = ("chain_updates", "world_changes", "hints")

    def __init__(
        self,
        chain_updates: list[ConsequenceChain] | None = None,
        world_changes: list[WorldChange] | None = None,
        hints: list[str] | None = None,
    ) -> None:
        self.chain_updates = chain_updates or []
        self.world_changes = world_changes or []
        self.hints = hints or []


# --- Pruning priority tiers (S05 FR-8) ---

# Lower = pruned first; higher = protected longer.
# Never prune pending long-term, defining, or permanent chains.
_PRUNE_PRIORITY = {
    ConsequenceStatus.RESOLVED: 0,
    ConsequenceStatus.DORMANT: 1,
    ConsequenceStatus.PRUNED: -1,  # already pruned, skip
    ConsequenceStatus.ACTIVE: 3,
    ConsequenceStatus.PENDING: 4,
}


def _chain_prune_score(chain: ConsequenceChain) -> int:
    """Score a chain for pruning priority (lower = prune first).

    Protected chains (long-term+pending, permanent, defining) get
    very high scores so they're pruned last.
    """
    # Fully resolved → prune immediately
    if chain.is_resolved:
        return 0

    base = max(
        (_PRUNE_PRIORITY.get(e.status, 2) for e in chain.entries),
        default=0,
    )

    # Protect long-term pending chains
    if any(
        e.timescale == ConsequenceTimescale.LONG_TERM
        and e.status == ConsequenceStatus.PENDING
        for e in chain.entries
    ):
        base += 10

    # Protect defining/permanent chains
    if chain.impact_level in (
        ImpactLevel.DEFINING,
        ImpactLevel.PIVOTAL,
    ):
        base += 10
    if chain.reversibility == Reversibility.PERMANENT:
        base += 5

    return base


# --- Protocol ---


@runtime_checkable
class ConsequenceService(Protocol):
    """Interface for consequence chain management.

    Separate from WorldService — this handles consequence-specific
    logic (creation, evaluation, pruning). Session-scoped.
    """

    async def create_chain(
        self,
        session_id: UUID,
        root_trigger: str,
        *,
        entries: list[ConsequenceEntry] | None = None,
        impact_level: str = ImpactLevel.ATMOSPHERIC,
        reversibility: str = Reversibility.MODERATE,
        turn: int = 0,
        parent_chain_id: UUID | None = None,
    ) -> ConsequenceChain:
        """Create a new consequence chain. Returns the chain."""
        ...

    async def evaluate(
        self,
        session_id: UUID,
        turn: int,
        player_input: str,
    ) -> EvaluateResult:
        """Evaluate all active chains for the given turn.

        Returns an atomic bundle of chain updates, world changes,
        and foreshadowing hints.
        """
        ...

    async def resolve_chain(
        self,
        chain_id: UUID,
        turn: int,
    ) -> ConsequenceChain | None:
        """Mark all entries in a chain as resolved. Returns updated chain."""
        ...

    async def get_active_chains(
        self,
        session_id: UUID,
    ) -> list[ConsequenceChain]:
        """Return all non-resolved, non-pruned chains for a session."""
        ...

    async def prune_chains(
        self,
        session_id: UUID,
        current_turn: int,
        *,
        max_chains: int = MAX_ACTIVE_CHAINS,
    ) -> list[UUID]:
        """Prune excess chains. Returns IDs of pruned chains."""
        ...

    async def get_foreshadowing_hints(
        self,
        session_id: UUID,
    ) -> list[str]:
        """Return foreshadowing hints for hidden/foreshadowed entries."""
        ...

    async def reveal_hidden_entry(
        self,
        entry_id: UUID,
    ) -> ConsequenceEntry | None:
        """Transition a hidden entry to visible. Returns updated entry."""
        ...


# --- In-memory implementation ---


class InMemoryConsequenceService:
    """In-memory ConsequenceService for testing and Wave 6.

    Session-id-keyed storage. Thread-safe enough for single-process
    async usage. Call clear() for test isolation.
    """

    def __init__(self) -> None:
        self._chains: dict[UUID, list[ConsequenceChain]] = defaultdict(list)
        self._anchors: dict[UUID, list[NarrativeAnchor]] = defaultdict(list)

    def clear(self) -> None:
        """Reset all state — use in test teardown."""
        self._chains.clear()
        self._anchors.clear()

    async def create_chain(
        self,
        session_id: UUID,
        root_trigger: str,
        *,
        entries: list[ConsequenceEntry] | None = None,
        impact_level: str = ImpactLevel.ATMOSPHERIC,
        reversibility: str = Reversibility.MODERATE,
        turn: int = 0,
        parent_chain_id: UUID | None = None,
    ) -> ConsequenceChain:
        chain_id = uuid4()
        chain = ConsequenceChain(
            id=chain_id,
            session_id=session_id,
            root_trigger=root_trigger,
            entries=entries or [],
            parent_chain_id=parent_chain_id,
            impact_level=impact_level,
            reversibility=reversibility,
            turn_created=turn,
            last_active_turn=turn,
        )
        # Fix entries to reference this chain
        for entry in chain.entries:
            entry.chain_id = chain_id
            entry.turn_created = turn
        self._chains[session_id].append(chain)
        log.debug(
            "consequence_chain_created",
            chain_id=str(chain_id),
            session_id=str(session_id),
            trigger=root_trigger,
        )
        return chain

    async def evaluate(
        self,
        session_id: UUID,
        turn: int,
        player_input: str,
    ) -> EvaluateResult:
        """Evaluate active chains for turn effects.

        For Wave 6, this does basic timescale-based activation:
        - Immediate entries activate on creation turn
        - Short-term entries activate when turn delta is in range
        - Long-term entries activate when turn delta > 10
        Hidden entries generate foreshadowing hints.
        """
        chains = self._chains.get(session_id, [])
        world_changes: list[WorldChange] = []
        hints: list[str] = []
        updated: list[ConsequenceChain] = []

        for chain in chains:
            if chain.is_resolved or chain.is_dormant:
                continue
            chain.last_active_turn = turn
            changed = False

            for entry in chain.entries:
                if entry.status != ConsequenceStatus.PENDING:
                    continue

                turns_elapsed = turn - entry.turn_created
                should_activate = False

                if entry.timescale == ConsequenceTimescale.IMMEDIATE:
                    should_activate = turns_elapsed >= 0
                elif entry.timescale == ConsequenceTimescale.SHORT_TERM:
                    should_activate = 1 <= turns_elapsed <= 10
                elif entry.timescale == ConsequenceTimescale.LONG_TERM:
                    should_activate = turns_elapsed > 10

                if should_activate:
                    if entry.visibility == ConsequenceVisibility.HIDDEN:
                        if entry.narrative_hook:
                            hints.append(entry.narrative_hook)
                        continue  # Stay pending until reveal

                    entry.status = ConsequenceStatus.ACTIVE
                    changed = True
                    world_changes.append(
                        WorldChange(
                            type=WorldChangeType.QUEST_STATUS_CHANGED,
                            entity_id=str(entry.chain_id),
                            payload={
                                "consequence_entry_id": str(entry.id),
                                "consequence_chain_id": str(entry.chain_id),
                                "effect": entry.effect,
                                "timescale": entry.timescale,
                            },
                        )
                    )

                # Foreshadowed entries always hint
                if (
                    entry.visibility == ConsequenceVisibility.FORESHADOWED
                    and entry.narrative_hook
                    and entry.status == ConsequenceStatus.PENDING
                ):
                    hints.append(entry.narrative_hook)

            if changed:
                updated.append(chain)

        return EvaluateResult(
            chain_updates=updated,
            world_changes=world_changes,
            hints=hints,
        )

    async def resolve_chain(
        self,
        chain_id: UUID,
        turn: int,
    ) -> ConsequenceChain | None:
        for chains in self._chains.values():
            for chain in chains:
                if chain.id == chain_id:
                    for entry in chain.entries:
                        if entry.status in (
                            ConsequenceStatus.PENDING,
                            ConsequenceStatus.ACTIVE,
                        ):
                            entry.status = ConsequenceStatus.RESOLVED
                            entry.turn_resolved = turn
                    return chain
        return None

    async def get_active_chains(
        self,
        session_id: UUID,
    ) -> list[ConsequenceChain]:
        return [
            c
            for c in self._chains.get(session_id, [])
            if not c.is_resolved and not c.is_dormant
        ]

    async def prune_chains(
        self,
        session_id: UUID,
        current_turn: int,
        *,
        max_chains: int = MAX_ACTIVE_CHAINS,
    ) -> list[UUID]:
        chains = self._chains.get(session_id, [])
        pruned_ids: list[UUID] = []

        # Mark dormant chains first (50+ turns inactive, S05 FR-8)
        for chain in chains:
            if (
                not chain.is_resolved
                and not chain.is_dormant
                and current_turn - chain.last_active_turn >= 50
            ):
                chain.is_dormant = True
                for entry in chain.entries:
                    if entry.status in (
                        ConsequenceStatus.PENDING,
                        ConsequenceStatus.ACTIVE,
                    ):
                        entry.status = ConsequenceStatus.DORMANT

        # Capacity pruning
        active = [c for c in chains if not c.is_resolved and not c.is_dormant]
        if len(active) <= max_chains:
            return pruned_ids

        scored = sorted(active, key=_chain_prune_score)
        to_prune = len(active) - max_chains

        for chain in scored[:to_prune]:
            for entry in chain.entries:
                entry.status = ConsequenceStatus.PRUNED
            pruned_ids.append(chain.id)
            log.debug(
                "consequence_chain_pruned",
                chain_id=str(chain.id),
                reason="over_capacity",
            )

        return pruned_ids

    async def get_foreshadowing_hints(
        self,
        session_id: UUID,
    ) -> list[str]:
        hints: list[str] = []
        for chain in self._chains.get(session_id, []):
            if chain.is_resolved or chain.is_dormant:
                continue
            for entry in chain.entries:
                if (
                    entry.visibility
                    in (
                        ConsequenceVisibility.HIDDEN,
                        ConsequenceVisibility.FORESHADOWED,
                    )
                    and entry.status == ConsequenceStatus.PENDING
                    and entry.narrative_hook
                ):
                    hints.append(entry.narrative_hook)
        return hints

    async def reveal_hidden_entry(
        self,
        entry_id: UUID,
    ) -> ConsequenceEntry | None:
        for chains in self._chains.values():
            for chain in chains:
                for entry in chain.entries:
                    if (
                        entry.id == entry_id
                        and entry.visibility == ConsequenceVisibility.HIDDEN
                    ):
                        entry.visibility = ConsequenceVisibility.VISIBLE
                        entry.status = ConsequenceStatus.ACTIVE
                        return entry
        return None

    # --- Anchor management (S05 FR-4) ---

    async def add_anchor(
        self,
        session_id: UUID,
        description: str,
        target_turn: int | None = None,
    ) -> NarrativeAnchor:
        anchor = NarrativeAnchor(
            session_id=session_id,
            description=description,
            target_turn=target_turn,
        )
        self._anchors[session_id].append(anchor)
        return anchor

    async def get_active_anchors(
        self,
        session_id: UUID,
    ) -> list[NarrativeAnchor]:
        return [
            a
            for a in self._anchors.get(session_id, [])
            if a.is_active and not a.is_reached
        ]

    async def calculate_divergence(
        self,
        session_id: UUID,
        current_turn: int,
    ) -> DivergenceScore:
        """Calculate divergence from nearest active anchor.

        Simple heuristic for Wave 6: ratio of active chains to
        max chains, weighted by anchor proximity.
        """
        anchors = await self.get_active_anchors(session_id)
        chains = await self.get_active_chains(session_id)

        if not anchors:
            return DivergenceScore(
                score=0.0,
                turn_number=current_turn,
                factors={"reason": "no_active_anchors"},
            )

        # Find nearest anchor
        nearest = min(
            anchors,
            key=lambda a: abs((a.target_turn or current_turn) - current_turn),
        )

        # Divergence factors
        chain_ratio = len(chains) / MAX_ACTIVE_CHAINS
        # How many chains are high-impact
        high_impact_count = sum(
            1
            for c in chains
            if c.impact_level in (ImpactLevel.PIVOTAL, ImpactLevel.DEFINING)
        )
        high_impact_ratio = high_impact_count / len(chains) if chains else 0.0

        # Simple weighted score
        score = min(1.0, (chain_ratio * 0.4) + (high_impact_ratio * 0.6))

        return DivergenceScore(
            score=score,
            nearest_anchor_id=nearest.id,
            turn_number=current_turn,
            factors={
                "chain_count": len(chains),
                "chain_ratio": round(chain_ratio, 3),
                "high_impact_count": high_impact_count,
                "high_impact_ratio": round(high_impact_ratio, 3),
            },
        )
