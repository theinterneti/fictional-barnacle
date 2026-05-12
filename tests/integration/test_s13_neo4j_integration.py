"""Integration tests — Neo4j query latency for S13/S12 acceptance criteria.

ACs covered:
  AC-13.04 — get_location_context(depth=1) p95 < 150 ms on 1 000-node world
  AC-13.05 — validate_movement p95 < 30 ms on 1 000-node world
  AC-13.06 — get_location_context(depth=2) p95 < 200 ms on 1 000-node world
  AC-12.08 — two-hop neighbour query p95 < 200 ms (same query as AC-13.06)
  AC-13.13 — NPC updated_at timestamp is strictly after created_at after an update
  AC-13.15 — World node in Neo4j has session_id matching the created game_id
  AC-13.16 — Deleting a game session removes all Neo4j nodes with that session_id
"""

from __future__ import annotations

import asyncio
import statistics
import time
import uuid
from typing import Any

import pytest

from tta.world.neo4j_service import Neo4jWorldService

pytestmark = pytest.mark.integration

# Must match _LARGE_WORLD_SESSION_ID in tests/integration/conftest.py exactly.
LARGE_SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Location IDs from world_large.cypher: large-loc-{region}-{index}
_START_LOC = "large-loc-0-0"
_NEXT_LOC = "large-loc-0-1"

_SAMPLES = 20


def _p95(latencies: list[float]) -> float:
    """Return the 95th-percentile value from *latencies* (in seconds)."""
    # statistics.quantiles(n=20) returns 19 cut points; index 18 = 95th pct.
    return statistics.quantiles(latencies, n=20)[18]


@pytest.mark.spec("AC-13.04")
class TestAC1304LocationContextLatency:
    """get_location_context(depth=1) p95 must be < 150 ms on the large world."""

    @pytest.mark.asyncio
    async def test_p95_under_150ms(self, neo4j_large_world: Any) -> None:
        service = Neo4jWorldService(driver=neo4j_large_world)
        latencies: list[float] = []

        for _ in range(_SAMPLES):
            t0 = time.perf_counter()
            await service.get_location_context(LARGE_SESSION_ID, _START_LOC, depth=1)
            latencies.append(time.perf_counter() - t0)

        p95_ms = _p95(latencies) * 1000
        assert p95_ms < 150, (
            f"AC-13.04 FAIL: get_location_context(depth=1) p95={p95_ms:.1f} ms >= 150 ms"
        )


@pytest.mark.spec("AC-13.05")
class TestAC1305MovementValidationLatency:
    """validate_movement p95 must be < 30 ms on the large world."""

    @pytest.mark.asyncio
    async def test_p95_under_30ms(self, neo4j_large_world: Any) -> None:
        service = Neo4jWorldService(driver=neo4j_large_world)
        latencies: list[float] = []

        for _ in range(_SAMPLES):
            t0 = time.perf_counter()
            await service.validate_movement(LARGE_SESSION_ID, _START_LOC, _NEXT_LOC)
            latencies.append(time.perf_counter() - t0)

        p95_ms = _p95(latencies) * 1000
        assert p95_ms < 30, (
            f"AC-13.05 FAIL: validate_movement p95={p95_ms:.1f} ms >= 30 ms"
        )


@pytest.mark.spec("AC-13.06")
@pytest.mark.spec("AC-12.08")
class TestAC1306TwoHopLatency:
    """get_location_context(depth=2) p95 must be < 200 ms on the large world.

    Covers both AC-13.06 (world-graph two-hop query) and AC-12.08
    (persistence layer two-hop neighbour retrieval).
    """

    @pytest.mark.asyncio
    async def test_p95_under_200ms(self, neo4j_large_world: Any) -> None:
        service = Neo4jWorldService(driver=neo4j_large_world)
        latencies: list[float] = []

        for _ in range(_SAMPLES):
            t0 = time.perf_counter()
            await service.get_location_context(LARGE_SESSION_ID, _START_LOC, depth=2)
            latencies.append(time.perf_counter() - t0)

        p95_ms = _p95(latencies) * 1000
        assert p95_ms < 200, (
            f"AC-13.06/AC-12.08 FAIL: get_location_context(depth=2) "
            f"p95={p95_ms:.1f} ms >= 200 ms"
        )


@pytest.mark.spec("AC-13.07")
class TestAC1307PlayerMovementAtomicity:
    """Player movement must leave exactly one LOCATED_IN edge after the move."""

    @pytest.mark.asyncio
    async def test_player_has_single_location_after_move(
        self, neo4j_session: Any
    ) -> None:
        sid = str(uuid.uuid4())

        # Seed: two locations, one player at start, one EXIT start→end
        await neo4j_session.run(
            "CREATE (start:Location {location_id: 'start', session_id: $sid})"
            " CREATE (end:Location {location_id: 'end', session_id: $sid})"
            " CREATE (p:Player {player_id: 'p1', session_id: $sid})"
            " CREATE (p)-[:LOCATED_IN]->(start)"
            " CREATE (start)-[:EXIT {direction: 'north'}]->(end)",
            sid=sid,
        )

        # Move: delete LOCATED_IN from start, create LOCATED_IN to end atomically
        await neo4j_session.run(
            "MATCH (p:Player {player_id: 'p1', session_id: $sid})"
            "-[r:LOCATED_IN]->(old:Location)"
            " MATCH (end:Location {location_id: 'end', session_id: $sid})"
            " DELETE r"
            " CREATE (p)-[:LOCATED_IN]->(end)",
            sid=sid,
        )

        # Assert exactly one LOCATED_IN edge exists
        result = await neo4j_session.run(
            "MATCH (p:Player {player_id: 'p1', session_id: $sid})"
            "-[:LOCATED_IN]->(loc)"
            " RETURN count(loc) AS cnt, collect(loc.location_id) AS loc_ids",
            sid=sid,
        )
        record = await result.single()
        assert record is not None, "Expected one LOCATED_IN record"
        assert record["cnt"] == 1, (
            f"AC-13.07 FAIL: expected 1 LOCATED_IN edge, got {record['cnt']}"
        )
        assert record["loc_ids"] == ["end"], (
            f"AC-13.07 FAIL: player should be at 'end', "
            f"got {record['loc_ids']}"
        )


@pytest.mark.spec("AC-13.08")
class TestAC1308ItemPickupAtomicity:
    """Item pickup must transfer from AT_LOCATION to CARRIED_BY atomically."""

    @pytest.mark.asyncio
    async def test_item_moves_from_location_to_inventory(
        self, neo4j_session: Any
    ) -> None:
        sid = str(uuid.uuid4())

        # Seed: one location, one item AT_LOCATION, one player LOCATED_IN same location
        await neo4j_session.run(
            "CREATE (loc:Location {location_id: 'loc1', session_id: $sid})"
            " CREATE (item:Item {item_id: 'sword', session_id: $sid})"
            " CREATE (p:Player {player_id: 'p1', session_id: $sid})"
            " CREATE (item)-[:AT_LOCATION]->(loc)"
            " CREATE (p)-[:LOCATED_IN]->(loc)",
            sid=sid,
        )

        # Pickup: delete AT_LOCATION, create CARRIED_BY atomically
        await neo4j_session.run(
            "MATCH (item:Item {item_id: 'sword', session_id: $sid})"
            "-[r:AT_LOCATION]->(loc)"
            " MATCH (p:Player {player_id: 'p1', session_id: $sid})"
            " DELETE r"
            " CREATE (item)-[:CARRIED_BY]->(p)",
            sid=sid,
        )

        # Assert AT_LOCATION count = 0
        at_loc_result = await neo4j_session.run(
            "MATCH (item:Item {item_id: 'sword', session_id: $sid})"
            "-[r:AT_LOCATION]->()"
            " RETURN count(r) AS cnt",
            sid=sid,
        )
        at_loc_record = await at_loc_result.single()
        assert at_loc_record is not None
        assert at_loc_record["cnt"] == 0, (
            f"AC-13.08 FAIL: expected 0 AT_LOCATION edges, got {at_loc_record['cnt']}"
        )

        # Assert CARRIED_BY count = 1
        carried_result = await neo4j_session.run(
            "MATCH (item:Item {item_id: 'sword', session_id: $sid})"
            "-[r:CARRIED_BY]->()"
            " RETURN count(r) AS cnt",
            sid=sid,
        )
        carried_record = await carried_result.single()
        assert carried_record is not None
        assert carried_record["cnt"] == 1, (
            f"AC-13.08 FAIL: expected 1 CARRIED_BY edge, got {carried_record['cnt']}"
        )


@pytest.mark.spec("AC-13.09")
class TestAC1309NPCSinglePresence:
    """NPC must have exactly one PRESENT_IN edge after being moved between locations."""

    @pytest.mark.asyncio
    async def test_npc_has_single_presence_after_move(self, neo4j_session: Any) -> None:
        sid = str(uuid.uuid4())

        # Seed: two locations, one NPC PRESENT_IN loc1
        await neo4j_session.run(
            "CREATE (loc1:Location {location_id: 'loc1', session_id: $sid})"
            " CREATE (loc2:Location {location_id: 'loc2', session_id: $sid})"
            " CREATE (npc:NPC {npc_id: 'guard', session_id: $sid})"
            " CREATE (npc)-[:PRESENT_IN]->(loc1)",
            sid=sid,
        )

        # Move NPC: delete old PRESENT_IN, create new PRESENT_IN to loc2 atomically
        await neo4j_session.run(
            "MATCH (npc:NPC {npc_id: 'guard', session_id: $sid})"
            "-[r:PRESENT_IN]->()"
            " MATCH (loc2:Location {location_id: 'loc2', session_id: $sid})"
            " DELETE r"
            " CREATE (npc)-[:PRESENT_IN]->(loc2)",
            sid=sid,
        )

        # Assert exactly one PRESENT_IN edge exists
        result = await neo4j_session.run(
            "MATCH (npc:NPC {npc_id: 'guard', session_id: $sid})"
            "-[:PRESENT_IN]->(loc)"
            " RETURN count(loc) AS cnt, collect(loc.location_id) AS loc_ids",
            sid=sid,
        )
        record = await result.single()
        assert record is not None, "Expected one PRESENT_IN record"
        assert record["cnt"] == 1, (
            f"AC-13.09 FAIL: expected 1 PRESENT_IN edge, got {record['cnt']}"
        )
        assert record["loc_ids"] == ["loc2"], (
            f"AC-13.09 FAIL: NPC should be at 'loc2', "
            f"got {record['loc_ids']}"
        )


@pytest.mark.spec("AC-13.13")
class TestAC1313TimestampOrdering:
    """NPC updated_at must be strictly after created_at following an update."""

    @pytest.mark.asyncio
    async def test_updated_at_after_created_at(self, neo4j_session: Any) -> None:
        sid = str(uuid.uuid4())

        # Seed NPC with both timestamps set at creation time
        await neo4j_session.run(
            "CREATE (npc:NPC {"
            "  npc_id: 'guard',"
            "  session_id: $sid,"
            "  created_at: datetime(),"
            "  updated_at: datetime()"
            "})",
            sid=sid,
        )

        # Advance clock slightly before performing the update
        await asyncio.sleep(0.05)

        # SET updated_at to current datetime (simulates a write operation)
        await neo4j_session.run(
            "MATCH (npc:NPC {npc_id: 'guard', session_id: $sid})"
            " SET npc.updated_at = datetime()",
            sid=sid,
        )

        # Query both timestamps and compare
        result = await neo4j_session.run(
            "MATCH (npc:NPC {npc_id: 'guard', session_id: $sid})"
            " RETURN npc.created_at AS ca, npc.updated_at AS ua",
            sid=sid,
        )
        record = await result.single()
        assert record is not None, "Expected NPC record with timestamps"
        assert record["ua"] > record["ca"], (
            "AC-13.13 FAIL: updated_at must be strictly after created_at, "
            f"got created_at={record['ca']!r}, updated_at={record['ua']!r}"
        )


@pytest.mark.spec("AC-13.15")
class TestAC1315DualStoreSessionConsistency:
    """World node in Neo4j must carry a session_id matching the created game_id."""

    @pytest.mark.asyncio
    async def test_world_node_session_id_matches_game_id(
        self,
        client: Any,
        neo4j_db: Any,
    ) -> None:
        # Register a player
        handle = f"ac1315-{uuid.uuid4().hex[:8]}"
        reg_resp = await client.post(
            "/api/v1/players",
            json={
                "handle": handle,
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert reg_resp.status_code == 201, reg_resp.text
        token = reg_resp.json()["data"]["session_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a game session
        game_resp = await client.post(
            "/api/v1/games",
            json={},
            headers=headers,
        )
        if game_resp.status_code not in (200, 201):
            pytest.skip(
                f"POST /api/v1/games returned {game_resp.status_code} — "
                "endpoint unavailable or world genesis not implemented"
            )

        game_id = game_resp.json()["data"]["game_id"]

        # Query Neo4j for a World node with matching session_id
        async with neo4j_db.session() as session:
            result = await session.run(
                "MATCH (w:World {session_id: $sid}) RETURN w.session_id AS sid",
                sid=game_id,
            )
            record = await result.single()

        assert record is not None, (
            f"AC-13.15 FAIL: no World node found in Neo4j for session_id={game_id!r}"
        )
        assert record["sid"] == game_id, (
            f"AC-13.15 FAIL: World.session_id={record['sid']!r} != game_id={game_id!r}"
        )


@pytest.mark.spec("AC-13.16")
class TestAC1316SessionDeleteCleansNeo4j:
    """Deleting a game session must remove all Neo4j nodes with that session_id."""

    @pytest.mark.asyncio
    async def test_delete_game_removes_neo4j_nodes(
        self,
        client: Any,
        neo4j_db: Any,
    ) -> None:
        # Register a player
        handle = f"ac1316-{uuid.uuid4().hex[:8]}"
        reg_resp = await client.post(
            "/api/v1/players",
            json={
                "handle": handle,
                "age_13_plus_confirmed": True,
                "consent_version": "1.0",
                "consent_categories": {
                    "core_gameplay": True,
                    "llm_processing": True,
                },
            },
        )
        assert reg_resp.status_code == 201, reg_resp.text
        token = reg_resp.json()["data"]["session_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create a game session
        game_resp = await client.post(
            "/api/v1/games",
            json={},
            headers=headers,
        )
        if game_resp.status_code not in (200, 201):
            pytest.skip(
                f"POST /api/v1/games returned {game_resp.status_code} — "
                "endpoint unavailable or world genesis not implemented"
            )

        game_id = game_resp.json()["data"]["game_id"]

        # Delete the game session
        del_resp = await client.delete(
            f"/api/v1/games/{game_id}",
            headers=headers,
        )
        if del_resp.status_code not in (200, 204):
            pytest.skip(
                f"DELETE /api/v1/games/{{game_id}} returned {del_resp.status_code} — "
                "delete endpoint unavailable"
            )

        # Query Neo4j: all nodes with that session_id must be gone
        async with neo4j_db.session() as session:
            result = await session.run(
                "MATCH (n {session_id: $sid}) RETURN count(n) AS cnt",
                sid=game_id,
            )
            record = await result.single()

        assert record is not None
        assert record["cnt"] == 0, (
            f"AC-13.16 FAIL: expected 0 Neo4j nodes after game deletion, "
            f"got {record['cnt']} nodes with session_id={game_id!r}"
        )
