"""NPC dialogue context assembly (S06 FR-6).

Builds per-NPC dialogue context dicts for injection into the
generation prompt, combining NPC state with relationship data
and trust-gated knowledge reveal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from tta.models.world import (
    NPC,
    NPCDialogueContext,
    NPCTier,
    trust_to_label,
)

if TYPE_CHECKING:
    from uuid import UUID

    from tta.world.relationship_service import RelationshipService

logger = structlog.get_logger(__name__)

# Trust thresholds for knowledge gating (S06 FR-6.2)
KNOWLEDGE_TRUST_THRESHOLD: int = 10
GOALS_TRUST_THRESHOLD: int = 30


async def build_dialogue_context(
    npc: NPC,
    session_id: UUID,
    source_id: str,
    relationship_service: RelationshipService | None = None,
) -> NPCDialogueContext:
    """Assemble dialogue context for a single NPC.

    Combines static NPC data with live relationship dimensions.
    Knowledge and goals are trust-gated: only revealed when the
    player-NPC trust exceeds the relevant threshold.

    Args:
        npc: The NPC to build context for.
        session_id: Active game session.
        source_id: The entity viewing the NPC (usually player).
        relationship_service: Optional relationship lookup.

    Returns:
        Populated NPCDialogueContext ready for prompt injection.
    """
    trust = 0
    affinity = 0
    label = trust_to_label(0)

    if relationship_service is not None:
        rel = await relationship_service.get_relationship(session_id, source_id, npc.id)
        if rel is not None:
            trust = rel.dimensions.trust
            affinity = rel.dimensions.affinity
            label = rel.dimensions.label

    # Trust-gated fields
    knowledge = npc.knowledge_summary if trust >= KNOWLEDGE_TRUST_THRESHOLD else None
    goals = npc.goals_short if trust >= GOALS_TRUST_THRESHOLD else None

    ctx = NPCDialogueContext(
        npc_id=npc.id,
        npc_name=npc.name,
        personality=npc.personality,
        voice=npc.voice,
        disposition=npc.disposition,
        traits=list(npc.traits),
        knowledge_summary=knowledge,
        goals_short=goals,
        relationship_label=label,
        relationship_trust=trust,
        relationship_affinity=affinity,
        emotional_state=npc.state,
        occupation=npc.occupation,
        mannerisms=npc.mannerisms,
    )

    logger.debug(
        "dialogue_context_built",
        npc_id=npc.id,
        tier=npc.tier,
        trust=trust,
        label=label,
    )
    return ctx


async def build_dialogue_contexts_for_location(
    npcs: list[NPC],
    session_id: UUID,
    source_id: str,
    relationship_service: RelationshipService | None = None,
) -> list[dict]:
    """Build dialogue contexts for all NPCs present at a location.

    Background-tier NPCs get a minimal context; key and supporting
    NPCs get full dialogue context assembly.

    Returns a list of dicts suitable for prompt template injection.
    """
    contexts: list[dict] = []
    for npc in npcs:
        if npc.tier == NPCTier.BACKGROUND:
            # Background NPCs get minimal context
            contexts.append(
                NPCDialogueContext(
                    npc_id=npc.id,
                    npc_name=npc.name,
                    disposition=npc.disposition,
                ).model_dump(exclude_none=True)
            )
        else:
            ctx = await build_dialogue_context(
                npc, session_id, source_id, relationship_service
            )
            contexts.append(ctx.model_dump(exclude_none=True))

    logger.debug(
        "location_dialogue_contexts",
        count=len(contexts),
        session_id=str(session_id),
    )
    return contexts
