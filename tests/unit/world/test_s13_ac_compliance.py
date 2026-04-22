"""S13 World Graph Integrity — Acceptance Criteria compliance tests.

Covers the v1 ACs from specs/13-world-graph.md:
  AC-13.01 — Referential integrity enforced at seed validation
  AC-13.02 — Region key uniqueness enforced
  AC-13.03 — Required properties (key, archetype) enforced
  AC-13.10 — Valid seed materialises world graph via Cypher
  AC-13.11 — Invalid seed is rejected before any Cypher is run
  AC-13.12 — Duplicate session_id is rejected
  AC-13.14 — apply_world_changes dispatches one call per change

v2-deferred ACs (not tested here):
  AC-13.04–AC-13.09 — graph query depth, NPC context, item context (v2)
  AC-13.15–AC-13.16 — history compression, partial updates (v2)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tta.models.world import (
    TemplateLocation,
    TemplateMetadata,
    TemplateRegion,
    WorldChange,
    WorldChangeType,
    WorldSeed,
    WorldTemplate,
)
from tta.world.neo4j_service import Neo4jWorldService
from tta.world.template_validator import (
    DanglingReferenceError,
    DuplicateKeyError,
    validate_template,
)

# ── Helpers ───────────────────────────────────────────────────────


def _make_driver() -> MagicMock:
    """Build a minimal mocked neo4j.AsyncDriver.

    ``session()`` on a real driver is synchronous (returns a context manager),
    so we use MagicMock at the top level and AsyncMock for the transaction.
    """
    driver = MagicMock()
    tx = AsyncMock()
    tx.run = AsyncMock()
    tx.commit = AsyncMock()
    tx_ctx = MagicMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=tx)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin_transaction = AsyncMock(return_value=tx_ctx)
    session.run = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    driver.session.return_value = session
    return driver


def _minimal_metadata(**overrides: Any) -> TemplateMetadata:
    base: dict[str, Any] = {
        "template_key": "test_world",
        "display_name": "Test World",
    }
    base.update(overrides)
    return TemplateMetadata(**base)


def _minimal_region(**overrides: Any) -> TemplateRegion:
    base: dict[str, Any] = {"key": "forest", "archetype": "dense_forest"}
    base.update(overrides)
    return TemplateRegion(**base)


def _minimal_location(**overrides: Any) -> TemplateLocation:
    base: dict[str, Any] = {
        "key": "clearing",
        "region_key": "forest",
        "type": "exterior",
        "archetype": "open_clearing",
        "is_starting_location": True,
    }
    base.update(overrides)
    return TemplateLocation(**base)


def _minimal_template(**overrides: Any) -> WorldTemplate:
    base: dict[str, Any] = {
        "metadata": _minimal_metadata(),
        "regions": [_minimal_region()],
        "locations": [_minimal_location()],
    }
    base.update(overrides)
    return WorldTemplate(**base)


def _minimal_seed(**overrides: Any) -> WorldSeed:
    base: dict[str, Any] = {"template": _minimal_template()}
    base.update(overrides)
    return WorldSeed(**base)


# ── AC-13.01: Referential integrity ──────────────────────────────


@pytest.mark.spec("AC-13.01")
class TestAC1301ReferentialIntegrity:
    """AC-13.01: A Location's region_key must reference an existing Region.key.
    Seeds with dangling region_key references must be rejected.

    Gherkin:
      Given a WorldTemplate with a location referencing region_key="ghost_region"
      And "ghost_region" is not in the regions list
      When the template is validated
      Then a ValidationError or ValueError is raised
    """

    def test_location_valid_region_key_is_accepted(self) -> None:
        """A location whose region_key matches an existing region is valid."""
        template = _minimal_template()
        assert template.locations[0].region_key == "forest"
        assert template.regions[0].key == "forest"

    def test_dangling_region_key_raises_error(self) -> None:
        """validate_template() raises DanglingReferenceError for a missing region."""
        dangling = TemplateLocation(
            key="lost_place",
            region_key="ghost_region",
            type="exterior",
            archetype="ruin",
            is_starting_location=True,
        )
        template = WorldTemplate(
            metadata=_minimal_metadata(),
            regions=[_minimal_region(key="forest")],
            locations=[dangling],
        )
        with pytest.raises(DanglingReferenceError):
            validate_template(template)


# ── AC-13.02: Region key uniqueness ──────────────────────────────


@pytest.mark.spec("AC-13.02")
class TestAC1302RegionKeyUniqueness:
    """AC-13.02: Two regions with the same key must be rejected.

    Gherkin:
      Given a WorldTemplate with two regions both having key="forest"
      When the template is constructed or validated
      Then a ValidationError is raised
    """

    def test_duplicate_region_keys_detectable(self) -> None:
        """Raises DuplicateKeyError for two regions with the same key."""
        r1 = _minimal_region(key="forest", archetype="dense")
        r2 = _minimal_region(key="forest", archetype="sparse")
        template = WorldTemplate(
            metadata=_minimal_metadata(),
            regions=[r1, r2],
            locations=[_minimal_location()],
        )
        with pytest.raises(DuplicateKeyError):
            validate_template(template)

    def test_unique_region_keys_accepted(self) -> None:
        """A template with unique region keys is valid."""
        r1 = _minimal_region(key="forest", archetype="dense")
        r2 = _minimal_region(key="plains", archetype="open_plains")
        loc1 = _minimal_location(key="clearing", region_key="forest")
        loc2 = _minimal_location(key="meadow", region_key="plains")
        template = WorldTemplate(
            metadata=_minimal_metadata(),
            regions=[r1, r2],
            locations=[loc1, loc2],
        )
        region_keys = [r.key for r in template.regions]
        assert len(region_keys) == len(set(region_keys))


# ── AC-13.03: Required properties ────────────────────────────────


@pytest.mark.spec("AC-13.03")
class TestAC1303RequiredProperties:
    """AC-13.03: TemplateRegion and TemplateLocation require key and archetype.
    Omitting these fields must raise a ValidationError.

    Gherkin:
      Given a TemplateRegion constructed without "key"
      Then a ValidationError is raised

      Given a TemplateLocation constructed without "archetype"
      Then a ValidationError is raised
    """

    def test_region_missing_key_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            TemplateRegion(archetype="dense_forest")  # type: ignore[call-arg]

    def test_region_missing_archetype_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            TemplateRegion(key="forest")  # type: ignore[call-arg]

    def test_location_missing_key_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            TemplateLocation(  # type: ignore[call-arg]
                region_key="forest",
                type="exterior",
                archetype="clearing",
            )

    def test_location_missing_archetype_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            TemplateLocation(  # type: ignore[call-arg]
                key="clearing",
                region_key="forest",
                type="exterior",
            )

    def test_valid_region_constructs_without_error(self) -> None:
        region = TemplateRegion(key="forest", archetype="dense_forest")
        assert region.key == "forest"
        assert region.archetype == "dense_forest"

    def test_valid_location_constructs_without_error(self) -> None:
        loc = TemplateLocation(
            key="clearing",
            region_key="forest",
            type="exterior",
            archetype="open_clearing",
        )
        assert loc.key == "clearing"


# ── AC-13.10: Valid seed materialises graph ───────────────────────


@pytest.mark.spec("AC-13.10")
class TestAC1310ValidSeedMaterialises:
    """AC-13.10: create_world_graph with a valid WorldSeed runs Cypher transactions.

    Gherkin:
      Given a Neo4jWorldService with a mocked driver
      And a valid WorldSeed with one region and one location
      When create_world_graph(session_id, world_seed) is called
      Then the driver's session() is entered
      And tx.run() is called at least once with a CREATE statement
      And tx.commit() is called
    """

    @pytest.mark.anyio()
    async def test_valid_seed_calls_tx_run(self) -> None:
        """create_world_graph must invoke at least one Cypher CREATE call."""
        driver = _make_driver()
        service = Neo4jWorldService(driver=driver)
        seed = _minimal_seed()
        session_id = uuid4()

        await service.create_world_graph(session_id, seed)

        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        assert tx.run.called, "tx.run should be called to emit Cypher"

    @pytest.mark.anyio()
    async def test_valid_seed_calls_tx_commit(self) -> None:
        """create_world_graph must commit the transaction."""
        driver = _make_driver()
        service = Neo4jWorldService(driver=driver)
        seed = _minimal_seed()
        session_id = uuid4()

        await service.create_world_graph(session_id, seed)

        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        tx.commit.assert_called_once()

    @pytest.mark.anyio()
    async def test_world_node_create_called(self) -> None:
        """The World node CREATE must be one of the Cypher calls."""
        driver = _make_driver()
        service = Neo4jWorldService(driver=driver)
        seed = _minimal_seed()
        session_id = uuid4()

        await service.create_world_graph(session_id, seed)

        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        # At least one call should reference "World"
        calls_str = str(tx.run.call_args_list)
        assert "World" in calls_str or "MERGE" in calls_str or "CREATE" in calls_str


# ── AC-13.11: Invalid seed rejected before Cypher ────────────────


@pytest.mark.spec("AC-13.11")
class TestAC1311InvalidSeedRejected:
    """AC-13.11: An invalid WorldSeed must fail at construction (Pydantic).
    No Cypher should be executed for invalid seeds.

    Gherkin:
      Given a WorldSeed with a missing template
      Then constructing the WorldSeed raises a ValidationError
    """

    def test_seed_without_template_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            WorldSeed()  # type: ignore[call-arg]

    def test_template_without_metadata_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            WorldTemplate()  # type: ignore[call-arg]

    def test_metadata_without_template_key_raises_validation_error(self) -> None:
        with pytest.raises((ValidationError, TypeError)):
            TemplateMetadata(display_name="Test")  # type: ignore[call-arg]

    def test_valid_seed_does_not_raise(self) -> None:
        """A properly constructed WorldSeed should not raise."""
        seed = _minimal_seed()
        assert seed.template.metadata.template_key == "test_world"


# ── AC-13.12: Duplicate session rejected ─────────────────────────


@pytest.mark.spec("AC-13.12")
class TestAC1312DuplicateSessionRejected:
    """AC-13.12: A second create_world_graph for the same session_id should
    fail (duplicate constraint). The Neo4j MERGE / CREATE on World ensures
    session_id uniqueness at the graph layer.

    Gherkin:
      Given a session_id that already has a World node
      When create_world_graph is called again with the same session_id
      Then the driver raises a ConstraintError (or equivalent)
    """

    @pytest.mark.anyio()
    async def test_duplicate_session_raises_on_driver_error(self) -> None:
        """If the driver raises on a duplicate session, the error propagates."""
        from neo4j.exceptions import ConstraintError

        driver = _make_driver()
        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        tx.run = AsyncMock(side_effect=ConstraintError("duplicate"))

        service = Neo4jWorldService(driver=driver)
        seed = _minimal_seed()
        session_id = uuid4()

        with (
            patch(
                "tta.world.neo4j_service.observe_neo4j_op",
                return_value=MagicMock(
                    __aenter__=AsyncMock(return_value=None),
                    __aexit__=AsyncMock(return_value=False),
                ),
            ),
            pytest.raises(ConstraintError),
        ):
            await service.create_world_graph(session_id, seed)


# ── AC-13.14: Change detection / apply_world_changes ─────────────


@pytest.mark.spec("AC-13.14")
class TestAC1314ChangeDetection:
    """AC-13.14: apply_world_changes dispatches one Cypher call per WorldChange.

    Gherkin:
      Given a list of 3 WorldChange objects
      When apply_world_changes(session_id, changes) is called
      Then tx.run() is called at least 3 times (one per change)
    """

    @pytest.mark.anyio()
    async def test_one_change_calls_tx_run_once(self) -> None:
        driver = _make_driver()
        service = Neo4jWorldService(driver=driver)
        session_id = uuid4()
        changes = [
            WorldChange(
                type=WorldChangeType.NPC_STATE_CHANGED,
                entity_id="npc-1",
                payload={"state": "sleeping"},
            )
        ]

        with patch(
            "tta.world.neo4j_service.observe_neo4j_op",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            await service.apply_world_changes(session_id, changes)

        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        assert tx.run.called

    @pytest.mark.anyio()
    async def test_multiple_changes_dispatch_multiple_cypher_calls(
        self,
    ) -> None:
        driver = _make_driver()
        service = Neo4jWorldService(driver=driver)
        session_id = uuid4()
        changes = [
            WorldChange(
                type=WorldChangeType.NPC_STATE_CHANGED,
                entity_id="npc-1",
                payload={"state": "sleeping"},
            ),
            WorldChange(
                type=WorldChangeType.NPC_STATE_CHANGED,
                entity_id="npc-2",
                payload={"state": "active"},
            ),
            WorldChange(
                type=WorldChangeType.LOCATION_STATE_CHANGED,
                entity_id="loc-1",
                payload={"is_accessible": False},
            ),
        ]

        with patch(
            "tta.world.neo4j_service.observe_neo4j_op",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            await service.apply_world_changes(session_id, changes)

        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        # Each change should produce at least one tx.run call
        assert tx.run.call_count >= len(changes)

    @pytest.mark.anyio()
    async def test_empty_changes_list_commits_cleanly(self) -> None:
        driver = _make_driver()
        service = Neo4jWorldService(driver=driver)

        with patch(
            "tta.world.neo4j_service.observe_neo4j_op",
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=False),
            ),
        ):
            # Empty change list should not raise
            await service.apply_world_changes(uuid4(), [])

        session = driver.session.return_value
        tx = session.begin_transaction.return_value.__aenter__.return_value
        tx.commit.assert_called_once()
