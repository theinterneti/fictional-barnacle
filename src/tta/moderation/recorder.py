"""Moderation record persistence (S24 FR-24.09, FR-24.13–FR-24.14).

Stores every moderation action to a dedicated ``moderation_records``
table.  Raw content lives exclusively here — general logs reference
``moderation_id`` and ``content_hash`` only.
"""

from __future__ import annotations

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

    # ------------------------------------------------------------------
    # Query / update helpers for admin moderation queue (S26 §3.5)
    # ------------------------------------------------------------------

    async def query(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        game_id: str | None = None,
        player_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Return moderation records with optional filters.

        Only records with verdict ``flag`` or ``block`` are typically
        interesting for the admin queue.  Cursor-based pagination uses
        ``moderation_id`` (UUID, lexicographic ordering is fine for
        paging — we ORDER BY timestamp DESC, moderation_id DESC).
        """
        limit = min(max(1, limit), 100)
        clauses: list[str] = ["1=1"]
        params: dict[str, object] = {"lim": limit}

        if status:
            clauses.append("verdict = :verdict")
            params["verdict"] = status
        if category:
            clauses.append("category = :category")
            params["category"] = category
        if game_id:
            clauses.append("game_id = :game_id")
            params["game_id"] = game_id
        if player_id:
            clauses.append("player_id = :player_id")
            params["player_id"] = player_id
        if cursor:
            clauses.append(
                "(timestamp, moderation_id::text) < "
                "((SELECT timestamp FROM moderation_records "
                "  WHERE moderation_id::text = :cursor), :cursor)"
            )
            params["cursor"] = cursor

        where = " AND ".join(clauses)
        sql = (
            f"SELECT moderation_id, turn_id, game_id, player_id, "
            f"  stage, content_hash, verdict, category, confidence, "
            f"  reason, timestamp "
            f"FROM moderation_records WHERE {where} "
            f"ORDER BY timestamp DESC, moderation_id DESC "
            f"LIMIT :lim"
        )
        try:
            async with self._sf() as session:
                result = await session.execute(sa.text(sql), params)
                rows = result.mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            log.error("moderation_query_failed", exc_info=True)
            return []

    async def update_verdict(self, moderation_id: str, new_verdict: str) -> bool:
        """Update the verdict of an existing moderation record.

        Returns ``True`` if a row was updated.
        """
        try:
            async with self._sf() as session:
                result = await session.execute(
                    sa.text(
                        "UPDATE moderation_records SET verdict = :v "
                        "WHERE moderation_id::text = :mid"
                    ),
                    {"v": new_verdict, "mid": moderation_id},
                )
                await session.commit()
                return result.rowcount > 0  # type: ignore[union-attr]
        except Exception:
            log.error(
                "moderation_update_verdict_failed",
                moderation_id=moderation_id,
                exc_info=True,
            )
            return False
