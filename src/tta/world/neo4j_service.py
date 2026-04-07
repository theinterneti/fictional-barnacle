"""Neo4j-backed WorldService implementation."""

from __future__ import annotations

from uuid import UUID, uuid4

import structlog
from neo4j import AsyncDriver

from tta.models.world import (
    NPC,
    Item,
    Location,
    LocationContext,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldEvent,
    WorldSeed,
)

logger = structlog.get_logger(__name__)

# Reverse direction lookup for bidirectional connections.
# Supports both abbreviated and full-word directions.
_REVERSE_DIRECTION: dict[str, str] = {
    "n": "s",
    "s": "n",
    "e": "w",
    "w": "e",
    "ne": "sw",
    "sw": "ne",
    "nw": "se",
    "se": "nw",
    "up": "down",
    "down": "up",
    "in": "out",
    "out": "in",
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "northeast": "southwest",
    "southwest": "northeast",
    "northwest": "southeast",
    "southeast": "northwest",
}


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
        include (default 1 = immediate neighbors only).
        """
        sid = str(session_id)
        safe_depth = max(1, min(depth, 5))
        query = f"""
        MATCH (loc:Location {{id: $location_id,
                             session_id: $session_id}})
        OPTIONAL MATCH (loc)-[:CONNECTS_TO*1..{safe_depth}]->(adj:Location)
        OPTIONAL MATCH (npc:NPC)-[:IS_AT]->(loc)
            WHERE npc.alive = true
        OPTIONAL MATCH (item:Item)-[:IS_AT]->(loc)
            WHERE item.hidden = false
        RETURN loc,
               collect(DISTINCT adj) AS exits,
               collect(DISTINCT npc) AS npcs,
               collect(DISTINCT item) AS items
        """
        async with self._driver.async_session() as session:
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

        async with self._driver.async_session() as session:
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
        async with self._driver.async_session() as session:
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

        async with self._driver.async_session() as session:
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

                # 5. NPCs
                for npc in tmpl.npcs:
                    nid = _gen_id()
                    id_map[npc.key] = nid
                    loc_id = id_map.get(npc.location_key, "")
                    await tx.run(
                        """
                        MATCH (l:Location {
                            id: $loc_id,
                            session_id: $sid
                        })
                        CREATE (n:NPC {
                            id: $id,
                            session_id: $sid,
                            name: $key,
                            description: $archetype,
                            role: $role,
                            disposition: $disp,
                            alive: true,
                            state: 'idle',
                            template_key: $key
                        })
                        CREATE (n)-[:IS_AT]->(l)
                        """,
                        id=nid,
                        sid=sid,
                        key=npc.key,
                        archetype=npc.archetype,
                        role=npc.role,
                        disp=npc.disposition,
                        loc_id=loc_id,
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
        async with self._driver.async_session() as session:
            await session.run(query, session_id=sid)

        logger.info("session_cleaned_up", session_id=sid)

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
        async with self._driver.async_session() as session:
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
        async with self._driver.async_session() as session:
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


# -- Internal helpers ------------------------------------------


def _gen_id() -> str:
    """Generate a unique string ID."""
    return uuid4().hex


def _node_to_location(node: dict) -> Location:  # type: ignore[type-arg]
    """Convert a Neo4j node dict to a Location model."""
    return Location(
        id=node["id"],
        name=node["name"],
        description=node["description"],
        type=node.get("type", "interior"),
        visited=node.get("visited", False),
        region_id=node.get("region_id"),
        light_level=node.get("light_level", "lit"),
        is_accessible=node.get("is_accessible", True),
        template_key=node.get("template_key"),
    )


def _node_to_npc(node: dict) -> NPC:  # type: ignore[type-arg]
    """Convert a Neo4j node dict to an NPC model."""
    return NPC(
        id=node["id"],
        name=node["name"],
        description=node["description"],
        disposition=node.get("disposition", "neutral"),
        alive=node.get("alive", True),
        role=node.get("role"),
        state=node.get("state", "idle"),
        template_key=node.get("template_key"),
    )


def _node_to_item(node: dict) -> Item:  # type: ignore[type-arg]
    """Convert a Neo4j node dict to an Item model."""
    return Item(
        id=node["id"],
        name=node["name"],
        description=node["description"],
        portable=node.get("portable", True),
        hidden=node.get("hidden", False),
        item_type=node.get("item_type"),
        template_key=node.get("template_key"),
    )


async def _dispatch_change(
    tx,  # noqa: ANN001
    sid: str,
    change: WorldChange,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Route a single WorldChange to the correct Cypher."""
    ct = change.type
    eid = change.entity_id
    payload = change.payload

    if ct == WorldChangeType.PLAYER_MOVED:
        await tx.run(
            """
            MATCH (ps:PlayerSession {session_id: $sid})
                  -[r:IS_AT]->(:Location)
            DELETE r
            WITH ps
            MATCH (loc:Location {
                id: $to_id, session_id: $sid
            })
            CREATE (ps)-[:IS_AT]->(loc)
            SET loc.visited = true
            """,
            sid=sid,
            to_id=payload.get("to_id", eid),
        )
    elif ct == WorldChangeType.ITEM_TAKEN:
        await tx.run(
            """
            MATCH (i:Item {id: $eid, session_id: $sid})
                  -[r:IS_AT]->(:Location)
            DELETE r
            WITH i
            MATCH (ps:PlayerSession {session_id: $sid})
            CREATE (i)-[:HELD_BY]->(ps)
            """,
            eid=eid,
            sid=sid,
        )
    elif ct == WorldChangeType.ITEM_DROPPED:
        await tx.run(
            """
            MATCH (i:Item {id: $eid, session_id: $sid})
                  -[r:HELD_BY]->(:PlayerSession)
            DELETE r
            WITH i
            MATCH (ps:PlayerSession {session_id: $sid})
                  -[:IS_AT]->(loc:Location)
            CREATE (i)-[:IS_AT]->(loc)
            """,
            eid=eid,
            sid=sid,
        )
    elif ct == WorldChangeType.NPC_MOVED:
        to_loc = payload.get("to_location_id", "")
        await tx.run(
            """
            MATCH (n:NPC {id: $eid, session_id: $sid})
                  -[r:IS_AT]->(:Location)
            DELETE r
            WITH n
            MATCH (loc:Location {
                id: $to_loc, session_id: $sid
            })
            CREATE (n)-[:IS_AT]->(loc)
            """,
            eid=eid,
            sid=sid,
            to_loc=to_loc,
        )
    elif ct == WorldChangeType.NPC_DISPOSITION_CHANGED:
        await tx.run(
            """
            MATCH (n:NPC {id: $eid, session_id: $sid})
            SET n.disposition = $disp
            """,
            eid=eid,
            sid=sid,
            disp=payload.get("disposition", "neutral"),
        )
    elif ct == WorldChangeType.LOCATION_STATE_CHANGED:
        props = {
            k: v
            for k, v in payload.items()
            if k
            in {
                "description",
                "light_level",
                "is_accessible",
            }
        }
        if props:
            set_clauses = ", ".join(f"loc.{k} = ${k}" for k in props)
            await tx.run(
                f"""
                MATCH (loc:Location {{
                    id: $eid, session_id: $sid
                }})
                SET {set_clauses}
                """,
                eid=eid,
                sid=sid,
                **props,
            )
    elif ct == WorldChangeType.CONNECTION_LOCKED:
        await tx.run(
            """
            MATCH (:Location {id: $fid, session_id: $sid})
                  -[c:CONNECTS_TO]->
                  (:Location {id: $tid, session_id: $sid})
            SET c.is_locked = true
            """,
            fid=eid,
            tid=payload.get("to_id", ""),
            sid=sid,
        )
    elif ct == WorldChangeType.CONNECTION_UNLOCKED:
        await tx.run(
            """
            MATCH (:Location {id: $fid, session_id: $sid})
                  -[c:CONNECTS_TO]->
                  (:Location {id: $tid, session_id: $sid})
            SET c.is_locked = false
            """,
            fid=eid,
            tid=payload.get("to_id", ""),
            sid=sid,
        )
    elif ct == WorldChangeType.QUEST_STATUS_CHANGED:
        await tx.run(
            """
            MATCH (q:Quest {id: $eid, session_id: $sid})
            SET q.status = $status
            """,
            eid=eid,
            sid=sid,
            status=payload.get("status", "active"),
        )
    elif ct == WorldChangeType.ITEM_VISIBILITY_CHANGED:
        await tx.run(
            """
            MATCH (i:Item {id: $eid, session_id: $sid})
            SET i.hidden = $hidden
            """,
            eid=eid,
            sid=sid,
            hidden=payload.get("hidden", False),
        )
    elif ct == WorldChangeType.NPC_STATE_CHANGED:
        await tx.run(
            """
            MATCH (n:NPC {id: $eid, session_id: $sid})
            SET n.state = $state
            """,
            eid=eid,
            sid=sid,
            state=payload.get("state", "idle"),
        )
    else:  # pragma: no cover
        log.warning(
            "unknown_change_type",
            change_type=str(ct),
        )
