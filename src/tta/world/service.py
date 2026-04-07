"""WorldService protocol — interface for world graph operations."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from tta.models.world import (
    Location,
    LocationContext,
    WorldChange,
    WorldEvent,
)


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
