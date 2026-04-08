"""WorldService protocol and default implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

import structlog

from tta.models.world import (
    Location,
    LocationContext,
    WorldChange,
    WorldContext,
    WorldEvent,
    WorldSeed,
)

if TYPE_CHECKING:
    from tta.persistence.repositories import WorldEventRepository

log = structlog.get_logger()


@runtime_checkable
class WorldService(Protocol):
    """Interface for world graph operations.

    Implemented by Neo4j in Wave 3. Consumers depend on
    this protocol so they can be tested with in-memory fakes.
    """

    async def get_location_context(
        self,
        session_id: UUID,
        location_id: str,
        depth: int = 1,
    ) -> LocationContext: ...

    async def get_recent_events(
        self,
        session_id: UUID,
        limit: int = 5,
    ) -> list[WorldEvent]: ...

    async def apply_world_changes(
        self,
        session_id: UUID,
        changes: list[WorldChange],
    ) -> None: ...

    async def get_player_location(
        self,
        session_id: UUID,
    ) -> Location: ...

    # -- Wave 3 additions --

    async def create_world_graph(
        self,
        session_id: UUID,
        world_seed: WorldSeed,
    ) -> None: ...

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None: ...

    async def validate_movement(
        self,
        session_id: UUID,
        from_id: str,
        to_id: str,
    ) -> bool: ...

    async def get_world_state(
        self,
        session_id: UUID,
    ) -> WorldContext: ...


class DefaultWorldService:
    """World service backed by PostgreSQL event repository.

    Delegates event operations to a WorldEventRepository.
    Location/graph operations require Neo4j and raise
    NotImplementedError until that integration lands.
    """

    def __init__(self, event_repo: WorldEventRepository) -> None:
        self._event_repo = event_repo

    async def get_recent_events(
        self,
        session_id: UUID,
        limit: int = 5,
    ) -> list[WorldEvent]:
        return await self._event_repo.get_recent_events(
            session_id, limit
        )

    async def get_location_context(
        self,
        session_id: UUID,
        location_id: str,
        depth: int = 1,
    ) -> LocationContext:
        raise NotImplementedError(
            "get_location_context requires Neo4j"
        )

    async def apply_world_changes(
        self,
        session_id: UUID,
        changes: list[WorldChange],
    ) -> None:
        raise NotImplementedError(
            "apply_world_changes requires Neo4j"
        )

    async def get_player_location(
        self,
        session_id: UUID,
    ) -> Location:
        raise NotImplementedError(
            "get_player_location requires Neo4j"
        )

    async def create_world_graph(
        self,
        session_id: UUID,
        world_seed: WorldSeed,
    ) -> None:
        raise NotImplementedError(
            "create_world_graph requires Neo4j"
        )

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None:
        raise NotImplementedError(
            "cleanup_session requires Neo4j"
        )

    async def validate_movement(
        self,
        session_id: UUID,
        from_id: str,
        to_id: str,
    ) -> bool:
        raise NotImplementedError(
            "validate_movement requires Neo4j"
        )

    async def get_world_state(
        self,
        session_id: UUID,
    ) -> WorldContext:
        raise NotImplementedError(
            "get_world_state requires Neo4j"
        )
