"""Neo4j-backed WorldService implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
import structlog
from neo4j import AsyncDriver

from tta.models.world import (
    Location,
    LocationContext,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldEvent,
    WorldSeed,
)
from tta.observability.db_metrics import observe_neo4j_op
from tta.world.neo4j_helpers import (
    _LOCATION_CONTEXT_QUERIES,
    _REVERSE_DIRECTION,
    _dispatch_change,
    _gen_id,
    _node_to_item,
    _node_to_location,
    _node_to_npc,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = structlog.get_logger(__name__)


class Neo4jWorldService:
    """WorldService backed by a Neo4j graph database.

    Each session owns an isolated subgraph keyed by
    ``session_id`` on every node.
    """

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    # -- Protocol method: get_location_context -----------------

    async def get_location_context(
        self,
        session_id: UUID,
        location_id: str,
        depth: int = 1,
    ) -> LocationContext:
        """Return a location with its exits, NPCs, and items.

        ``depth`` controls how many hops of adjacent locations to
        include (default 1 = immediate neighbors only, max 5).
        """
        sid = str(session_id)
        safe_depth = max(1, min(depth, 5))
        query = _LOCATION_CONTEXT_QUERIES[safe_depth]
        async with observe_neo4j_op("get_location_context"):
            async with self._driver.session() as session:
                result = await session.run(
                    query,
                    location_id=location_id,
                    session_id=sid,
                )
                record = await result.single()

        if record is None:
            msg = f"Location {location_id!r} not found for session {sid}"
            raise ValueError(msg)

        loc_node = record["loc"]
        location = _node_to_location(loc_node)

        adjacent = [_node_to_location(n) for n in record["exits"]]
        npcs = [_node_to_npc(n) for n in record["npcs"]]
        items = [_node_to_item(n) for n in record["items"]]

        return LocationContext(
            location=location,
            adjacent_locations=adjacent,
            npcs_present=npcs,
            items_here=items,
        )

    # -- Protocol method: get_recent_events --------------------

    async def get_recent_events(
        self,
        session_id: UUID,
        limit: int = 5,
    ) -> list[WorldEvent]:
        """Return recent events.

        Events live in Postgres, not Neo4j. Returns an empty
        list until a Postgres repository is wired in.
        """
        return []

    # -- Protocol method: apply_world_changes ------------------

    async def apply_world_changes(
        self,
        session_id: UUID,
        changes: list[WorldChange],
    ) -> None:
        """Apply a batch of world mutations in one transaction."""
        sid = str(session_id)
        log = logger.bind(session_id=sid)

        async with observe_neo4j_op("apply_world_changes"):
            async with self._driver.session() as session:
                async with await session.begin_transaction() as tx:
                    for change in changes:
                        await _dispatch_change(tx, sid, change, log)
                    await tx.commit()

    # -- Protocol method: get_player_location ------------------

    async def get_player_location(
        self,
        session_id: UUID,
    ) -> Location:
        """Return the player's current location."""
        sid = str(session_id)
        query = """
        MATCH (ps:PlayerSession {session_id: $session_id})
              -[:IS_AT]->(loc:Location)
        RETURN loc
        """
        async with self._driver.session() as session:
            result = await session.run(query, session_id=sid)
            record = await result.single()

        if record is None:
            msg = f"No player location for session {sid}"
            raise ValueError(msg)

        return _node_to_location(record["loc"])

    # -- Protocol method: create_world_graph -------------------

    async def create_world_graph(
        self,
        session_id: UUID,
        world_seed: WorldSeed,
    ) -> None:
        """Materialise a WorldSeed template into Neo4j."""
        sid = str(session_id)
        tmpl = world_seed.template
        log = logger.bind(session_id=sid)

        # Build an id_map from template keys → generated IDs.
        id_map: dict[str, str] = {}

        async with self._driver.session() as session:
            async with await session.begin_transaction() as tx:
                # 1. World node
                world_id = _gen_id()
                await tx.run(
                    """
                    CREATE (w:World {
                        id: $id,
                        session_id: $sid,
                        template_key: $tkey
                    })
                    """,
                    id=world_id,
                    sid=sid,
                    tkey=tmpl.metadata.template_key,
                )

                # 2. Regions
                for region in tmpl.regions:
                    rid = _gen_id()
                    id_map[region.key] = rid
                    await tx.run(
                        """
                        MATCH (w:World {
                            id: $wid,
                            session_id: $sid
                        })
                        CREATE (r:Region {
                            id: $id,
                            session_id: $sid,
                            name: $key,
                            description: $archetype,
                            template_key: $key
                        })
                        CREATE (w)-[:CONTAINS]->(r)
                        """,
                        wid=world_id,
                        sid=sid,
                        id=rid,
                        key=region.key,
                        archetype=region.archetype,
                    )

                # 3. Locations
                starting_location_id: str | None = None
                for loc in tmpl.locations:
                    lid = _gen_id()
                    id_map[loc.key] = lid
                    region_id = id_map.get(loc.region_key, "")
                    await tx.run(
                        """
                        CREATE (l:Location {
                            id: $id,
                            session_id: $sid,
                            name: $key,
                            description: $archetype,
                            type: $type,
                            region_id: $region_id,
                            light_level: $light,
                            visited: false,
                            is_accessible: true,
                            template_key: $key
                        })
                        WITH l
                        OPTIONAL MATCH
                            (r:Region {
                                id: $region_id,
                                session_id: $sid
                            })
                        FOREACH (
                            _ IN CASE WHEN r IS NOT NULL
                                      THEN [1] ELSE [] END |
                            CREATE (r)-[:CONTAINS]->(l)
                        )
                        """,
                        id=lid,
                        sid=sid,
                        key=loc.key,
                        archetype=loc.archetype,
                        type=loc.type,
                        region_id=region_id,
                        light=loc.light_level,
                    )
                    if loc.is_starting_location:
                        starting_location_id = lid

                # 4. Connections
                for conn in tmpl.connections:
                    fid = id_map.get(conn.from_key, "")
                    tid = id_map.get(conn.to_key, "")
                    await tx.run(
                        """
                        MATCH (a:Location {
                            id: $fid, session_id: $sid
                        })
                        MATCH (b:Location {
                            id: $tid, session_id: $sid
                        })
                        CREATE (a)-[:CONNECTS_TO {
                            direction: $dir,
                            is_locked: $locked,
                            is_hidden: $hidden
                        }]->(b)
                        """,
                        fid=fid,
                        tid=tid,
                        sid=sid,
                        dir=conn.direction,
                        locked=conn.is_locked,
                        hidden=conn.is_hidden,
                    )
                    if conn.bidirectional:
                        rev = _REVERSE_DIRECTION.get(conn.direction, conn.direction)
                        await tx.run(
                            """
                            MATCH (a:Location {
                                id: $tid,
                                session_id: $sid
                            })
                            MATCH (b:Location {
                                id: $fid,
                                session_id: $sid
                            })
                            CREATE (a)-[:CONNECTS_TO {
                                direction: $dir,
                                is_locked: $locked,
                                is_hidden: $hidden
                            }]->(b)
                            """,
                            fid=fid,
                            tid=tid,
                            sid=sid,
                            dir=rev,
                            locked=conn.is_locked,
                            hidden=conn.is_hidden,
                        )

                # 5. NPCs — with enrichment from flavor_text
                enriched_npcs: dict[str, dict] = {}
                ft = world_seed.flavor_text
                if isinstance(ft, dict) and "npcs" in ft:
                    for entry in ft["npcs"]:
                        if isinstance(entry, dict) and "key" in entry:
                            enriched_npcs[entry["key"]] = entry

                for npc in tmpl.npcs:
                    nid = _gen_id()
                    id_map[npc.key] = nid
                    loc_id = id_map.get(npc.location_key, "")
                    enr = enriched_npcs.get(npc.key, {})
                    await tx.run(
                        """
                        MATCH (l:Location {
                            id: $loc_id,
                            session_id: $sid
                        })
                        CREATE (n:NPC {
                            id: $id,
                            session_id: $sid,
                            name: $name,
                            description: $desc,
                            role: $role,
                            disposition: $disp,
                            alive: true,
                            state: 'idle',
                            template_key: $key,
                            tier: $tier,
                            traits: $traits,
                            interaction_count: 0,
                            personality: $personality,
                            dialogue_style: $dialogue_style,
                            voice: $voice,
                            occupation: $occupation,
                            goals_short: $goals_short,
                            backstory: $backstory_summary
                        })
                        CREATE (n)-[:IS_AT]->(l)
                        """,
                        id=nid,
                        sid=sid,
                        key=npc.key,
                        name=enr.get("name", npc.key),
                        desc=enr.get(
                            "description",
                            npc.archetype,
                        ),
                        role=npc.role,
                        disp=npc.disposition,
                        loc_id=loc_id,
                        tier=npc.tier.value,
                        traits=list(npc.traits),
                        personality=enr.get("personality"),
                        dialogue_style=enr.get("dialogue_style"),
                        voice=enr.get("voice"),
                        occupation=enr.get("occupation"),
                        goals_short=enr.get("goals_short"),
                        backstory_summary=enr.get("backstory_summary"),
                    )

                # 5b. Seed RELATES_TO edges from template
                for rel in tmpl.relationships:
                    src_id = id_map.get(rel.source_npc_key)
                    tgt_id = id_map.get(rel.target_npc_key)
                    if src_id and tgt_id:
                        await tx.run(
                            """
                            MATCH (a:NPC {
                                id: $src,
                                session_id: $sid
                            })
                            MATCH (b:NPC {
                                id: $tgt,
                                session_id: $sid
                            })
                            CREATE (a)-[:RELATES_TO {
                                session_id: $sid,
                                trust: $trust,
                                affinity: $affinity,
                                respect: $respect,
                                fear: $fear,
                                familiarity: $fam,
                                interaction_count: 0
                            }]->(b)
                            """,
                            src=src_id,
                            tgt=tgt_id,
                            sid=sid,
                            trust=rel.trust,
                            affinity=rel.affinity,
                            respect=rel.respect,
                            fear=rel.fear,
                            fam=rel.familiarity,
                        )

                # 6. Items
                for item in tmpl.items:
                    iid = _gen_id()
                    id_map[item.key] = iid
                    if item.location_key:
                        parent_id = id_map.get(item.location_key, "")
                        await tx.run(
                            """
                            MATCH (l:Location {
                                id: $pid,
                                session_id: $sid
                            })
                            CREATE (i:Item {
                                id: $id,
                                session_id: $sid,
                                name: $key,
                                description: $archetype,
                                item_type: $type,
                                portable: $portable,
                                hidden: $hidden,
                                template_key: $key
                            })
                            CREATE (i)-[:IS_AT]->(l)
                            """,
                            id=iid,
                            sid=sid,
                            key=item.key,
                            archetype=item.archetype,
                            type=item.type,
                            portable=item.portable,
                            hidden=item.hidden,
                            pid=parent_id,
                        )
                    elif item.npc_key:
                        parent_id = id_map.get(item.npc_key, "")
                        await tx.run(
                            """
                            MATCH (n:NPC {
                                id: $pid,
                                session_id: $sid
                            })
                            CREATE (i:Item {
                                id: $id,
                                session_id: $sid,
                                name: $key,
                                description: $archetype,
                                item_type: $type,
                                portable: $portable,
                                hidden: $hidden,
                                template_key: $key
                            })
                            CREATE (i)-[:HELD_BY]->(n)
                            """,
                            id=iid,
                            sid=sid,
                            key=item.key,
                            archetype=item.archetype,
                            type=item.type,
                            portable=item.portable,
                            hidden=item.hidden,
                            pid=parent_id,
                        )

                # 7. PlayerSession
                if starting_location_id is None and tmpl.locations:
                    starting_location_id = id_map.get(tmpl.locations[0].key, "")
                if starting_location_id:
                    await tx.run(
                        """
                        MATCH (l:Location {
                            id: $loc_id,
                            session_id: $sid
                        })
                        CREATE (ps:PlayerSession {
                            session_id: $sid,
                            world_id: $wid
                        })
                        CREATE (ps)-[:IS_AT]->(l)
                        """,
                        sid=sid,
                        wid=world_id,
                        loc_id=starting_location_id,
                    )

                await tx.commit()

        log.info(
            "world_graph_created",
            template=tmpl.metadata.template_key,
            locations=len(tmpl.locations),
            npcs=len(tmpl.npcs),
            items=len(tmpl.items),
        )

    # -- Protocol method: cleanup_session ----------------------

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None:
        """Delete every node and relationship for a session."""
        sid = str(session_id)
        query = """
        MATCH (n {session_id: $session_id})
        DETACH DELETE n
        """
        async with self._driver.session() as session:
            await session.run(query, session_id=sid)

        logger.info("session_cleaned_up", session_id=sid)

    # -- AC-12.06: reconstruct_world_graph ----------------------

    async def reconstruct_world_graph(
        self,
        game_session_id: UUID,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Replay world_events from Postgres to rebuild Neo4j graph state.

        Safe to call even if the graph is partially populated — existing
        nodes will be updated in-place by the dispatch handlers.  If no
        events exist the method returns without error (degraded-mode log).
        """
        sid = str(game_session_id)
        log = logger.bind(session_id=sid, operation="reconstruct_world_graph")
        world_seed_dict: dict | None = None

        # Load events and world seed from Postgres ordered by authoritative turn number.
        async with session_factory() as db:
            rows = (
                await db.execute(
                    sa.text(
                        "SELECT we.event_type, we.entity_id, we.payload"
                        " FROM world_events we"
                        " JOIN turns t ON we.turn_id = t.id"
                        " WHERE we.session_id = :sid"
                        " ORDER BY t.turn_number ASC, we.created_at ASC"
                    ),
                    {"sid": game_session_id},
                )
            ).fetchall()
            ws_row = (
                await db.execute(
                    sa.text("SELECT world_seed FROM game_sessions WHERE id = :sid"),
                    {"sid": game_session_id},
                )
            ).one_or_none()
            if ws_row is not None:
                world_seed_dict = ws_row.world_seed

        if not rows:
            log.warning(
                "world_graph_reconstruction_skipped",
                reason="no_events_found",
                note="degraded: Neo4j graph state not available",
            )
            return

        changes: list[WorldChange] = []
        for row in rows:
            raw_payload = row.payload
            if isinstance(raw_payload, str):
                raw_payload = json.loads(raw_payload)
            try:
                changes.append(
                    WorldChange(
                        type=WorldChangeType(row.event_type),
                        entity_id=row.entity_id,
                        payload=raw_payload or {},
                    )
                )
            except ValueError:
                log.warning(
                    "unknown_world_event_type",
                    event_type=row.event_type,
                    entity_id=row.entity_id,
                )

        if not changes:
            return

        async with observe_neo4j_op("reconstruct_world_graph"):
            # Ensure the base World node exists before replaying events.
            async with self._driver.session() as check_sess:
                check_result = await check_sess.run(
                    "MATCH (w:World {session_id: $sid}) RETURN count(w) AS cnt",
                    sid=sid,
                )
                record = await check_result.single()
                world_exists = record is not None and record["cnt"] > 0

            if not world_exists:
                if world_seed_dict is not None:
                    await self.create_world_graph(
                        game_session_id,
                        WorldSeed.model_validate(world_seed_dict),
                    )
                    log.info("world_graph_base_seeded", session_id=sid)
                else:
                    log.warning(
                        "world_graph_seed_unavailable",
                        session_id=sid,
                        note="no world_seed; event replay may partially no-op",
                    )

            async with self._driver.session() as neo4j_sess:
                async with await neo4j_sess.begin_transaction() as tx:
                    for change in changes:
                        await _dispatch_change(tx, sid, change, log)
                    await tx.commit()

        log.info(
            "world_graph_reconstructed",
            events_replayed=len(changes),
        )

    # -- Protocol method: validate_movement --------------------

    async def validate_movement(
        self,
        session_id: UUID,
        from_id: str,
        to_id: str,
    ) -> bool:
        """Check a CONNECTS_TO edge exists and is unlocked."""
        sid = str(session_id)
        query = """
        MATCH (a:Location {id: $from_id,
                           session_id: $sid})
              -[c:CONNECTS_TO]->
              (b:Location {id: $to_id,
                           session_id: $sid})
        RETURN c.is_locked AS locked
        """
        async with self._driver.session() as session:
            result = await session.run(
                query,
                from_id=from_id,
                to_id=to_id,
                sid=sid,
            )
            record = await result.single()

        if record is None:
            return False
        return not record["locked"]

    # -- Protocol method: get_world_state ----------------------

    async def get_world_state(
        self,
        session_id: UUID,
    ) -> WorldContext:
        """Return a full WorldContext snapshot for the session."""
        sid = str(session_id)
        query = """
        MATCH (ps:PlayerSession {session_id: $sid})
              -[:IS_AT]->(cur:Location)
        OPTIONAL MATCH (cur)-[:CONNECTS_TO]->(adj:Location)
        OPTIONAL MATCH (npc:NPC)-[:IS_AT]->(cur)
            WHERE npc.alive = true
        OPTIONAL MATCH (item:Item)-[:IS_AT]->(cur)
            WHERE item.hidden = false
        RETURN cur,
               collect(DISTINCT adj) AS nearby,
               collect(DISTINCT npc) AS npcs,
               collect(DISTINCT item) AS items
        """
        async with self._driver.session() as session:
            result = await session.run(query, sid=sid)
            record = await result.single()

        if record is None:
            msg = f"No world state for session {sid}"
            raise ValueError(msg)

        return WorldContext(
            current_location=_node_to_location(record["cur"]),
            nearby_locations=[_node_to_location(n) for n in record["nearby"]],
            npcs_present=[_node_to_npc(n) for n in record["npcs"]],
            items_here=[_node_to_item(n) for n in record["items"]],
        )
