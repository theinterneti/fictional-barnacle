"""Shared helpers for admin route modules.

These were inlined in admin.py before the concern decomposition.
"""

from __future__ import annotations

import structlog
from fastapi import Request

from tta.admin.auth import AdminIdentity

log = structlog.get_logger(__name__)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def audit(
    request: Request,
    admin: AdminIdentity,
    *,
    action: str,
    target_type: str,
    target_id: str,
    reason: str = "",
) -> None:
    """Create an immutable audit-log entry for admin actions (FR-26.24)."""
    audit_repo = request.app.state.audit_repo
    if audit_repo is not None:
        await audit_repo.create_and_append(
            admin_id=admin.admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            source_ip=_client_ip(request),
        )
