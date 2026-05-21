"""World-change parsing: convert LLM-extracted dicts to typed change objects.

These helpers translate the LLM's unstructured world-state updates
(produced by the generate stage) into strongly-typed WorldChange and
RelationshipChange objects that the world service can apply.
"""

from __future__ import annotations

from tta.models.world import (
    RelationshipChange,
    WorldChange,
    WorldChangeType,
)

# Keywords for attribute-to-change-type inference
_ATTRIBUTE_TYPE_MAP: dict[str, WorldChangeType] = {
    "location": WorldChangeType.PLAYER_MOVED,
    "position": WorldChangeType.PLAYER_MOVED,
    "moved": WorldChangeType.PLAYER_MOVED,
    "disposition": WorldChangeType.NPC_DISPOSITION_CHANGED,
    "mood": WorldChangeType.NPC_DISPOSITION_CHANGED,
    "attitude": WorldChangeType.NPC_DISPOSITION_CHANGED,
    "state": WorldChangeType.LOCATION_STATE_CHANGED,
    "status": WorldChangeType.LOCATION_STATE_CHANGED,
    "locked": WorldChangeType.CONNECTION_LOCKED,
    "unlocked": WorldChangeType.CONNECTION_UNLOCKED,
    "taken": WorldChangeType.ITEM_TAKEN,
    "picked": WorldChangeType.ITEM_TAKEN,
    "dropped": WorldChangeType.ITEM_DROPPED,
    "quest_status": WorldChangeType.QUEST_STATUS_CHANGED,
    "quest": WorldChangeType.QUEST_STATUS_CHANGED,
    "visibility": WorldChangeType.ITEM_VISIBILITY_CHANGED,
    "relationship": WorldChangeType.RELATIONSHIP_CHANGED,
}

# Keywords for inferring relationship direction from LLM output
_POSITIVE_KEYWORDS = frozenset(
    {"increase", "improve", "gain", "grow", "positive", "warm", "better", "higher"}
)
_NEGATIVE_KEYWORDS = frozenset(
    {"decrease", "lose", "drop", "worsen", "negative", "cold", "worse", "lower"}
)


def _build_typed_payload(change_type: WorldChangeType, item: dict) -> dict:
    """Build a payload dict with the keys required by validate_change()."""
    base: dict = {
        "attribute": str(item.get("attribute") or ""),
        "old_value": item.get("old_value"),
        "new_value": item.get("new_value"),
        "reason": item.get("reason", ""),
    }
    # Merge any extra keys the LLM may have provided (e.g. from_id, to_id)
    for k, v in item.items():
        if k not in ("entity", "attribute", "old_value", "new_value", "reason"):
            base[k] = v

    nv = item.get("new_value")
    ct = change_type
    if ct == WorldChangeType.PLAYER_MOVED:
        base.setdefault("from_id", item.get("old_value", ""))
        base.setdefault("to_id", item.get("new_value", ""))
    elif ct == WorldChangeType.NPC_DISPOSITION_CHANGED:
        base.setdefault("disposition", nv if nv is not None else "")
    elif ct == WorldChangeType.NPC_STATE_CHANGED:
        base.setdefault("state", nv if nv is not None else "")
    elif ct == WorldChangeType.NPC_MOVED:
        base.setdefault("to_location_id", nv if nv is not None else "")
    elif ct == WorldChangeType.CONNECTION_LOCKED:
        base.setdefault("from_id", item.get("old_value", ""))
        base.setdefault("to_id", str(item.get("entity", "")))
    elif ct == WorldChangeType.CONNECTION_UNLOCKED:
        base.setdefault("from_id", item.get("old_value", ""))
        base.setdefault("to_id", str(item.get("entity", "")))
    elif ct == WorldChangeType.QUEST_STATUS_CHANGED:
        base.setdefault("new_status", nv if nv is not None else "")
    elif ct == WorldChangeType.ITEM_VISIBILITY_CHANGED:
        hidden = nv if isinstance(nv, bool) else str(nv).lower() == "true"
        base.setdefault("hidden", hidden)
    elif ct == WorldChangeType.RELATIONSHIP_CHANGED:
        base.setdefault("dimension", str(item.get("attribute") or "trust"))
        base.setdefault("direction", str(nv) if nv is not None else "positive")
    return base


def translate_world_updates(raw: list[dict]) -> list[WorldChange]:
    """Convert LLM-extracted dicts to WorldChange objects (best-effort)."""
    changes: list[WorldChange] = []
    for item in raw:
        entity = item.get("entity", "")
        attribute = str(item.get("attribute") or "")
        if not entity:
            continue
        # Infer change type from attribute keywords
        change_type = WorldChangeType.LOCATION_STATE_CHANGED
        attr_lower = attribute.lower()
        for keyword, ct in sorted(
            _ATTRIBUTE_TYPE_MAP.items(), key=lambda x: -len(x[0])
        ):
            if keyword in attr_lower:
                change_type = ct
                break
        changes.append(
            WorldChange(
                type=change_type,
                entity_id=str(entity),
                payload=_build_typed_payload(change_type, item),
            )
        )
    return changes


def parse_relationship_delta(payload: dict) -> RelationshipChange:
    """Convert LLM-extracted relationship payload to a RelationshipChange.

    The payload contains ``dimension`` (attribute like "trust", "fear") and
    ``direction`` (a descriptive string like "increased", "grew warmer").
    We map these to a small numeric delta on the appropriate axis.
    """
    dimension = payload.get("dimension", "trust").lower()
    direction_raw = str(payload.get("direction", "positive")).lower()

    # Determine sign: positive or negative shift
    sign = 1
    if any(kw in direction_raw for kw in _NEGATIVE_KEYWORDS):
        sign = -1

    delta = 5 * sign  # modest default step

    trust = 0
    affinity = 0
    respect = 0
    fear = 0
    familiarity = 3  # any interaction increases familiarity

    if "trust" in dimension:
        trust = delta
    elif "affinity" in dimension or "warmth" in dimension:
        affinity = delta
    elif "respect" in dimension:
        respect = delta
    elif "fear" in dimension:
        fear = abs(delta) if sign > 0 else -abs(delta)
    else:
        # Generic / unmapped -> trust + affinity
        trust = delta
        affinity = delta

    return RelationshipChange(
        trust=trust,
        affinity=affinity,
        respect=respect,
        fear=fear,
        familiarity=familiarity,
    )
