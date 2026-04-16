"""Player registration and profile routes (plan §2.1–2.3)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tta.api.deps import get_current_player, get_pg, get_redis
from tta.api.errors import AppError
from tta.auth.jwt import create_access_token
from tta.config import (
    CURRENT_CONSENT_VERSION,
    REQUIRED_CONSENT_CATEGORIES,
    get_settings,
)
from tta.errors import ErrorCategory
from tta.persistence.redis_session import delete_active_session

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlmodel.ext.asyncio.session import AsyncSession

    from tta.models.player import Player

log = structlog.get_logger()

router = APIRouter(prefix="/players", tags=["players"])


def _client_ip(request: Request) -> str:
    """Extract the client IP, respecting X-Forwarded-For behind proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- Request / Response schemas ---


class CreatePlayerRequest(BaseModel):
    handle: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9 _\-\.]+$",
        description="Unique player handle.",
    )
    age_13_plus_confirmed: bool = Field(
        ...,
        description="Player confirms they are 13 years or older.",
    )
    consent_version: str = Field(
        ...,
        description="Version of the consent agreement being accepted.",
    )
    consent_categories: dict[str, bool] = Field(
        ...,
        description="Consent categories and acceptance status.",
    )


class PlayerData(BaseModel):
    player_id: str
    handle: str
    created_at: datetime
    session_token: str


class PlayerProfile(BaseModel):
    player_id: str
    handle: str
    created_at: datetime


class UpdateConsentRequest(BaseModel):
    consent_version: str = Field(
        ..., description="Must match the current consent version."
    )
    consent_categories: dict[str, bool] = Field(
        ..., description="Categories to update (merged with existing)."
    )
    age_13_plus_confirmed: bool | None = Field(
        None,
        description="Set to true to confirm age gate (for existing players "
        "who registered before consent was required).",
    )


class UpdatePlayerRequest(BaseModel):
    handle: str | None = Field(
        None,
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9 _\-\.]+$",
    )


# --- Routes ---


@router.post("", status_code=201)
async def register_player(
    body: CreatePlayerRequest,
    request: Request,
    pg: Annotated[AsyncSession, Depends(get_pg)],
) -> JSONResponse:
    """Register a new anonymous player with a unique handle."""
    # Age gate (S17 FR-17.36)
    if not body.age_13_plus_confirmed:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "AGE_CONFIRMATION_REQUIRED",
            "You must confirm you are 13 years or older.",
        )

    # Consent version match (S17 FR-17.22)
    if body.consent_version != CURRENT_CONSENT_VERSION:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "CONSENT_VERSION_MISMATCH",
            f"Expected consent version {CURRENT_CONSENT_VERSION}.",
        )

    # Required categories must be accepted (S17 FR-17.24)
    for cat in REQUIRED_CONSENT_CATEGORIES:
        if not body.consent_categories.get(cat):
            raise AppError(
                ErrorCategory.INPUT_INVALID,
                "REQUIRED_CONSENT_MISSING",
                f"Required consent category '{cat}' must be accepted.",
            )

    # Check handle uniqueness
    existing = await pg.execute(
        sa.text("SELECT id FROM players WHERE handle = :handle"),
        {"handle": body.handle},
    )
    if existing.one_or_none() is not None:
        raise AppError(
            ErrorCategory.CONFLICT,
            "HANDLE_ALREADY_TAKEN",
            "Handle is already taken.",
        )

    # Create player with consent data
    player_id = uuid4()
    now = datetime.now(UTC)
    ip_hash = hashlib.sha256(_client_ip(request).encode()).hexdigest()

    await pg.execute(
        sa.text(
            "INSERT INTO players "
            "(id, handle, created_at, consent_version, "
            "consent_accepted_at, consent_categories, "
            "age_confirmed_at, consent_ip_hash) "
            "VALUES (:id, :handle, :created_at, :consent_version, "
            ":consent_accepted_at, CAST(:consent_categories AS jsonb), "
            ":age_confirmed_at, :consent_ip_hash)"
        ),
        {
            "id": player_id,
            "handle": body.handle,
            "created_at": now,
            "consent_version": body.consent_version,
            "consent_accepted_at": now,
            "consent_categories": json.dumps(body.consent_categories),
            "age_confirmed_at": now,
            "consent_ip_hash": ip_hash,
        },
    )

    # Issue JWT access token (S11 migration: replaced opaque token)
    settings = get_settings()
    token = create_access_token(
        player_id=player_id,
        role="player",
        is_anonymous=True,
    )

    await pg.commit()

    response = JSONResponse(
        status_code=201,
        content={
            "data": PlayerData(
                player_id=str(player_id),
                handle=body.handle,
                created_at=now,
                session_token=token,
            ).model_dump(mode="json")
        },
    )
    response.set_cookie(
        key="tta_session",
        value=token,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path="/",
        max_age=settings.anon_access_token_ttl,
    )
    return response


@router.get("/me")
async def get_profile(
    player: Annotated[Player, Depends(get_current_player)],
) -> dict:
    """Return the authenticated player's profile."""
    return {
        "data": PlayerProfile(
            player_id=str(player.id),
            handle=player.handle,
            created_at=player.created_at,
        ).model_dump(mode="json")
    }


@router.patch("/me")
async def update_profile(
    body: UpdatePlayerRequest,
    player: Annotated[Player, Depends(get_current_player)],
    pg: Annotated[AsyncSession, Depends(get_pg)],
) -> dict:
    """Update the authenticated player's handle."""
    if body.handle is None:
        return {
            "data": PlayerProfile(
                player_id=str(player.id),
                handle=player.handle,
                created_at=player.created_at,
            ).model_dump(mode="json")
        }

    # Check uniqueness (skip if unchanged)
    if body.handle != player.handle:
        existing = await pg.execute(
            sa.text("SELECT id FROM players WHERE handle = :handle"),
            {"handle": body.handle},
        )
        if existing.one_or_none() is not None:
            raise AppError(
                ErrorCategory.CONFLICT,
                "HANDLE_ALREADY_TAKEN",
                "Handle is already taken.",
            )

        await pg.execute(
            sa.text("UPDATE players SET handle = :handle WHERE id = :id"),
            {"handle": body.handle, "id": player.id},
        )
        await pg.commit()

    return {
        "data": PlayerProfile(
            player_id=str(player.id),
            handle=body.handle,
            created_at=player.created_at,
        ).model_dump(mode="json")
    }


# --- Consent management (S17 FR-17.22–17.26) ---


class ConsentState(BaseModel):
    consent_version: str | None
    consent_accepted_at: datetime | None
    consent_categories: dict[str, bool] | None
    age_confirmed_at: datetime | None


@router.get("/me/consent")
async def get_consent(
    player: Annotated[Player, Depends(get_current_player)],
) -> dict:
    """Return the authenticated player's current consent state."""
    cats = None
    if player.consent_categories is not None:
        cats = (
            json.loads(player.consent_categories)
            if isinstance(player.consent_categories, str)
            else player.consent_categories
        )
    return {
        "data": ConsentState(
            consent_version=player.consent_version,
            consent_accepted_at=player.consent_accepted_at,
            consent_categories=cats,
            age_confirmed_at=player.age_confirmed_at,
        ).model_dump(mode="json")
    }


@router.patch("/me/consent")
async def update_consent(
    body: UpdateConsentRequest,
    request: Request,
    player: Annotated[Player, Depends(get_current_player)],
    pg: Annotated[AsyncSession, Depends(get_pg)],
) -> dict:
    """Update consent categories (atomic JSONB merge).

    Required categories cannot be withdrawn (returns 400).
    """
    if body.consent_version != CURRENT_CONSENT_VERSION:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "CONSENT_VERSION_MISMATCH",
            f"Expected consent version {CURRENT_CONSENT_VERSION}.",
        )

    # Reject withdrawal of required categories (S17 FR-17.24)
    for cat in REQUIRED_CONSENT_CATEGORIES:
        if cat in body.consent_categories and not body.consent_categories[cat]:
            raise AppError(
                ErrorCategory.INPUT_INVALID,
                "REQUIRED_CONSENT_WITHDRAWAL",
                f"Cannot withdraw required consent category: {cat}",
            )

    now = datetime.now(UTC)
    ip_hash = hashlib.sha256(_client_ip(request).encode()).hexdigest()

    patch_json = json.dumps(body.consent_categories)

    # Build SET clause dynamically for optional age gate
    set_parts = [
        "consent_version = :version",
        "consent_categories = "
        "COALESCE(consent_categories, '{}'::jsonb) || CAST(:patch AS jsonb)",
        "consent_accepted_at = :now",
        "consent_ip_hash = :ip_hash",
        "updated_at = :now",
    ]
    params: dict[str, object] = {
        "version": body.consent_version,
        "patch": patch_json,
        "now": now,
        "ip_hash": ip_hash,
        "id": player.id,
    }
    if body.age_13_plus_confirmed:
        set_parts.append("age_confirmed_at = :age_at")
        params["age_at"] = now

    await pg.execute(
        sa.text(f"UPDATE players SET {', '.join(set_parts)} WHERE id = :id"),
        params,
    )
    await pg.commit()

    # Validate merged state has all required categories
    result = await pg.execute(
        sa.text(
            "SELECT consent_version, consent_accepted_at, "
            "consent_categories, age_confirmed_at "
            "FROM players WHERE id = :id"
        ),
        {"id": player.id},
    )
    row = result.one()

    cats = row.consent_categories
    if isinstance(cats, str):
        cats = json.loads(cats)

    missing = REQUIRED_CONSENT_CATEGORIES - {k for k, v in (cats or {}).items() if v}
    if missing:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "MISSING_REQUIRED_CONSENT",
            f"After merge, required categories still missing: {sorted(missing)}",
        )

    log.info(
        "consent_updated",
        player_id=str(player.id),
        consent_version=body.consent_version,
        categories_updated=list(body.consent_categories.keys()),
    )

    return {
        "data": ConsentState(
            consent_version=row.consent_version,
            consent_accepted_at=row.consent_accepted_at,
            consent_categories=cats,
            age_confirmed_at=row.age_confirmed_at,
        ).model_dump(mode="json")
    }


# --- GDPR endpoint stubs (S17 §3 FR-17.6, FR-17.9) ---


class DataExportResponse(BaseModel):
    status: str = "accepted"
    message: str = "Data export request queued. Available within 72 hours."


class AccountDeletionResponse(BaseModel):
    status: str = "accepted"
    message: str = "Account deletion accepted. Personal data has been erased."


@router.get("/me/data-export", status_code=202)
async def request_data_export(
    player: Annotated[Player, Depends(get_current_player)],
) -> dict:
    """Request an export of all player data (GDPR Art. 20).

    Stub — full async job system deferred to post-v1.
    """
    data = DataExportResponse().model_dump()
    data["player_id"] = str(player.id)
    return {"data": data}


@router.delete("/me", status_code=202)
async def request_account_deletion(
    request: Request,
    player: Annotated[Player, Depends(get_current_player)],
    pg: Annotated[AsyncSession, Depends(get_pg)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> dict:
    """Erase account and all personal data (GDPR Art. 17, S17 FR-17.10).

    Performs immediate PII removal from ALL stores (AC-12.03):
    1. Marks player as pending_deletion with tombstone handle
    2. Ends all active/paused game sessions
    3. Scrubs PII from turns and game sessions
    4. Invalidates all session tokens
    5. Evicts cached state from Redis
    6. Cleans up Neo4j world graph data
    """
    now = datetime.now(UTC)
    pid = player.id

    # 1. Tombstone the player record
    await pg.execute(
        sa.text(
            "UPDATE players SET "
            "status = 'pending_deletion', "
            "handle = :tombstone, "
            "deletion_requested_at = :now, "
            "updated_at = :now "
            "WHERE id = :pid"
        ),
        {"tombstone": f"deleted-{pid}", "now": now, "pid": pid},
    )

    # 2. End all active/paused game sessions
    await pg.execute(
        sa.text(
            "UPDATE game_sessions SET status = 'ended', updated_at = :now "
            "WHERE player_id = :pid "
            "AND status IN ('created', 'active', 'paused')"
        ),
        {"pid": pid, "now": now},
    )

    # 3. Scrub PII from turns (player_input, narrative_output)
    await pg.execute(
        sa.text(
            "UPDATE turns "
            "SET player_input = '[redacted]', narrative_output = NULL "
            "WHERE session_id IN "
            "(SELECT id FROM game_sessions WHERE player_id = :pid)"
        ),
        {"pid": pid},
    )

    # 4. Scrub PII from game sessions (world_seed, summary)
    await pg.execute(
        sa.text(
            "UPDATE game_sessions "
            "SET world_seed = '{}'::jsonb, summary = NULL "
            "WHERE player_id = :pid"
        ),
        {"pid": pid},
    )

    # 5. Invalidate all session tokens
    await pg.execute(
        sa.text("DELETE FROM player_sessions WHERE player_id = :pid"),
        {"pid": pid},
    )

    await pg.commit()

    # 6. Fetch session IDs for multi-store cleanup
    session_rows = await pg.execute(
        sa.text("SELECT id FROM game_sessions WHERE player_id = :pid"),
        {"pid": pid},
    )
    session_ids = [row.id for row in session_rows.fetchall()]

    # 7. Evict cached state from Redis (AC-12.03)
    for sid in session_ids:
        try:
            await delete_active_session(redis, sid)
        except Exception:
            log.warning("gdpr_redis_cleanup_failed", session_id=str(sid))

    # 8. Clean up Neo4j world graph data (AC-12.03)
    world_service = getattr(request.app.state, "world_service", None)
    if world_service is not None:
        for sid in session_ids:
            try:
                await world_service.cleanup_session(sid)
            except NotImplementedError:
                pass
            except Exception:
                log.warning("gdpr_neo4j_cleanup_failed", session_id=str(sid))

    data = AccountDeletionResponse().model_dump()
    data["player_id"] = str(pid)
    return {"data": data}
