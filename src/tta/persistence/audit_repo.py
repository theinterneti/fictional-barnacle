"""Append-only audit log repository (S26 FR-26.24–FR-26.26).

Only INSERT and SELECT operations are exposed — no UPDATE or DELETE.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa

from tta.models.audit import AuditLogEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession


class AuditLogRepository:
    """Append-only audit log backed by PostgreSQL."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def append(self, entry: AuditLogEntry) -> AuditLogEntry:
        """Insert an audit log entry. Returns the persisted entry."""
        async with self._sf() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO audit_log "
                    "(id, admin_id, action, target_type, target_id, "
                    "reason, source_ip, timestamp) "
                    "VALUES (:id, :admin_id, :action, :target_type, "
                    ":target_id, :reason, :source_ip, :ts)"
                ),
                {
                    "id": entry.id,
                    "admin_id": entry.admin_id,
                    "action": entry.action,
                    "target_type": entry.target_type,
                    "target_id": entry.target_id,
                    "reason": entry.reason,
                    "source_ip": entry.source_ip,
                    "ts": entry.timestamp,
                },
            )
            await session.commit()
            return entry

    @staticmethod
    def encode_cursor(ts: datetime, entry_id: UUID) -> str:
        """Encode a ``(timestamp, id)`` pair into an opaque cursor."""
        raw = f"{ts.isoformat()}|{entry_id}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @staticmethod
    def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
        """Decode an opaque cursor into ``(timestamp, id)``."""
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), UUID(id_str)

    async def query(
        self,
        *,
        admin_id: str | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> list[AuditLogEntry]:
        """Query audit log with optional filters (FR-26.25).

        Returns at most *limit* entries (max 1000) ordered by
        timestamp descending.  Cursor-based pagination uses a
        composite ``(timestamp, id)`` token encoded as a base64
        string, so ordering is deterministic.
        """
        limit = min(limit, 1000)
        clauses: list[str] = []
        params: dict[str, object] = {"lim": limit}

        if admin_id:
            clauses.append("admin_id = :admin_id")
            params["admin_id"] = admin_id
        if action:
            clauses.append("action = :action")
            params["action"] = action
        if target_type:
            clauses.append("target_type = :target_type")
            params["target_type"] = target_type
        if target_id:
            clauses.append("target_id = :target_id")
            params["target_id"] = target_id
        if from_ts:
            clauses.append("timestamp >= :from_ts")
            params["from_ts"] = from_ts
        if to_ts:
            clauses.append("timestamp <= :to_ts")
            params["to_ts"] = to_ts
        if cursor:
            cur_ts, cur_id = self.decode_cursor(cursor)
            clauses.append("(timestamp, id) < (:cur_ts, :cur_id)")
            params["cur_ts"] = cur_ts
            params["cur_id"] = cur_id

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            f"SELECT id, admin_id, action, target_type, target_id, "
            f"reason, source_ip, timestamp "
            f"FROM audit_log {where} "
            f"ORDER BY timestamp DESC, id DESC LIMIT :lim"
        )

        async with self._sf() as session:
            result = await session.execute(sa.text(sql), params)
            rows = result.all()

        return [
            AuditLogEntry(
                id=r.id,
                admin_id=r.admin_id,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                reason=r.reason,
                source_ip=r.source_ip,
                timestamp=r.timestamp,
            )
            for r in rows
        ]

    async def create_and_append(
        self,
        *,
        admin_id: str,
        action: str,
        target_type: str,
        target_id: str,
        reason: str = "",
        source_ip: str = "",
    ) -> AuditLogEntry:
        """Convenience: build + persist an audit entry."""
        entry = AuditLogEntry(
            id=uuid4(),
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            source_ip=source_ip,
        )
        return await self.append(entry)
