"""Turn submission and listing routes.

Extracted from games.py during code health decomposition.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import (
    get_current_player,
    get_pg,
    require_consent,
)
from tta.api.errors import AppError
from tta.api.routes.games_commands import (
    _HELP_TEXT,
    _execute_command,
    _parse_slash_command,
)
from tta.api.routes.games_helpers import (
    _get_max_turn_number,
    _get_owned_game,
    _get_turn_count,
)
from tta.errors import ErrorCategory
from tta.models.game import (
    PaginationMeta,
    SubmitTurnRequest,
    TurnAccepted,
)
from tta.models.player import Player
from tta.observability.metrics import TURN_STORAGE_OPS_DURATION
from tta.pipeline.orchestrator import dispatch_pipeline

log = structlog.get_logger(__name__)

router = APIRouter(tags=["games"])


@router.get("/{game_id}/turns")
async def list_turns(
    game_id: UUID,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    """Paginated turn history for a game session."""
    await _get_owned_game(pg, game_id, player)

    # Decode cursor (base64-encoded turn_number)
    cursor_turn: int | None = None
    if cursor is not None:
        try:
            decoded = base64.urlsafe_b64decode(cursor).decode("utf-8")
            cursor_turn = int(decoded)
            if cursor_turn < 1:
                raise ValueError("non-positive cursor")
        except Exception:
            raise AppError(
                ErrorCategory.INPUT_INVALID,
                "INVALID_CURSOR",
                "Malformed pagination cursor.",
            ) from None

    # Build query — status='complete' only (matches get_game_state invariant)
    params: dict = {"sid": game_id, "lim": limit + 1}
    where = "session_id = :sid AND status = 'complete'"
    if cursor_turn is not None:
        where += " AND turn_number < :cursor_tn"
        params["cursor_tn"] = cursor_turn

    result = await pg.execute(
        sa.text(
            f"SELECT id, turn_number, player_input, narrative_output, "
            f"created_at FROM turns "
            f"WHERE {where} "
            f"ORDER BY turn_number DESC LIMIT :lim"
        ),
        params,
    )
    rows = result.all()

    has_more = len(rows) > limit
    items = rows[:limit]

    turns = [
        {
            "turn_id": str(t.id),
            "turn_number": t.turn_number,
            "player_input": t.player_input,
            "narrative_output": t.narrative_output,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in items
    ]

    next_cursor = (
        base64.urlsafe_b64encode(str(items[-1].turn_number).encode()).decode()
        if has_more and items
        else None
    )

    return {
        "data": turns,
        "meta": PaginationMeta(
            next_cursor=next_cursor,
            has_more=has_more,
        ).model_dump(mode="json"),
    }


@router.post(
    "/{game_id}/turns",
    status_code=202,
    response_model=None,
    dependencies=[Depends(require_consent)],
)
async def submit_turn(
    game_id: UUID,
    body: SubmitTurnRequest,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict | JSONResponse:
    """Submit a player turn for processing."""
    settings = request.app.state.settings
    row = await _get_owned_game(pg, game_id, player)

    # FR-27.15: attempt recovery before accepting new turns
    if row.needs_recovery:
        try:
            actual_tc = await _get_turn_count(pg, game_id)
            now_rec = datetime.now(UTC)
            await pg.execute(
                sa.text(
                    "UPDATE game_sessions "
                    "SET turn_count = :tc, needs_recovery = FALSE, "
                    "last_played_at = :now, updated_at = :now "
                    "WHERE id = :gid"
                ),
                {"gid": game_id, "tc": actual_tc, "now": now_rec},
            )
            await pg.commit()
            log.info("recovery_on_submit", game_id=str(game_id))
        except Exception:
            log.warning(
                "recovery_on_submit_failed",
                game_id=str(game_id),
                exc_info=True,
            )

    # Must be active or created
    if row.status not in ("active", "created"):
        raise AppError(
            ErrorCategory.CONFLICT,
            "GAME_NOT_ACTIVE",
            f"Cannot submit turns for a game in '{row.status}' status.",
        )

    # --- Pre-pipeline routing: commands (S01 AC-1.10), validation (S23 AC-23.11) ---
    normalized = body.input.strip()

    # Empty / whitespace-only input → 400 input_invalid (AC-23.11)
    if not normalized:
        raise AppError(
            ErrorCategory.INPUT_INVALID,
            "EMPTY_TURN_INPUT",
            "Turn text cannot be empty.",
        )

    # Slash commands → instant response (no DB row, no pipeline)
    if normalized.startswith("/") and len(normalized) > 1:
        known_cmd = _parse_slash_command(normalized)
        if known_cmd:
            reg = getattr(request.app.state, "template_registry", None)
            rel_svc = getattr(
                getattr(request.app.state, "pipeline_deps", None),
                "relationship_service",
                None,
            )
            llm = getattr(request.app.state, "llm_client", None)
            payload = await _execute_command(
                known_cmd,
                game_id,
                row,
                pg,
                template_registry=reg,
                relationship_service=rel_svc,
                llm_client=llm,
            )
        else:
            payload = {
                "type": "command",
                "command": "unknown",
                "message": (f"Unknown command. {_HELP_TEXT}"),
            }
        return JSONResponse(content={"data": payload}, status_code=200)

    # Concurrent turn check — advisory lock serialises per-game
    await pg.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:gid))"),
        {"gid": str(game_id)},
    )
    in_flight = await pg.execute(
        sa.text(
            "SELECT id, created_at FROM turns "
            "WHERE session_id = :sid AND status = 'processing'"
        ),
        {"sid": game_id},
    )
    stuck = in_flight.one_or_none()
    if stuck is not None:
        stuck_id = stuck.id
        stuck_at = getattr(stuck, "created_at", None)
        if stuck_at is None:
            raise AppError(
                ErrorCategory.CONFLICT,
                "TURN_IN_PROGRESS",
                "A turn is already being processed for this game.",
            )
        if stuck_at.tzinfo is None:
            stuck_at = stuck_at.replace(tzinfo=UTC)
        stuck_age = (datetime.now(UTC) - stuck_at).total_seconds()
        # Recovery: if a turn has been processing longer than 2x the
        # pipeline timeout, mark it failed and allow the next turn.
        timeout = settings.pipeline_timeout_seconds * 2
        if stuck_age > timeout:
            log.warning(
                "stuck_turn_cleared",
                turn_id=str(stuck_id),
                age_seconds=stuck_age,
                game_id=str(game_id),
            )
            await pg.execute(
                sa.text(
                    "UPDATE turns SET status = 'failed', "
                    "completed_at = :now WHERE id = :tid"
                ),
                {"tid": stuck_id, "now": datetime.now(UTC)},
            )
        else:
            raise AppError(
                ErrorCategory.CONFLICT,
                "TURN_IN_PROGRESS",
                "A turn is already being processed for this game.",
            )

    # Idempotency check
    if body.idempotency_key is not None:
        dup = await pg.execute(
            sa.text(
                "SELECT id, turn_number FROM turns "
                "WHERE session_id = :sid AND idempotency_key = :key"
            ),
            {"sid": game_id, "key": body.idempotency_key},
        )
        dup_row = dup.one_or_none()
        if dup_row is not None:
            return {
                "data": TurnAccepted(
                    turn_id=str(dup_row.id),
                    turn_number=dup_row.turn_number,
                    stream_url=f"/api/v1/games/{game_id}/stream",
                ).model_dump(mode="json")
            }

    # Create turn — track storage latency (AC-12.07)
    _storage_t0 = time.monotonic()
    turn_id = uuid4()
    turn_number = await _get_max_turn_number(pg, game_id) + 1
    now = datetime.now(UTC)

    await pg.execute(
        sa.text(
            "INSERT INTO turns "
            "(id, session_id, turn_number, player_input, "
            "idempotency_key, status, created_at) "
            "VALUES (:id, :sid, :tn, :input, :ikey, 'processing', :now)"
        ),
        {
            "id": turn_id,
            "sid": game_id,
            "tn": turn_number,
            "input": body.input,
            "ikey": body.idempotency_key,
            "now": now,
        },
    )

    # Transition created → active on first turn; always update last_played_at
    if row.status == "created":
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET status = 'active', "
                "last_played_at = :now, updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "now": now},
        )
    else:
        await pg.execute(
            sa.text(
                "UPDATE game_sessions SET last_played_at = :now, "
                "updated_at = :now WHERE id = :id"
            ),
            {"id": game_id, "now": now},
        )

    await pg.commit()
    TURN_STORAGE_OPS_DURATION.labels(operation="turn_insert").observe(
        time.monotonic() - _storage_t0
    )

    # Dispatch pipeline as background task
    game_state = row.world_seed if row.world_seed else {}
    if isinstance(game_state, str):
        game_state = json.loads(game_state)
    log.info(
        "turn_dispatch_task_created",
        game_id=str(game_id),
        turn_id=str(turn_id),
        turn_number=turn_number,
        input_len=len(normalized),
        game_state_keys=(
            sorted(game_state.keys()) if isinstance(game_state, dict) else []
        ),
        game_state_size=(
            len(json.dumps(game_state, default=str)) if game_state is not None else 0
        ),
    )
    asyncio.create_task(
        dispatch_pipeline(
            app_state=request.app.state,
            game_id=game_id,
            turn_id=turn_id,
            turn_number=turn_number,
            player_input=body.input,
            game_state=game_state,
            session_cost_usd=float(getattr(row, "total_cost_usd", 0) or 0),
            player_id=str(player.id),
        )
    )

    return {
        "data": TurnAccepted(
            turn_id=str(turn_id),
            turn_number=turn_number,
            stream_url=f"/api/v1/games/{game_id}/stream",
        ).model_dump(mode="json")
    }
