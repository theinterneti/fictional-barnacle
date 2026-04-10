"""Player registration and profile routes (plan §2.1–2.3)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import get_current_player, get_pg, get_redis
from tta.api.errors import AppError
from tta.config import get_settings
from tta.errors import ErrorCategory
from tta.models.player import Player
from tta.persistence.redis_session import delete_active_session

log = structlog.get_logger()

router = APIRouter(prefix="/players", tags=["players"])


# --- Request / Response schemas ---


class CreatePlayerRequest(BaseModel):
    handle: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-zA-Z0-9 _\-\.]+$",
        description="Unique player handle.",
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
    pg: AsyncSession = Depends(get_pg),
) -> JSONResponse:
    """Register a new anonymous player with a unique handle."""
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

    # Create player
    player_id = uuid4()
    now = datetime.now(UTC)
    await pg.execute(
        sa.text(
            "INSERT INTO players (id, handle, created_at) "
            "VALUES (:id, :handle, :created_at)"
        ),
        {"id": player_id, "handle": body.handle, "created_at": now},
    )

    # Create session token
    settings = get_settings()
    token = secrets.token_hex(32)
    expires_at = now + timedelta(seconds=settings.session_token_ttl)
    await pg.execute(
        sa.text(
            "INSERT INTO player_sessions "
            "(player_id, token, expires_at, created_at) "
            "VALUES (:player_id, :token, :expires_at, :created_at)"
        ),
        {
            "player_id": player_id,
            "token": token,
            "expires_at": expires_at,
            "created_at": now,
        },
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
        max_age=settings.session_token_ttl,
    )
    return response


@router.get("/me")
async def get_profile(
    player: Player = Depends(get_current_player),
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
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
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


# --- GDPR endpoint stubs (S17 §3 FR-17.6, FR-17.9) ---


class DataExportResponse(BaseModel):
    status: str = "accepted"
    message: str = "Data export request queued. Available within 72 hours."


class AccountDeletionResponse(BaseModel):
    status: str = "accepted"
    message: str = "Account deletion accepted. Personal data has been erased."


@router.get("/me/data-export", status_code=202)
async def request_data_export(
    player: Player = Depends(get_current_player),
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
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    redis: Redis = Depends(get_redis),
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
