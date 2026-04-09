"""Admin authentication dependency (S26 FR-26.01–FR-26.04).

v1 uses a shared admin API key. Every admin request must include
``Authorization: Bearer <key>`` matching ``TTA_ADMIN_API_KEY``.

.. note:: Spec FR-26.02 targets JWT with an ``admin`` role claim.
   The current shared-key scheme is a v1 stepping-stone; swap to
   JWT when an identity provider is integrated.
"""

from __future__ import annotations

import secrets

import structlog
from fastapi import Request

from tta.api.errors import AppError
from tta.errors import ErrorCategory

log = structlog.get_logger()


class AdminIdentity:
    """Represents a verified admin caller."""

    def __init__(self, admin_id: str = "admin") -> None:
        self.admin_id = admin_id


async def require_admin(request: Request) -> AdminIdentity:
    """FastAPI dependency: validate admin API key (FR-26.02–FR-26.04).

    Raises 401 if no token is present, 403 if the token is invalid.
    """
    settings = request.app.state.settings
    expected_key = settings.admin_api_key

    if not expected_key:
        raise AppError(
            ErrorCategory.FORBIDDEN,
            "ADMIN_NOT_CONFIGURED",
            "Admin API is not configured.",
        )

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        log.warning(
            "admin_auth_failed",
            reason="missing_token",
            ip=request.client.host if request.client else "unknown",
            path=request.url.path,
            method=request.method,
        )
        raise AppError(
            ErrorCategory.AUTH_REQUIRED,
            "ADMIN_TOKEN_MISSING",
            "Admin authentication required.",
        )

    token = auth[7:]
    if not secrets.compare_digest(token, expected_key):
        log.warning(
            "admin_auth_failed",
            reason="invalid_token",
            ip=request.client.host if request.client else "unknown",
            path=request.url.path,
            method=request.method,
        )
        raise AppError(
            ErrorCategory.FORBIDDEN,
            "ADMIN_TOKEN_INVALID",
            "Invalid admin credentials.",
        )

    return AdminIdentity()
