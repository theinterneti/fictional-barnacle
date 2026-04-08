"""Tests for WorldService protocol conformance and DefaultWorldService."""

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from tta.models.world import (
    Location,
    LocationContext,
    TemplateMetadata,
    WorldChange,
    WorldContext,
    WorldEvent,
    WorldSeed,
    WorldTemplate,
)
from tta.world.service import DefaultWorldService, WorldService

# ── Mock implementation ──────────────────────────────────────────


class MockWorldService:
    """In-memory fake that satisfies the WorldService protocol."""

    def __init__(self) -> None:
        self._location = Location(
            id="tavern",
            name="The Rusty Flagon",
            description="A dimly lit tavern.",
            type="interior",
        )

    async def get_location_context(
        self,
        session_id: UUID,
        location_id: str,
        depth: int = 1,
    ) -> LocationContext:
        return LocationContext(location=self._location)

    async def get_recent_events(
        self,
        session_id: UUID,
        limit: int = 5,
    ) -> list[WorldEvent]:
        return []

    async def apply_world_changes(
        self,
        session_id: UUID,
        changes: list[WorldChange],
    ) -> None:
        return None

    async def get_player_location(
        self,
        session_id: UUID,
    ) -> Location:
        return self._location

    # -- Wave 3 additions --

    async def create_world_graph(
        self,
        session_id: UUID,
        world_seed: WorldSeed,
    ) -> None:
        return None

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None:
        return None

    async def validate_movement(
        self,
        session_id: UUID,
        from_id: str,
        to_id: str,
    ) -> bool:
        return True

    async def get_world_state(
        self,
        session_id: UUID,
    ) -> WorldContext:
        return WorldContext(
            current_location=self._location,
        )


# ── Incomplete implementation (missing a method) ─────────────────


class IncompleteWorldService:
    """Intentionally missing get_player_location."""

    async def get_location_context(
        self,
        session_id: UUID,
        location_id: str,
        depth: int = 1,
    ) -> LocationContext:
        return LocationContext(
            location=Location(
                id="x", name="X", description="X", type="x"
            )
        )

    async def get_recent_events(
        self,
        session_id: UUID,
        limit: int = 5,
    ) -> list[WorldEvent]:
        return []

    async def apply_world_changes(
        self,
        session_id: UUID,
        changes: list[WorldChange],
    ) -> None:
        return None


# ── Protocol conformance tests ───────────────────────────────────


class TestWorldServiceProtocol:
    """Verify structural typing behaviour of WorldService."""

    def test_mock_satisfies_protocol(self) -> None:
        """A class implementing all methods is a WorldService."""
        svc: WorldService = MockWorldService()
        assert isinstance(svc, WorldService)

    def test_incomplete_class_does_not_satisfy(self) -> None:
        """A class missing a method is NOT a WorldService."""
        assert not isinstance(
            IncompleteWorldService(), WorldService
        )


# ── Functional tests on MockWorldService ─────────────────────────


class TestMockWorldService:
    """Smoke-test the mock to prove it returns canned data."""

    @pytest.fixture
    def svc(self) -> MockWorldService:
        return MockWorldService()

    @pytest.fixture
    def session_id(self) -> UUID:
        return uuid4()

    async def test_get_player_location(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        loc = await svc.get_player_location(session_id)
        assert loc.id == "tavern"
        assert loc.name == "The Rusty Flagon"

    async def test_get_location_context(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        ctx = await svc.get_location_context(session_id, "tavern")
        assert ctx.location.id == "tavern"
        assert ctx.adjacent_locations == []

    async def test_get_recent_events_empty(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        events = await svc.get_recent_events(session_id)
        assert events == []

    async def test_apply_world_changes_no_op(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        result = await svc.apply_world_changes(session_id, [])
        assert result is None

    async def test_create_world_graph(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        meta = TemplateMetadata(template_key="t", display_name="T")
        seed = WorldSeed(template=WorldTemplate(metadata=meta))
        result = await svc.create_world_graph(session_id, seed)
        assert result is None

    async def test_cleanup_session(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        result = await svc.cleanup_session(session_id)
        assert result is None

    async def test_validate_movement(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        ok = await svc.validate_movement(
            session_id, "loc-1", "loc-2"
        )
        assert ok is True

    async def test_get_world_state(
        self, svc: MockWorldService, session_id: UUID
    ) -> None:
        ctx = await svc.get_world_state(session_id)
        assert ctx.current_location.id == "tavern"


# ── DefaultWorldService tests ────────────────────────────────────


class TestDefaultWorldService:
    """Tests for the concrete DefaultWorldService."""

    @pytest.fixture
    def event_repo(self) -> AsyncMock:
        repo = AsyncMock()
        repo.get_recent_events.return_value = []
        return repo

    @pytest.fixture
    def svc(self, event_repo: AsyncMock) -> DefaultWorldService:
        return DefaultWorldService(event_repo=event_repo)

    @pytest.fixture
    def session_id(self) -> UUID:
        return uuid4()

    def test_satisfies_protocol(
        self, svc: DefaultWorldService
    ) -> None:
        """DefaultWorldService is a valid WorldService."""
        assert isinstance(svc, WorldService)

    async def test_get_recent_events_delegates(
        self,
        svc: DefaultWorldService,
        event_repo: AsyncMock,
        session_id: UUID,
    ) -> None:
        """Delegates to the event repository."""
        sid = session_id
        event = WorldEvent(
            session_id=sid,
            event_type="npc_moved",
            entity_id="npc-1",
        )
        event_repo.get_recent_events.return_value = [event]

        result = await svc.get_recent_events(sid, limit=3)

        assert result == [event]
        event_repo.get_recent_events.assert_awaited_once_with(
            sid, 3
        )

    async def test_get_recent_events_empty(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        """Returns empty list when no events exist."""
        result = await svc.get_recent_events(session_id)
        assert result == []

    async def test_get_location_context_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.get_location_context(session_id, "tavern")

    async def test_apply_world_changes_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.apply_world_changes(session_id, [])

    async def test_get_player_location_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.get_player_location(session_id)

    async def test_create_world_graph_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        meta = TemplateMetadata(template_key="t", display_name="T")
        seed = WorldSeed(template=WorldTemplate(metadata=meta))
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.create_world_graph(session_id, seed)

    async def test_cleanup_session_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.cleanup_session(session_id)

    async def test_validate_movement_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.validate_movement(
                session_id, "loc-1", "loc-2"
            )

    async def test_get_world_state_not_implemented(
        self,
        svc: DefaultWorldService,
        session_id: UUID,
    ) -> None:
        with pytest.raises(NotImplementedError, match="Neo4j"):
            await svc.get_world_state(session_id)
