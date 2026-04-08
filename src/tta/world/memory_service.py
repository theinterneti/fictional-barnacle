"""In-memory WorldService implementation for testing."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

from tta.models.world import (
    NPC,
    Connection,
    ConnectionDirection,
    Item,
    Location,
    LocationContext,
    WorldChange,
    WorldChangeType,
    WorldContext,
    WorldEvent,
    WorldSeed,
)

# Reverse direction lookup for bidirectional connections.
# Supports both abbreviated and full-word directions.
_REVERSE_DIRECTION: dict[str, ConnectionDirection] = {
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


class InMemoryWorldService:
    """Fully in-memory WorldService fake.

    Useful for unit tests across the codebase — no Neo4j
    driver required.
    """

    def __init__(self) -> None:
        # session_id → {location_id → Location}
        self._locations: dict[str, dict[str, Location]] = {}
        # session_id → {npc_id → (NPC, location_id)}
        self._npcs: dict[str, dict[str, tuple[NPC, str]]] = {}
        # session_id → {item_id → (Item, location_id | None)}
        self._items: dict[str, dict[str, tuple[Item, str | None]]] = {}
        # session_id → list[Connection]
        self._connections: dict[str, list[Connection]] = {}
        # session_id → player_location_id
        self._player_location: dict[str, str] = {}
        # session_id → list[WorldEvent]
        self._events: dict[str, list[WorldEvent]] = {}

    # -- Protocol method: get_location_context -----------------

    async def get_location_context(
        self,
        session_id: UUID,
        location_id: str,
        depth: int = 1,
    ) -> LocationContext:
        """Return location with its exits, NPCs, and items."""
        sid = str(session_id)
        locations = self._locations.get(sid, {})
        loc = locations.get(location_id)
        if loc is None:
            msg = f"Location {location_id!r} not found for session {sid}"
            raise ValueError(msg)

        adjacent = self._get_adjacent(sid, location_id)
        npcs = self._get_npcs_at(sid, location_id)
        items = self._get_items_at(sid, location_id)

        return LocationContext(
            location=deepcopy(loc),
            adjacent_locations=[deepcopy(a) for a in adjacent],
            npcs_present=[deepcopy(n) for n in npcs],
            items_here=[deepcopy(i) for i in items],
        )

    # -- Protocol method: get_recent_events --------------------

    async def get_recent_events(
        self,
        session_id: UUID,
        limit: int = 5,
    ) -> list[WorldEvent]:
        """Return recent events for the session."""
        sid = str(session_id)
        events = self._events.get(sid, [])
        return list(reversed(events[-limit:]))

    # -- Protocol method: apply_world_changes ------------------

    async def apply_world_changes(
        self,
        session_id: UUID,
        changes: list[WorldChange],
    ) -> None:
        """Apply a batch of world mutations."""
        sid = str(session_id)
        for change in changes:
            self._apply_single(sid, change)

    # -- Protocol method: get_player_location ------------------

    async def get_player_location(
        self,
        session_id: UUID,
    ) -> Location:
        """Return the player's current location."""
        sid = str(session_id)
        loc_id = self._player_location.get(sid)
        if loc_id is None:
            msg = f"No player location for session {sid}"
            raise ValueError(msg)
        locations = self._locations.get(sid, {})
        loc = locations.get(loc_id)
        if loc is None:
            msg = f"Player location {loc_id!r} not found"
            raise ValueError(msg)
        return deepcopy(loc)

    # -- Protocol method: create_world_graph -------------------

    async def create_world_graph(
        self,
        session_id: UUID,
        world_seed: WorldSeed,
    ) -> None:
        """Materialise a WorldSeed template in memory."""
        sid = str(session_id)
        tmpl = world_seed.template
        id_map: dict[str, str] = {}

        # Ensure session dicts exist.
        self._locations.setdefault(sid, {})
        self._npcs.setdefault(sid, {})
        self._items.setdefault(sid, {})
        self._connections.setdefault(sid, [])
        self._events.setdefault(sid, [])

        # Regions — generate IDs.
        for region in tmpl.regions:
            id_map[region.key] = uuid4().hex

        # Locations
        starting_loc_id: str | None = None
        for loc in tmpl.locations:
            lid = uuid4().hex
            id_map[loc.key] = lid
            region_id = id_map.get(loc.region_key)
            location = Location(
                id=lid,
                name=loc.key,
                description=loc.archetype,
                type=loc.type,
                region_id=region_id,
                light_level=loc.light_level,
                template_key=loc.key,
            )
            self._locations[sid][lid] = location
            if loc.is_starting_location:
                starting_loc_id = lid

        # Connections
        for conn in tmpl.connections:
            fid = id_map.get(conn.from_key, "")
            tid = id_map.get(conn.to_key, "")
            self._connections[sid].append(
                Connection(
                    from_id=fid,
                    to_id=tid,
                    direction=conn.direction,
                    is_locked=conn.is_locked,
                    is_hidden=conn.is_hidden,
                )
            )
            if conn.bidirectional:
                if conn.direction not in _REVERSE_DIRECTION:
                    msg = f"Unknown direction '{conn.direction}' for reverse lookup"
                    raise ValueError(msg)
                rev = _REVERSE_DIRECTION[conn.direction]
                self._connections[sid].append(
                    Connection(
                        from_id=tid,
                        to_id=fid,
                        direction=rev,
                        is_locked=conn.is_locked,
                        is_hidden=conn.is_hidden,
                    )
                )

        # NPCs
        for npc in tmpl.npcs:
            nid = uuid4().hex
            id_map[npc.key] = nid
            loc_id = id_map.get(npc.location_key, "")
            npc_model = NPC(
                id=nid,
                name=npc.key,
                description=npc.archetype,
                role=npc.role,
                disposition=npc.disposition,
                template_key=npc.key,
            )
            self._npcs[sid][nid] = (npc_model, loc_id)

        # Items — resolve holder (location or NPC's location)
        for item in tmpl.items:
            iid = uuid4().hex
            id_map[item.key] = iid
            parent_loc: str | None = None
            if item.location_key:
                parent_loc = id_map.get(item.location_key)
            elif item.npc_key:
                # Item is held by an NPC — place at NPC's location
                npc_id = id_map.get(item.npc_key, "")
                for npc_model, npc_loc in self._npcs.get(sid, {}).values():
                    if npc_model.id == npc_id:
                        parent_loc = npc_loc
                        break
            item_model = Item(
                id=iid,
                name=item.key,
                description=item.archetype,
                item_type=item.type,
                portable=item.portable,
                hidden=item.hidden,
                template_key=item.key,
            )
            self._items[sid][iid] = (
                item_model,
                parent_loc,
            )

        # Player location
        if starting_loc_id is None and tmpl.locations:
            starting_loc_id = id_map.get(tmpl.locations[0].key)
        if starting_loc_id:
            self._player_location[sid] = starting_loc_id

    # -- Protocol method: cleanup_session ----------------------

    async def cleanup_session(
        self,
        session_id: UUID,
    ) -> None:
        """Remove all data for a session."""
        sid = str(session_id)
        self._locations.pop(sid, None)
        self._npcs.pop(sid, None)
        self._items.pop(sid, None)
        self._connections.pop(sid, None)
        self._player_location.pop(sid, None)
        self._events.pop(sid, None)

    # -- Protocol method: validate_movement --------------------

    async def validate_movement(
        self,
        session_id: UUID,
        from_id: str,
        to_id: str,
    ) -> bool:
        """Check a connection exists and is unlocked."""
        sid = str(session_id)
        for conn in self._connections.get(sid, []):
            if conn.from_id == from_id and conn.to_id == to_id:
                return not conn.is_locked
        return False

    # -- Protocol method: get_world_state ----------------------

    async def get_world_state(
        self,
        session_id: UUID,
    ) -> WorldContext:
        """Return full WorldContext for the session."""
        sid = str(session_id)
        loc_id = self._player_location.get(sid)
        if loc_id is None:
            msg = f"No world state for session {sid}"
            raise ValueError(msg)

        locations = self._locations.get(sid, {})
        current = locations.get(loc_id)
        if current is None:
            msg = f"Player location {loc_id!r} not found"
            raise ValueError(msg)

        adjacent = self._get_adjacent(sid, loc_id)
        npcs = self._get_npcs_at(sid, loc_id)
        items = self._get_items_at(sid, loc_id)

        return WorldContext(
            current_location=deepcopy(current),
            nearby_locations=[deepcopy(a) for a in adjacent],
            npcs_present=[deepcopy(n) for n in npcs],
            items_here=[deepcopy(i) for i in items],
        )

    # -- Internal helpers --------------------------------------

    def _get_adjacent(self, sid: str, location_id: str) -> list[Location]:
        """Return locations reachable from location_id."""
        locations = self._locations.get(sid, {})
        result: list[Location] = []
        for conn in self._connections.get(sid, []):
            if conn.from_id == location_id:
                adj = locations.get(conn.to_id)
                if adj is not None:
                    result.append(adj)
        return result

    def _get_npcs_at(self, sid: str, location_id: str) -> list[NPC]:
        """Return alive NPCs at a location."""
        result: list[NPC] = []
        for npc, loc_id in self._npcs.get(sid, {}).values():
            if loc_id == location_id and npc.alive:
                result.append(npc)
        return result

    def _get_items_at(self, sid: str, location_id: str) -> list[Item]:
        """Return visible items at a location."""
        result: list[Item] = []
        for item, loc_id in self._items.get(sid, {}).values():
            if loc_id == location_id and not item.hidden:
                result.append(item)
        return result

    def _apply_single(self, sid: str, change: WorldChange) -> None:
        """Route a WorldChange to the correct handler."""
        ct = change.type
        eid = change.entity_id
        payload = change.payload

        if ct == WorldChangeType.PLAYER_MOVED:
            to_id = payload.get("to_id", eid)
            self._player_location[sid] = to_id
            locs = self._locations.get(sid, {})
            if to_id in locs:
                locs[to_id].visited = True

        elif ct == WorldChangeType.ITEM_TAKEN:
            items = self._items.get(sid, {})
            if eid in items:
                item, _ = items[eid]
                items[eid] = (item, None)

        elif ct == WorldChangeType.ITEM_DROPPED:
            items = self._items.get(sid, {})
            loc_id = self._player_location.get(sid)
            if eid in items and loc_id:
                item, _ = items[eid]
                items[eid] = (item, loc_id)

        elif ct == WorldChangeType.NPC_MOVED:
            npcs = self._npcs.get(sid, {})
            to_loc = payload.get("to_location_id", "")
            if eid in npcs:
                npc, _ = npcs[eid]
                npcs[eid] = (npc, to_loc)

        elif ct == WorldChangeType.NPC_DISPOSITION_CHANGED:
            npcs = self._npcs.get(sid, {})
            if eid in npcs:
                npc, loc_id = npcs[eid]
                npc.disposition = payload.get("disposition", "neutral")

        elif ct == WorldChangeType.LOCATION_STATE_CHANGED:
            locs = self._locations.get(sid, {})
            if eid in locs:
                loc = locs[eid]
                if "description" in payload:
                    loc.description = payload["description"]
                if "light_level" in payload:
                    loc.light_level = payload["light_level"]
                if "is_accessible" in payload:
                    loc.is_accessible = payload["is_accessible"]

        elif ct == WorldChangeType.CONNECTION_LOCKED:
            to_id = payload.get("to_id", "")
            for conn in self._connections.get(sid, []):
                if conn.from_id == eid and conn.to_id == to_id:
                    conn.is_locked = True

        elif ct == WorldChangeType.CONNECTION_UNLOCKED:
            to_id = payload.get("to_id", "")
            for conn in self._connections.get(sid, []):
                if conn.from_id == eid and conn.to_id == to_id:
                    conn.is_locked = False

        elif ct == WorldChangeType.ITEM_VISIBILITY_CHANGED:
            items = self._items.get(sid, {})
            if eid in items:
                item, loc_id = items[eid]
                item.hidden = payload.get("hidden", False)

        elif ct == WorldChangeType.NPC_STATE_CHANGED:
            npcs = self._npcs.get(sid, {})
            if eid in npcs:
                npc, loc_id = npcs[eid]
                npc.state = payload.get("state", "idle")
