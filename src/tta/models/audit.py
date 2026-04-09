"""Audit log model (S26 FR-26.24–FR-26.26).

Every non-GET admin request creates an immutable audit-log entry.
Entries are append-only — no UPDATE or DELETE is ever performed.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AuditLogEntry(BaseModel):
    """Immutable audit log record."""

    id: UUID = Field(default_factory=uuid4)
    admin_id: str
    action: str
    target_type: str
    target_id: str
    reason: str = ""
    source_ip: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
