"""Neo4j world service helpers — graph queries, node conversion, dispatch.

Extracted from neo4j_service.py during code health decomposition.
"""

from uuid import uuid4

import structlog
from neo4j import Query

from tta.models.world import (
    NPC,
    Item,
    Location,
    WorldChange,
    WorldChangeType,
)

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


def _location_context_query(depth: int) -> str:
    """Build a location context query for a given hop depth."""
    return f"""
    MATCH (loc:Location {{id: $location_id,
                         session_id: $session_id}})
    OPTIONAL MATCH (loc)-[:CONNECTS_TO*1..{depth}]->(adj:Location)
    OPTIONAL MATCH (npc:NPC)-[:IS_AT]->(loc)
        WHERE npc.alive = true
    OPTIONAL MATCH (item:Item)-[:IS_AT]->(loc)
        WHERE item.hidden = false
    RETURN loc,
           collect(DISTINCT adj) AS exits,
           collect(DISTINCT npc) AS npcs,
           collect(DISTINCT item) AS items
    """


# Pre-built queries keyed by depth (1–5), wrapped as Query objects
# to satisfy neo4j's LiteralString typing requirement.
_LOCATION_CONTEXT_QUERIES: dict[int, Query] = {
    d: Query(_location_context_query(d))  # type: ignore[arg-type]
    for d in range(1, 6)
}


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
    raw_tags = node.get("tags")
    tags = list(raw_tags) if raw_tags else []
    raw_traits = node.get("traits")
    traits = list(raw_traits) if raw_traits else []
    return NPC(
        id=node["id"],
        name=node["name"],
        description=node["description"],
        disposition=node.get("disposition", "neutral"),
        alive=node.get("alive", True),
        role=node.get("role"),
        state=node.get("state", "idle"),
        personality=node.get("personality"),
        dialogue_style=node.get("dialogue_style"),
        tags=tags,
        template_key=node.get("template_key"),
        session_id=node.get("session_id"),
        tier=node.get("tier", "background"),
        traits=traits,
        goals_short=node.get("goals_short"),
        goals_long=node.get("goals_long"),
        knowledge_summary=node.get("knowledge_summary"),
        schedule=node.get("schedule"),
        voice=node.get("voice"),
        occupation=node.get("occupation"),
        mannerisms=node.get("mannerisms"),
        appearance=node.get("appearance"),
        backstory=node.get("backstory"),
        interaction_count=node.get("interaction_count", 0),
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
    elif ct == WorldChangeType.NPC_TIER_CHANGED:
        await tx.run(
            """
            MATCH (n:NPC {id: $eid, session_id: $sid})
            SET n.tier = $tier
            """,
            eid=eid,
            sid=sid,
            tier=payload.get("tier", "background"),
        )
    elif ct == WorldChangeType.RELATIONSHIP_CHANGED:
        pass  # Handled by RelationshipService
    else:  # pragma: no cover
        log.warning(
            "unknown_change_type",
            change_type=str(ct),
        )
