"""Moderation record persistence (S24 FR-24.09, FR-24.13–FR-24.14).

Stores every moderation action to a dedicated ``moderation_records``
table.  Raw content lives exclusively here — general logs reference
``moderation_id`` and ``content_hash`` only.
"""

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.moderation.models import ModerationRecord

log = structlog.get_logger()


class ModerationRecorder:
    """Persists ``ModerationRecord`` objects to PostgreSQL."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def save(self, record: ModerationRecord) -> None:
        """Insert a moderation record into the database."""
        try:
            async with self._sf() as session:
                await session.execute(
                    sa.text(
                        "INSERT INTO moderation_records "
                        "(moderation_id, turn_id, game_id, player_id, "
                        " stage, content_hash, content, verdict, "
                        " category, confidence, reason, timestamp) "
                        "VALUES "
                        "(:moderation_id, :turn_id, :game_id, :player_id, "
                        " :stage, :content_hash, :content, :verdict, "
                        " :category, :confidence, :reason, :timestamp)"
                    ),
                    {
                        "moderation_id": record.moderation_id,
                        "turn_id": record.turn_id,
                        "game_id": record.game_id,
                        "player_id": record.player_id,
                        "stage": record.stage,
                        "content_hash": record.content_hash,
                        "content": record.content,
                        "verdict": record.verdict.value,
                        "category": record.category.value,
                        "confidence": record.confidence,
                        "reason": record.reason,
                        "timestamp": record.timestamp,
                    },
                )
                await session.commit()
        except Exception:
            log.error(
                "moderation_record_save_failed",
                moderation_id=record.moderation_id,
                exc_info=True,
            )
