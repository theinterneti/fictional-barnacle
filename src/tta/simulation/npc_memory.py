"""NPC Episodic Memory and Social Graph Writer (S38).

SocialMemoryWriter persists NPCEpisodicMemory records and NPCSocialEdge
relationships to Neo4j. GossipPropagator propagates gossip through the
social graph using template-based distortion (no LLM, NFR-38.04).

InMemorySocialMemoryWriter is the injectable test double.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ulid import ULID

from tta.simulation.types import (
    GossipEvent,
    NPCEpisodicMemory,
    NPCSocialContext,
    NPCSocialEdge,
)

if TYPE_CHECKING:
    from tta.simulation.types import WorldTime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (S38 FR-38.05)
# ---------------------------------------------------------------------------

_GOSSIP_RELIABILITY_DECREMENT = 0.2
_GOSSIP_RELIABILITY_FLOOR = 0.2

_GOSSIP_TEMPLATES = [
    "Rumour has it: {content}",
    "Word is going around that {content}",
    "Someone mentioned that {content}",
    "I heard through the grapevine: {content}",
]


def _distort_content(content: str, hop_count: int) -> str:
    """Apply simple template distortion — no LLM (NFR-38.04)."""
    template = _GOSSIP_TEMPLATES[hop_count % len(_GOSSIP_TEMPLATES)]
    return template.format(content=content)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SocialMemoryWriter(Protocol):
    """Injectable NPC social-memory service (S38 FR-38.04)."""

    async def record_episode(
        self,
        npc_id: str,
        universe_id: str,
        session_id: UUID,
        turn_number: int,
        world_time: WorldTime,
        content: str,
        source_memory_id: str | None,
        consequence_id: str | None,
        player_id: str,
        emotional_valence: float,
        relationship_delta: object | None,
        importance_score: float,
        is_gossip: bool,
        gossip_source_npc_id: str | None,
    ) -> NPCEpisodicMemory: ...

    async def propagate_gossip(
        self,
        episode: NPCEpisodicMemory,
        social_config: dict,
    ) -> list[GossipEvent]: ...

    async def get_npc_context(
        self,
        npc_id: str,
        universe_id: str,
        session_id: UUID,
        player_id: str = "",
        budget_tokens: int = 8000,
        npc_tier: str = "BACKGROUND",
    ) -> NPCSocialContext: ...

    async def get_relationship(
        self,
        source_npc_id: str,
        target_id: str,
        universe_id: str,
    ) -> NPCSocialEdge | None: ...

    async def update_relationship(
        self,
        edge: NPCSocialEdge,
    ) -> None: ...


# ---------------------------------------------------------------------------
# In-memory test double
# ---------------------------------------------------------------------------


class InMemorySocialMemoryWriter:
    """In-process SocialMemoryWriter backed by dicts. Used in tests."""

    def __init__(self) -> None:
        self._episodes: list[NPCEpisodicMemory] = []
        self._edges: dict[tuple[str, str, str], NPCSocialEdge] = {}
        self._gossip: list[GossipEvent] = []
        # Track originating_episode_id seen per receiver to enforce idempotency
        self._seen_gossip: set[tuple[str, str]] = set()  # (receiver, origin_ep_id)

    async def record_episode(
        self,
        npc_id: str,
        universe_id: str,
        session_id: UUID,
        turn_number: int,
        world_time: WorldTime,
        content: str,
        source_memory_id: str | None = None,
        consequence_id: str | None = None,
        player_id: str = "",
        emotional_valence: float = 0.0,
        relationship_delta: object | None = None,
        importance_score: float = 0.5,
        is_gossip: bool = False,
        gossip_source_npc_id: str | None = None,
    ) -> NPCEpisodicMemory:
        ep = NPCEpisodicMemory(
            episode_id=str(ULID()),
            npc_id=npc_id,
            universe_id=universe_id,
            session_id=str(session_id),
            turn_number=turn_number,
            world_time_tick=world_time.total_ticks,
            source_memory_id=source_memory_id,
            consequence_id=consequence_id,
            player_id=player_id,
            content=content,
            emotional_valence=emotional_valence,
            relationship_delta=relationship_delta,
            importance_score=importance_score,
            is_gossip=is_gossip,
            gossip_source_npc_id=gossip_source_npc_id,
        )
        self._episodes.append(ep)
        return ep

    async def propagate_gossip(
        self,
        episode: NPCEpisodicMemory,
        social_config: dict | None = None,
    ) -> list[GossipEvent]:
        """Propagate gossip up to max_hops through the KNOWS graph (S38 FR-38.05)."""
        cfg = social_config or {}
        max_hops: int = cfg.get("max_gossip_hops", 2)
        familiarity_threshold: float = cfg.get("gossip_familiarity_threshold", 30)

        new_events: list[GossipEvent] = []

        # BFS queue: (sender_npc_id, content, hop_count, reliability, source_ep_id)
        queue: deque[tuple[str, str, int, float, str]] = deque(
            [(episode.npc_id, episode.content, 0, 1.0, episode.episode_id)]
        )

        while queue:
            sender_id, content, hop_count, reliability, origin_ep_id = queue.popleft()

            if hop_count >= max_hops:
                continue

            next_reliability = reliability - _GOSSIP_RELIABILITY_DECREMENT
            if next_reliability < _GOSSIP_RELIABILITY_FLOOR:
                continue

            # Find social edges from sender in this universe
            neighbors = [
                edge
                for (src, _tgt, uni), edge in self._edges.items()
                if src == sender_id
                and uni == episode.universe_id
                and edge.gossip_weight * 100 >= familiarity_threshold
            ]

            for edge in neighbors:
                receiver_id = edge.target_id
                idempotency_key = (receiver_id, origin_ep_id)
                if idempotency_key in self._seen_gossip:
                    continue
                self._seen_gossip.add(idempotency_key)

                next_content = _distort_content(content, hop_count + 1)
                event = GossipEvent(
                    gossip_id=str(ULID()),
                    universe_id=episode.universe_id,
                    originating_episode_id=origin_ep_id,
                    sender_npc_id=sender_id,
                    receiver_npc_id=receiver_id,
                    content=next_content,
                    hop_count=hop_count + 1,
                    reliability=next_reliability,
                    session_id=episode.session_id,
                    world_time_tick=episode.world_time_tick,
                )
                self._gossip.append(event)
                new_events.append(event)

                # Receiver gets their own episodic memory of the gossip
                receiver_ep = NPCEpisodicMemory(
                    episode_id=str(ULID()),
                    npc_id=receiver_id,
                    universe_id=episode.universe_id,
                    session_id=episode.session_id,
                    turn_number=episode.turn_number,
                    world_time_tick=episode.world_time_tick,
                    source_memory_id=None,
                    consequence_id=None,
                    player_id="",
                    content=next_content,
                    importance_score=max(
                        0.1, episode.importance_score * next_reliability
                    ),
                    emotional_valence=0.0,
                    relationship_delta=None,
                    is_gossip=True,
                    gossip_source_npc_id=sender_id,
                )
                self._episodes.append(receiver_ep)

                queue.append(
                    (
                        receiver_id,
                        next_content,
                        hop_count + 1,
                        next_reliability,
                        origin_ep_id,
                    )
                )

        return new_events

    async def get_npc_context(
        self,
        npc_id: str,
        universe_id: str,
        session_id: UUID,
        player_id: str = "",
        budget_tokens: int = 8000,
        npc_tier: str = "BACKGROUND",
    ) -> NPCSocialContext:
        session_str = str(session_id)
        episodes = [
            ep
            for ep in self._episodes
            if ep.npc_id == npc_id
            and ep.universe_id == universe_id
            and (npc_tier == "KEY" or ep.session_id == session_str)
        ]
        episodes.sort(key=lambda e: e.importance_score, reverse=True)

        gossip = [
            g
            for g in self._gossip
            if g.receiver_npc_id == npc_id
            and g.universe_id == universe_id
            and g.session_id == session_str
        ]

        # Pick first outgoing edge as the primary relationship
        relationship = next(
            (
                edge
                for edge in self._edges.values()
                if edge.source_npc_id == npc_id and edge.universe_id == universe_id
            ),
            None,
        )

        return NPCSocialContext(
            npc_id=npc_id,
            player_id=player_id,
            relationship=relationship,
            episodes=episodes,
            gossip_received=gossip,
        )

    async def get_relationship(
        self,
        source_npc_id: str,
        target_id: str,
        universe_id: str,
    ) -> NPCSocialEdge | None:
        return self._edges.get((source_npc_id, target_id, universe_id))

    async def update_relationship(self, edge: NPCSocialEdge) -> None:
        key = (edge.source_npc_id, edge.target_id, edge.universe_id)
        self._edges[key] = edge

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def all_episodes(self) -> list[NPCEpisodicMemory]:
        return list(self._episodes)

    def all_gossip(self) -> list[GossipEvent]:
        return list(self._gossip)

    def all_edges(self) -> list[NPCSocialEdge]:
        return list(self._edges.values())


# ---------------------------------------------------------------------------
# GossipPropagator — standalone utility (delegates to SocialMemoryWriter)
# ---------------------------------------------------------------------------


class GossipPropagator:
    """Standalone gossip propagator; delegates to SocialMemoryWriter."""

    def __init__(self, writer: SocialMemoryWriter) -> None:  # type: ignore[type-arg]
        self._writer = writer

    async def propagate(
        self,
        episode: NPCEpisodicMemory,
        social_config: dict | None = None,
    ) -> list[GossipEvent]:
        return await self._writer.propagate_gossip(episode, social_config or {})
