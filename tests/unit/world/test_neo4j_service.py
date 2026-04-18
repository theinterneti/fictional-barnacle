"""Tests for Neo4jWorldService (mocked driver)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from tta.models.world import (
    Location,
    LocationContext,
    TemplateConnection,
    TemplateLocation,
    TemplateMetadata,
    TemplateNPC,
    TemplateRegion,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldSeed,
    WorldTemplate,
)
from tta.world.neo4j_service import Neo4jWorldService
from tta.world.service import WorldService

# ── Helpers ──────────────────────────────────────────────────────


def _make_driver() -> MagicMock:
    """Return a mocked neo4j.AsyncDriver.

    ``session()`` is synchronous on a real driver,
    so we use ``MagicMock`` as the top-level mock.
    """
    return MagicMock()


def _loc_node(
    *,
    id: str = "loc-1",
    name: str = "Tavern",
    description: str = "A tavern.",
    type: str = "interior",
    visited: bool = False,
    region_id: str | None = None,
    light_level: str = "lit",
    is_accessible: bool = True,
    template_key: str | None = None,
) -> dict:
    """Build a fake Neo4j node dict for a Location."""
    return {
        "id": id,
        "name": name,
        "description": description,
        "type": type,
        "visited": visited,
        "region_id": region_id,
        "light_level": light_level,
        "is_accessible": is_accessible,
        "template_key": template_key,
    }


def _npc_node(
    *,
    id: str = "npc-1",
    name: str = "Barkeep",
    description: str = "The barkeep.",
    disposition: str = "friendly",
    alive: bool = True,
    role: str | None = "merchant",
    state: str = "idle",
    template_key: str | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "description": description,
        "disposition": disposition,
        "alive": alive,
        "role": role,
        "state": state,
        "template_key": template_key,
    }


def _item_node(
    *,
    id: str = "item-1",
    name: str = "Rusty Sword",
    description: str = "A sword.",
    portable: bool = True,
    hidden: bool = False,
    item_type: str | None = "weapon",
    template_key: str | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "description": description,
        "portable": portable,
        "hidden": hidden,
        "item_type": item_type,
        "template_key": template_key,
    }


def _make_async_cm(value: object) -> MagicMock:
    """Build a mock that works as ``async with x as v``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _setup_session_run(
    driver: MagicMock,
    record_data: dict | None,
) -> AsyncMock:
    """Wire driver → session → result → single().

    Returns the mock session's ``run`` coroutine.
    """
    # Build record mock so ``record["key"]`` works.
    if record_data is not None:
        mock_record = MagicMock()
        mock_record.__getitem__ = lambda self, key: record_data[key]
    else:
        mock_record = None

    mock_result = AsyncMock()
    mock_result.single.return_value = mock_record

    mock_session = MagicMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    driver.session.return_value = mock_session
    return mock_session


def _setup_tx_session(
    driver: MagicMock,
) -> tuple[MagicMock, AsyncMock]:
    """Wire driver → session → begin_transaction → tx.

    Returns ``(mock_session, mock_tx)``.
    """
    mock_tx = MagicMock()
    mock_tx.run = AsyncMock()
    mock_tx.commit = AsyncMock()
    mock_tx.__aenter__ = AsyncMock(return_value=mock_tx)
    mock_tx.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.begin_transaction = AsyncMock(return_value=mock_tx)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    driver.session.return_value = mock_session
    return mock_session, mock_tx


def _make_seed() -> WorldSeed:
    """Return a minimal WorldSeed for testing."""
    meta = TemplateMetadata(
        template_key="test",
        display_name="Test World",
    )
    return WorldSeed(
        template=WorldTemplate(
            metadata=meta,
            regions=[
                TemplateRegion(
                    key="town",
                    archetype="A small town",
                ),
            ],
            locations=[
                TemplateLocation(
                    key="tavern",
                    region_key="town",
                    type="interior",
                    archetype="A dimly lit tavern",
                    is_starting_location=True,
                ),
                TemplateLocation(
                    key="market",
                    region_key="town",
                    type="exterior",
                    archetype="A bustling market",
                ),
            ],
            connections=[
                TemplateConnection(
                    from_key="tavern",
                    to_key="market",
                    direction="e",
                    bidirectional=True,
                ),
            ],
            npcs=[
                TemplateNPC(
                    key="barkeep",
                    location_key="tavern",
                    role="merchant",
                    archetype="A gruff barkeep",
                ),
            ],
        ),
    )


# ── Protocol conformance ────────────────────────────────────────


class TestNeo4jServiceProtocol:
    """Verify Neo4jWorldService satisfies the protocol."""

    def test_satisfies_protocol(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        assert isinstance(svc, WorldService)


# ── get_location_context ─────────────────────────────────────────


class TestGetLocationContext:
    """Tests for get_location_context."""

    async def test_returns_location_with_adjacents(
        self,
    ) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        adj_node = _loc_node(id="loc-2", name="Market")
        record = {
            "loc": _loc_node(),
            "exits": [adj_node],
            "npcs": [_npc_node()],
            "items": [_item_node()],
        }
        _setup_session_run(driver, record)

        # Act
        ctx = await svc.get_location_context(uuid4(), "loc-1")

        # Assert
        assert isinstance(ctx, LocationContext)
        assert ctx.location.id == "loc-1"
        assert len(ctx.adjacent_locations) == 1
        assert ctx.adjacent_locations[0].id == "loc-2"
        assert len(ctx.npcs_present) == 1
        assert len(ctx.items_here) == 1

    async def test_raises_on_missing_location(
        self,
    ) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _setup_session_run(driver, None)

        # Act / Assert
        with pytest.raises(ValueError, match="not found"):
            await svc.get_location_context(uuid4(), "nonexistent")

    async def test_empty_adjacents(self) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        record = {
            "loc": _loc_node(),
            "exits": [],
            "npcs": [],
            "items": [],
        }
        _setup_session_run(driver, record)

        # Act
        ctx = await svc.get_location_context(uuid4(), "loc-1")

        # Assert
        assert ctx.adjacent_locations == []
        assert ctx.npcs_present == []
        assert ctx.items_here == []


# ── get_recent_events ────────────────────────────────────────────


class TestGetRecentEvents:
    """get_recent_events returns empty (Postgres stub)."""

    async def test_returns_empty_list(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        events = await svc.get_recent_events(uuid4())
        assert events == []


# ── get_player_location ──────────────────────────────────────────


class TestGetPlayerLocation:
    """Tests for get_player_location."""

    async def test_returns_location(self) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        record = {"loc": _loc_node()}
        _setup_session_run(driver, record)

        # Act
        loc = await svc.get_player_location(uuid4())

        # Assert
        assert isinstance(loc, Location)
        assert loc.id == "loc-1"

    async def test_raises_when_no_session(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _setup_session_run(driver, None)

        with pytest.raises(ValueError, match="No player location"):
            await svc.get_player_location(uuid4())


# ── apply_world_changes ─────────────────────────────────────────


class TestApplyWorldChanges:
    """Tests for apply_world_changes."""

    async def test_player_moved(self) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.PLAYER_MOVED,
            entity_id="loc-2",
            payload={"to_id": "loc-2"},
        )

        # Act
        await svc.apply_world_changes(uuid4(), [change])

        # Assert
        mock_tx.run.assert_called()
        mock_tx.commit.assert_awaited_once()

    async def test_item_taken(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.ITEM_TAKEN,
            entity_id="item-1",
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_item_dropped(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.ITEM_DROPPED,
            entity_id="item-1",
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_npc_moved(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.NPC_MOVED,
            entity_id="npc-1",
            payload={"to_location_id": "loc-2"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_npc_disposition_changed(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.NPC_DISPOSITION_CHANGED,
            entity_id="npc-1",
            payload={"disposition": "hostile"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_location_state_changed(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.LOCATION_STATE_CHANGED,
            entity_id="loc-1",
            payload={"light_level": "dark"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_connection_locked(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.CONNECTION_LOCKED,
            entity_id="loc-1",
            payload={"to_id": "loc-2"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_connection_unlocked(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.CONNECTION_UNLOCKED,
            entity_id="loc-1",
            payload={"to_id": "loc-2"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_quest_status_changed(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.QUEST_STATUS_CHANGED,
            entity_id="quest-1",
            payload={"status": "completed"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_item_visibility_changed(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.ITEM_VISIBILITY_CHANGED,
            entity_id="item-1",
            payload={"hidden": True},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_npc_state_changed(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        change = WorldChange(
            type=WorldChangeType.NPC_STATE_CHANGED,
            entity_id="npc-1",
            payload={"state": "sleeping"},
        )
        await svc.apply_world_changes(uuid4(), [change])
        mock_tx.run.assert_called()

    async def test_empty_changes(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        await svc.apply_world_changes(uuid4(), [])
        mock_tx.commit.assert_awaited_once()

    async def test_multiple_changes(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)

        changes = [
            WorldChange(
                type=WorldChangeType.PLAYER_MOVED,
                entity_id="loc-2",
                payload={"to_id": "loc-2"},
            ),
            WorldChange(
                type=WorldChangeType.ITEM_TAKEN,
                entity_id="item-1",
            ),
        ]
        await svc.apply_world_changes(uuid4(), changes)
        assert mock_tx.run.call_count == 2


# ── create_world_graph ───────────────────────────────────────────


class TestCreateWorldGraph:
    """Tests for create_world_graph."""

    async def test_creates_nodes(self) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _, mock_tx = _setup_tx_session(driver)
        seed = _make_seed()

        # Act
        await svc.create_world_graph(uuid4(), seed)

        # Assert — at least 1 call per entity class
        assert mock_tx.run.call_count >= 5
        mock_tx.commit.assert_awaited_once()


# ── cleanup_session ──────────────────────────────────────────────


class TestCleanupSession:
    """Tests for cleanup_session."""

    async def test_cleanup_runs_detach_delete(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)

        mock_session = MagicMock()
        mock_session.run = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        driver.session.return_value = mock_session

        await svc.cleanup_session(uuid4())
        mock_session.run.assert_awaited_once()


# ── validate_movement ────────────────────────────────────────────


class TestValidateMovement:
    """Tests for validate_movement."""

    async def test_valid_unlocked_connection(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _setup_session_run(driver, {"locked": False})

        ok = await svc.validate_movement(uuid4(), "loc-1", "loc-2")
        assert ok is True

    async def test_locked_connection(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _setup_session_run(driver, {"locked": True})

        ok = await svc.validate_movement(uuid4(), "loc-1", "loc-2")
        assert ok is False

    async def test_no_connection(self) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _setup_session_run(driver, None)

        ok = await svc.validate_movement(uuid4(), "loc-1", "loc-99")
        assert ok is False


# ── get_world_state ──────────────────────────────────────────────


class TestGetWorldState:
    """Tests for get_world_state."""

    async def test_returns_world_context(
        self,
    ) -> None:
        # Arrange
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        record = {
            "cur": _loc_node(),
            "nearby": [_loc_node(id="loc-2", name="Market")],
            "npcs": [_npc_node()],
            "items": [_item_node()],
        }
        _setup_session_run(driver, record)

        # Act
        ctx = await svc.get_world_state(uuid4())

        # Assert
        assert isinstance(ctx, WorldContext)
        assert ctx.current_location.id == "loc-1"
        assert len(ctx.nearby_locations) == 1
        assert len(ctx.npcs_present) == 1
        assert len(ctx.items_here) == 1

    async def test_raises_on_no_session(
        self,
    ) -> None:
        driver = _make_driver()
        svc = Neo4jWorldService(driver)
        _setup_session_run(driver, None)

        with pytest.raises(ValueError, match="No world state"):
            await svc.get_world_state(uuid4())


# ------------------------------------------------------------------
# Neo4jWorldService.reconstruct_world_graph
# ------------------------------------------------------------------


class TestReconstructWorldGraph:
    """AC-12.06: Replay world_events in turn-number order."""

    def _make_driver(self) -> MagicMock:
        driver = MagicMock()
        tx = AsyncMock()
        tx.run = AsyncMock()
        transaction_cm = AsyncMock()
        transaction_cm.__aenter__ = AsyncMock(return_value=tx)
        transaction_cm.__aexit__ = AsyncMock(return_value=False)
        neo4j_sess = AsyncMock()
        neo4j_sess.begin_transaction = AsyncMock(return_value=transaction_cm)
        sess_cm = AsyncMock()
        sess_cm.__aenter__ = AsyncMock(return_value=neo4j_sess)
        sess_cm.__aexit__ = AsyncMock(return_value=False)
        driver.session = MagicMock(return_value=sess_cm)
        return driver

    @pytest.mark.anyio
    async def test_sql_query_joins_turns_ordered_by_turn_number(
        self,
    ) -> None:
        """SQL must JOIN turns and ORDER BY turn_number, not created_at alone."""
        from unittest.mock import call
        from uuid import uuid4 as uuid

        import sqlalchemy as sa

        driver = self._make_driver()
        svc = Neo4jWorldService(driver)

        session_id = uuid()

        # Build a fake pg row with a MOVE_PLAYER event
        row = MagicMock()
        row.event_type = WorldChangeType.PLAYER_MOVED.value
        row.entity_id = "player-1"
        row.payload = {"location_id": "loc-2"}

        db_mock = AsyncMock()
        result_mock = AsyncMock()
        result_mock.fetchall = MagicMock(return_value=[row])
        db_mock.execute = AsyncMock(return_value=result_mock)

        session_factory_cm = AsyncMock()
        session_factory_cm.__aenter__ = AsyncMock(return_value=db_mock)
        session_factory_cm.__aexit__ = AsyncMock(return_value=False)

        session_factory = MagicMock(return_value=session_factory_cm)

        await svc.reconstruct_world_graph(session_id, session_factory)

        # Verify the SQL text contains the JOIN and ORDER BY turn_number
        call_args = db_mock.execute.call_args
        assert call_args is not None
        sql_text: sa.TextClause = call_args[0][0]
        sql_str = sql_text.text.lower()
        assert "join turns" in sql_str, "Query must JOIN the turns table"
        assert "t.turn_number" in sql_str.lower(), (
            "ORDER BY must use turns.turn_number"
        )
        assert "order by" in sql_str

    @pytest.mark.anyio
    async def test_no_events_returns_without_error(
        self,
    ) -> None:
        """Empty world_events → return early without raising."""
        from uuid import uuid4 as uuid

        driver = self._make_driver()
        svc = Neo4jWorldService(driver)
        session_id = uuid()

        db_mock = AsyncMock()
        result_mock = AsyncMock()
        result_mock.fetchall = MagicMock(return_value=[])
        db_mock.execute = AsyncMock(return_value=result_mock)

        session_factory_cm = AsyncMock()
        session_factory_cm.__aenter__ = AsyncMock(return_value=db_mock)
        session_factory_cm.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=session_factory_cm)

        # Should not raise
        await svc.reconstruct_world_graph(session_id, session_factory)

        # Neo4j session should never have been opened
        driver.session.assert_not_called()
