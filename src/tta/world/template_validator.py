"""Template validation — 10 structural rules for WorldTemplate."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tta.models.world import WorldTemplate

# ── Exception hierarchy ──────────────────────────────────────────


class TemplateValidationError(Exception):
    """Base class for all template validation errors."""


class DuplicateKeyError(TemplateValidationError):
    """Raised when two or more entities share the same key."""


class DanglingReferenceError(TemplateValidationError):
    """Raised when a foreign-key reference points at nothing."""


class NoStartingLocationError(TemplateValidationError):
    """Raised when there is not exactly one starting location."""


class DirectionConflictError(TemplateValidationError):
    """Raised when a location has duplicate exit directions."""


class ItemPlacementError(TemplateValidationError):
    """Raised when an item has neither or both placements."""


class EmptyTemplateError(TemplateValidationError):
    """Raised when a template contains no locations."""


class DisconnectedGraphError(TemplateValidationError):
    """Raised when some locations are unreachable from start."""


# ── Validation rules ─────────────────────────────────────────────


def _rule_unique_keys(template: WorldTemplate) -> None:
    """Rule 1: All key values must be unique across the template."""
    seen: dict[str, str] = {}
    entries: list[tuple[str, str]] = []

    for r in template.regions:
        entries.append((r.key, "region"))
    for loc in template.locations:
        entries.append((loc.key, "location"))
    for npc in template.npcs:
        entries.append((npc.key, "npc"))
    for item in template.items:
        entries.append((item.key, "item"))

    for key, kind in entries:
        if key in seen:
            msg = f"Duplicate key '{key}' (found in {seen[key]} and {kind})"
            raise DuplicateKeyError(msg)
        seen[key] = kind


def _rule_region_refs(template: WorldTemplate) -> None:
    """Rule 2: Every location.region_key must exist."""
    region_keys = {r.key for r in template.regions}
    for loc in template.locations:
        if loc.region_key not in region_keys:
            msg = f"Location '{loc.key}' references unknown region '{loc.region_key}'"
            raise DanglingReferenceError(msg)


def _rule_location_refs(template: WorldTemplate) -> None:
    """Rule 3: NPC/item location_key refs must exist."""
    loc_keys = {loc.key for loc in template.locations}
    npc_keys = {npc.key for npc in template.npcs}
    for npc in template.npcs:
        if npc.location_key not in loc_keys:
            msg = f"NPC '{npc.key}' references unknown location '{npc.location_key}'"
            raise DanglingReferenceError(msg)
    for item in template.items:
        if item.location_key is not None and item.location_key not in loc_keys:
            msg = (
                f"Item '{item.key}' references "
                f"unknown location '{item.location_key}'"
            )
            raise DanglingReferenceError(msg)
        if item.npc_key is not None and item.npc_key not in npc_keys:
            msg = f"Item '{item.key}' references unknown NPC '{item.npc_key}'"
            raise DanglingReferenceError(msg)


def _rule_npc_knowledge_refs(template: WorldTemplate) -> None:
    """Rule 4: Knowledge npc_key and about_key must exist."""
    npc_keys = {npc.key for npc in template.npcs}
    all_keys: set[str] = set()
    for r in template.regions:
        all_keys.add(r.key)
    for loc in template.locations:
        all_keys.add(loc.key)
    all_keys.update(npc_keys)
    for item in template.items:
        all_keys.add(item.key)

    for k in template.knowledge:
        if k.npc_key not in npc_keys:
            msg = f"Knowledge entry references unknown npc_key '{k.npc_key}'"
            raise DanglingReferenceError(msg)
        if k.about_key not in all_keys:
            msg = f"Knowledge entry references unknown about_key '{k.about_key}'"
            raise DanglingReferenceError(msg)


def _rule_one_starting_location(template: WorldTemplate) -> None:
    """Rule 5: Exactly one location must be the start."""
    starts = [loc.key for loc in template.locations if loc.is_starting_location]
    if len(starts) != 1:
        msg = f"Expected exactly 1 starting location, found {len(starts)}: {starts}"
        raise NoStartingLocationError(msg)


def _rule_connection_refs(template: WorldTemplate) -> None:
    """Rule 6: Connection from_key/to_key must exist."""
    loc_keys = {loc.key for loc in template.locations}
    for conn in template.connections:
        if conn.from_key not in loc_keys:
            msg = f"Connection references unknown from_key '{conn.from_key}'"
            raise DanglingReferenceError(msg)
        if conn.to_key not in loc_keys:
            msg = f"Connection references unknown to_key '{conn.to_key}'"
            raise DanglingReferenceError(msg)


def _rule_no_direction_conflicts(template: WorldTemplate) -> None:
    """Rule 7: No location has two exits in the same direction."""
    exits: dict[str, set[str]] = defaultdict(set)
    for conn in template.connections:
        if conn.direction in exits[conn.from_key]:
            msg = (
                f"Location '{conn.from_key}' has "
                f"duplicate exit direction '{conn.direction}'"
            )
            raise DirectionConflictError(msg)
        exits[conn.from_key].add(conn.direction)

        if conn.bidirectional:
            reverse = _reverse_direction(conn.direction)
            if reverse in exits[conn.to_key]:
                msg = (
                    f"Location '{conn.to_key}' has "
                    f"duplicate exit direction '{reverse}' "
                    f"(from bidirectional connection)"
                )
                raise DirectionConflictError(msg)
            exits[conn.to_key].add(reverse)


_REVERSE_MAP: dict[str, str] = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "northeast": "southwest",
    "southwest": "northeast",
    "northwest": "southeast",
    "southeast": "northwest",
    "up": "down",
    "down": "up",
    "in": "out",
    "out": "in",
    "n": "s",
    "s": "n",
    "e": "w",
    "w": "e",
    "ne": "sw",
    "sw": "ne",
    "nw": "se",
    "se": "nw",
}


def _reverse_direction(direction: str) -> str:
    """Return the opposite compass direction."""
    return _REVERSE_MAP.get(direction, f"reverse_{direction}")


def _rule_item_placement(template: WorldTemplate) -> None:
    """Rule 8: Each item must have exactly one placement."""
    for item in template.items:
        has_loc = item.location_key is not None
        has_npc = item.npc_key is not None
        if has_loc == has_npc:
            msg = (
                f"Item '{item.key}' must have exactly one of "
                f"location_key or npc_key "
                f"(got location_key={item.location_key!r}, "
                f"npc_key={item.npc_key!r})"
            )
            raise ItemPlacementError(msg)


def _rule_at_least_one_location(template: WorldTemplate) -> None:
    """Rule 9: Template must contain at least one location."""
    if not template.locations:
        raise EmptyTemplateError("Template has no locations")


def _rule_connected_graph(template: WorldTemplate) -> None:
    """Rule 10: All locations reachable from starting location."""
    loc_keys = {loc.key for loc in template.locations}
    if not loc_keys:
        return  # Rule 9 catches this

    start = None
    for loc in template.locations:
        if loc.is_starting_location:
            start = loc.key
            break
    if start is None:
        return  # Rule 5 catches this

    adj: dict[str, set[str]] = defaultdict(set)
    for conn in template.connections:
        adj[conn.from_key].add(conn.to_key)
        if conn.bidirectional:
            adj[conn.to_key].add(conn.from_key)

    visited: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adj[node] - visited)

    unreachable = loc_keys - visited
    if unreachable:
        msg = f"Locations unreachable from '{start}': {sorted(unreachable)}"
        raise DisconnectedGraphError(msg)


# ── Public entry point ───────────────────────────────────────────

_RULES = [
    _rule_unique_keys,
    _rule_at_least_one_location,
    _rule_region_refs,
    _rule_location_refs,
    _rule_npc_knowledge_refs,
    _rule_one_starting_location,
    _rule_connection_refs,
    _rule_no_direction_conflicts,
    _rule_item_placement,
    _rule_connected_graph,
]


def validate_template(template: WorldTemplate) -> None:
    """Validate a WorldTemplate against all 10 structural rules.

    Raises ``TemplateValidationError`` (or a subclass) on the
    first rule that fails.
    """
    for rule in _RULES:
        rule(template)
