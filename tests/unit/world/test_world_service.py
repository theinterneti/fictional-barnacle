"""Tests for WorldService protocol conformance."""

from uuid import UUID, uuid4

import pytest

from tta.models.world import (
    Location,
    LocationContext,
    WorldChange,
    WorldEvent,
)
from tta.world.service import WorldService

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
            location=Location(id="x", name="X", description="X", type="x")
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
        assert not isinstance(IncompleteWorldService(), WorldService)


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
