"""Audit logging for completed turns."""

from tta.models.turn import TurnState


async def log_turn(turn_state: TurnState) -> None:
    """Append completed turn to audit log.

    v1: writes to Postgres turns table (handled by persistence
    layer).  This is a placeholder that will be wired to
    persistence in Wave 2.
    """
    pass  # Will be implemented when persistence is connected
