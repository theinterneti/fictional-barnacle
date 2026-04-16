"""WorldChange handler dispatch — validate and apply world mutations.

Provides validation rules per WorldChangeType and a batch-apply
entry point that validates each change before forwarding to the
WorldService.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from tta.models.world import WorldChange, WorldChangeType

if TYPE_CHECKING:
    from uuid import UUID

    from tta.world.service import WorldService

log = structlog.get_logger()


class ChangeValidationError(Exception):
    """Raised when a world change fails validation."""


# -- Per-type validation dispatchers --------------------------------


async def _validate_player_moved(
    change: WorldChange,
    world_service: WorldService,
    session_id: UUID,
) -> None:
    payload = change.payload
    if "from_id" not in payload or "to_id" not in payload:
        msg = "PLAYER_MOVED requires 'from_id' and 'to_id'"
        raise ChangeValidationError(msg)
    ok = await world_service.validate_movement(
        session_id, payload["from_id"], payload["to_id"]
    )
    if not ok:
        msg = (
            f"Movement from {payload['from_id']!r} to {payload['to_id']!r} is not valid"
        )
        raise ChangeValidationError(msg)


def _validate_item_taken(change: WorldChange) -> None:
    if not change.entity_id:
        msg = "ITEM_TAKEN requires entity_id to be the item ID"
        raise ChangeValidationError(msg)


def _validate_item_dropped(change: WorldChange) -> None:
    if not change.entity_id:
        msg = "ITEM_DROPPED requires entity_id to be the item ID"
        raise ChangeValidationError(msg)


def _validate_npc_moved(change: WorldChange) -> None:
    if "to_location_id" not in change.payload:
        msg = "NPC_MOVED requires 'to_location_id'"
        raise ChangeValidationError(msg)


def _validate_npc_disposition_changed(change: WorldChange) -> None:
    if "disposition" not in change.payload:
        msg = "NPC_DISPOSITION_CHANGED requires 'disposition'"
        raise ChangeValidationError(msg)


def _validate_npc_state_changed(change: WorldChange) -> None:
    if "state" not in change.payload:
        msg = "NPC_STATE_CHANGED requires 'state'"
        raise ChangeValidationError(msg)


def _validate_location_state_changed(change: WorldChange) -> None:
    if not change.payload:
        msg = "LOCATION_STATE_CHANGED requires at least one property to change"
        raise ChangeValidationError(msg)


def _validate_connection_locked(change: WorldChange) -> None:
    if "from_id" not in change.payload or "to_id" not in change.payload:
        msg = "CONNECTION_LOCKED requires 'from_id' and 'to_id'"
        raise ChangeValidationError(msg)


def _validate_connection_unlocked(change: WorldChange) -> None:
    if "from_id" not in change.payload or "to_id" not in change.payload:
        msg = "CONNECTION_UNLOCKED requires 'from_id' and 'to_id'"
        raise ChangeValidationError(msg)


def _validate_quest_status_changed(change: WorldChange) -> None:
    if "new_status" not in change.payload:
        msg = "QUEST_STATUS_CHANGED requires 'new_status'"
        raise ChangeValidationError(msg)


def _validate_item_visibility_changed(change: WorldChange) -> None:
    if "hidden" not in change.payload:
        msg = "ITEM_VISIBILITY_CHANGED requires 'hidden'"
        raise ChangeValidationError(msg)
    if not isinstance(change.payload["hidden"], bool):
        msg = "ITEM_VISIBILITY_CHANGED 'hidden' must be a bool"
        raise ChangeValidationError(msg)


def _validate_relationship_changed(change: WorldChange) -> None:
    if not change.entity_id:
        msg = "RELATIONSHIP_CHANGED requires entity_id (the NPC identifier)"
        raise ChangeValidationError(msg)


# -- Public API -----------------------------------------------------


async def validate_change(
    change: WorldChange,
    world_service: WorldService,
    session_id: UUID,
) -> None:
    """Validate a single change. Raises ChangeValidationError."""
    ct = change.type

    if ct == WorldChangeType.PLAYER_MOVED:
        await _validate_player_moved(change, world_service, session_id)
    elif ct == WorldChangeType.ITEM_TAKEN:
        _validate_item_taken(change)
    elif ct == WorldChangeType.ITEM_DROPPED:
        _validate_item_dropped(change)
    elif ct == WorldChangeType.NPC_MOVED:
        _validate_npc_moved(change)
    elif ct == WorldChangeType.NPC_DISPOSITION_CHANGED:
        _validate_npc_disposition_changed(change)
    elif ct == WorldChangeType.NPC_STATE_CHANGED:
        _validate_npc_state_changed(change)
    elif ct == WorldChangeType.LOCATION_STATE_CHANGED:
        _validate_location_state_changed(change)
    elif ct == WorldChangeType.CONNECTION_LOCKED:
        _validate_connection_locked(change)
    elif ct == WorldChangeType.CONNECTION_UNLOCKED:
        _validate_connection_unlocked(change)
    elif ct == WorldChangeType.QUEST_STATUS_CHANGED:
        _validate_quest_status_changed(change)
    elif ct == WorldChangeType.ITEM_VISIBILITY_CHANGED:
        _validate_item_visibility_changed(change)
    elif ct == WorldChangeType.RELATIONSHIP_CHANGED:
        _validate_relationship_changed(change)

    log.debug(
        "change_validated",
        change_type=str(ct),
        entity_id=change.entity_id,
    )


async def apply_changes(
    changes: list[WorldChange],
    world_service: WorldService,
    session_id: UUID,
) -> list[WorldChange]:
    """Validate and apply changes.

    Returns the list of successfully applied changes.
    Raises ChangeValidationError on the first invalid change.
    """
    applied: list[WorldChange] = []
    for change in changes:
        await validate_change(change, world_service, session_id)
        applied.append(change)

    await world_service.apply_world_changes(session_id, applied)

    log.info(
        "changes_applied",
        count=len(applied),
        session_id=str(session_id),
    )
    return applied
