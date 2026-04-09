"""Session-level moderation flagging (S24 FR-24.11).

Tracks blocked actions per game session and auto-flags when a
player accumulates *N* blocks within *M* minutes.  Tracking
is in-memory (per-process); a distributed implementation can
replace this with Redis if horizontal scaling requires it.
"""

from collections import defaultdict
from datetime import UTC, datetime

import structlog

log = structlog.get_logger()


class SessionFlagTracker:
    """Detects rapid-fire blocked content per session.

    Parameters
    ----------
    threshold:
        Number of blocked actions before flagging (default 5).
    window_minutes:
        Sliding window in minutes (default 10).
    """

    def __init__(
        self,
        *,
        threshold: int = 5,
        window_minutes: int = 10,
    ) -> None:
        self._threshold = threshold
        self._window_minutes = window_minutes
        # game_id → list of block timestamps
        self._blocks: dict[str, list[datetime]] = defaultdict(list)

    def record_block(self, game_id: str, player_id: str) -> bool:
        """Record a blocked action and return ``True`` if flagged.

        Returns ``True`` when the threshold is crossed *for the first
        time* in the current window (the session should be flagged).
        Subsequent blocks within the same window do NOT re-trigger.
        """
        now = datetime.now(UTC)
        cutoff = now.timestamp() - self._window_minutes * 60

        # Prune expired entries
        timestamps = self._blocks[game_id]
        timestamps[:] = [t for t in timestamps if t.timestamp() > cutoff]

        timestamps.append(now)

        if len(timestamps) == self._threshold:
            log.warning(
                "moderation_session_flagged",
                game_id=game_id,
                player_id=player_id,
                blocks_in_window=len(timestamps),
                window_minutes=self._window_minutes,
            )
            return True

        return False

    def reset(self, game_id: str) -> None:
        """Clear tracking state for a game session."""
        self._blocks.pop(game_id, None)
