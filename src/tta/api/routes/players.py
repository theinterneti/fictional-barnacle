"""Player registration and profile routes (plan §2.1–2.3)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import get_current_player, get_pg
from tta.api.errors import AppError
from tta.config import get_settings
from tta.models.player import Player

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
        raise AppError(409, "HANDLE_ALREADY_TAKEN", "Handle is already taken.")

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
            raise AppError(409, "HANDLE_ALREADY_TAKEN", "Handle is already taken.")

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
    message: str = "Account deletion scheduled. Data will be erased within 30 days."


@router.get("/me/data-export", status_code=202)
async def request_data_export(
    player: Player = Depends(get_current_player),
) -> dict:
    """Request an export of all player data (GDPR Art. 20).

    Stub — full async job system deferred to post-v1.
    """
    return {
        "data": DataExportResponse().model_dump(),
        "player_id": str(player.id),
    }


@router.delete("/me", status_code=202)
async def request_account_deletion(
    player: Player = Depends(get_current_player),
) -> dict:
    """Request account and data erasure (GDPR Art. 17).

    Stub — full 30-day erasure pipeline deferred to post-v1.
    """
    return {
        "data": AccountDeletionResponse().model_dump(),
        "player_id": str(player.id),
    }
