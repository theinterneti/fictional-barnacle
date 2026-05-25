"""Game session routes (plan §2.4–2.12)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, Query, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.api.deps import (
    get_current_player,
    get_pg,
    require_anonymous_game_limit,
)
from tta.api.errors import AppError
from tta.api.routes.games_helpers import (
    _count_active_games,
    _get_owned_game,
    _get_turn_count,
)
from tta.api.routes.games_lifecycle import router as _lifecycle
from tta.api.routes.games_stream import router as _stream
from tta.api.routes.games_turns import router as _turns
from tta.config import Settings, get_settings
from tta.errors import ErrorCategory
from tta.models.game import (
    CreateGameRequest,
    GameData,
    GameStatus,
    GameSummary,
    PaginationMeta,
)
from tta.models.player import Player
from tta.models.world import (
    WorldSeed,
)
from tta.observability.metrics import (
    SESSIONS_ACTIVE,
)

log = structlog.get_logger()

router = APIRouter(prefix="/games", tags=["games"])


_GENESIS_SEED_KEYS = {
    "tone",
    "tech_level",
    "magic_presence",
    "world_scale",
    "player_position",
    "power_source",
    "defining_detail",
    "character_name",
    "character_concept",
}


router.include_router(_lifecycle)
router.include_router(_turns)
router.include_router(_stream)
# Map internal states to S27 public states (active | completed | abandoned)
_PUBLIC_STATE_MAP: dict[str, str] = {
    "created": "active",
    "active": "active",
    "paused": "active",
    "completed": "completed",
    "ended": "completed",
    "expired": "abandoned",
    "abandoned": "abandoned",
}


def _string_pref(preferences: dict[str, str | list[str]], key: str) -> str | None:
    value = preferences.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _traits_pref(preferences: dict[str, str | list[str]]) -> list[str]:
    raw = preferences.get("traits")
    if isinstance(raw, list):
        return [trait for trait in raw if isinstance(trait, str) and trait.strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw]
    return []


# --- Routes ---


@router.post("", status_code=201, dependencies=[Depends(require_anonymous_game_limit)])
async def create_game(
    body: CreateGameRequest,
    request: Request,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Create a new game session, optionally running world genesis."""
    settings: Settings = request.app.state.settings
    active_count = await _count_active_games(pg, player.id)
    if active_count >= settings.max_active_games:
        raise AppError(
            ErrorCategory.CONFLICT,
            "MAX_GAMES_REACHED",
            f"Maximum of {settings.max_active_games} active games reached.",
        )

    game_id = uuid4()
    now = datetime.now(UTC)
    pref = body.preferences
    seed_preferences = {
        key: value
        for key, value in pref.items()
        if key in _GENESIS_SEED_KEYS and isinstance(value, str)
    }
    world_seed_json = {
        "world_id": body.world_id,
        "preferences": seed_preferences,
    }

    # Persist game row first — game exists even if genesis fails (S01)
    await pg.execute(
        sa.text(
            "INSERT INTO game_sessions "
            "(id, player_id, status, world_seed, "
            "created_at, updated_at, last_played_at) "
            "VALUES (:id, :pid, :status, "
            "cast(:seed AS jsonb), :now, :now, :now)"
        ),
        {
            "id": game_id,
            "pid": player.id,
            "status": GameStatus.created.value,
            "seed": json.dumps(world_seed_json),
            "now": now,
        },
    )
    await pg.commit()
    SESSIONS_ACTIVE.inc()

    # --- Genesis (best-effort) ---
    narrative_intro: str | None = None
    try:
        registry = request.app.state.template_registry

        # Select template: explicit key or best-match by preferences
        if body.world_id:
            template = registry.get(body.world_id)
        else:
            template = registry.select_by_preferences(body.preferences)

        # Build WorldSeed with selected template + preferences
        seed = WorldSeed(
            template=template,
            tone=_string_pref(pref, "tone"),
            tech_level=_string_pref(pref, "tech_level"),
            magic_presence=_string_pref(pref, "magic_presence"),
            world_scale=_string_pref(pref, "world_scale"),
            player_position=_string_pref(pref, "player_position"),
            power_source=_string_pref(pref, "power_source"),
            defining_detail=_string_pref(pref, "defining_detail"),
            character_name=_string_pref(pref, "character_name"),
            character_concept=_string_pref(pref, "character_concept"),
        )

        from tta.genesis.genesis_lite import run_genesis_lite

        abort_seconds = settings.latency_budget_abort_ms / 1000.0
        genesis_budget_seconds = max(
            0.05,
            min(
                settings.pipeline_timeout_seconds,
                abort_seconds * 0.8,
            ),
        )
        result = await asyncio.wait_for(
            run_genesis_lite(
                session_id=game_id,
                player_id=player.id,
                world_seed=seed,
                llm=request.app.state.llm_client,
                world_service=request.app.state.world_service,
            ),
            timeout=genesis_budget_seconds,
        )
        narrative_intro = result.narrative_intro

        # Persist genesis result alongside original seed
        world_seed_json["genesis"] = {
            "world_id": result.world_id,
            "player_location_id": result.player_location_id,
            "template_key": result.template_key,
            "narrative_intro": result.narrative_intro,
            "genesis_elements": result.genesis_elements,
        }
        await pg.execute(
            sa.text(
                "UPDATE game_sessions "
                "SET world_seed = cast(:seed AS jsonb), "
                "updated_at = :now "
                "WHERE id = :gid"
            ),
            {
                "seed": json.dumps(world_seed_json),
                "now": datetime.now(UTC),
                "gid": game_id,
            },
        )
        await pg.commit()
        log.info("genesis_complete", game_id=str(game_id))
    except asyncio.CancelledError:
        log.warning(
            "genesis_cancelled_graceful_degradation",
            game_id=str(game_id),
        )
    except Exception:
        log.warning(
            "genesis_failed_graceful_degradation",
            game_id=str(game_id),
            exc_info=True,
        )

    return {
        "data": GameData(
            game_id=str(game_id),
            player_id=str(player.id),
            status=GameStatus.active.value,
            turn_count=0,
            narrative_intro=narrative_intro,
            character_name=_string_pref(pref, "character_name"),
            character_traits=_traits_pref(pref),
            created_at=now,
            updated_at=now,
            last_played_at=now,
        ).model_dump(mode="json")
    }


@router.get("")
async def list_games(
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
    status: str | None = Query(None),
    cursor: datetime | None = Query(None),
    limit: int | None = Query(None, ge=1, le=50),
) -> dict:
    """List the authenticated player's games (S27 FR-27.08–FR-27.11)."""
    settings: Settings = get_settings()
    effective_limit = min(
        limit or settings.game_listing_default_size,
        settings.game_listing_max_size,
    )

    params: dict = {"pid": player.id, "lim": effective_limit + 1}
    where_clauses = [
        "gs.player_id = :pid",
        "gs.deleted_at IS NULL",
    ]

    if status is not None:
        where_clauses.append("gs.status = :status")
        params["status"] = status
    else:
        # Exclude abandoned games by default (S27 FR-27.10)
        where_clauses.append("gs.status != 'abandoned'")

    if cursor is not None:
        where_clauses.append("gs.last_played_at < :cursor")
        params["cursor"] = cursor

    where = " AND ".join(where_clauses)
    result = await pg.execute(
        sa.text(
            f"SELECT gs.id, gs.player_id, gs.status, gs.world_seed, "  # noqa: S608
            f"gs.title, gs.summary, "
            f"COALESCE(tc.cnt, 0) AS turn_count, "
            f"gs.created_at, gs.updated_at, gs.last_played_at "
            f"FROM game_sessions gs "
            f"LEFT JOIN ("
            f"  SELECT session_id, count(*) AS cnt "
            f"  FROM turns WHERE status = 'complete' "
            f"  GROUP BY session_id"
            f") tc ON tc.session_id = gs.id "
            f"WHERE {where} "
            f"ORDER BY gs.last_played_at DESC NULLS LAST "
            f"LIMIT :lim"
        ),
        params,
    )
    rows = result.all()
    has_more = len(rows) > effective_limit
    items = rows[:effective_limit]

    games = [
        GameSummary(
            game_id=str(r.id),
            status=_PUBLIC_STATE_MAP.get(r.status or "", r.status or ""),
            turn_count=r.turn_count or 0,
            title=r.title,
            summary=r.summary,
            created_at=r.created_at,
            updated_at=r.updated_at,
            last_played_at=r.last_played_at,
        ).model_dump(mode="json")
        for r in items
    ]

    next_cursor = (
        items[-1].last_played_at.isoformat()
        if has_more and items and items[-1].last_played_at
        else None
    )

    return {
        "data": games,
        "meta": PaginationMeta(
            next_cursor=next_cursor,
            has_more=has_more,
        ).model_dump(mode="json"),
    }


@router.get("/{game_id}")
async def get_game_state(
    game_id: UUID,
    player: Player = Depends(get_current_player),
    pg: AsyncSession = Depends(get_pg),
) -> dict:
    """Get full game state for a session."""
    row = await _get_owned_game(pg, game_id, player)
    turn_count = await _get_turn_count(pg, game_id)

    # Recent turns
    turns_result = await pg.execute(
        sa.text(
            "SELECT id, turn_number, player_input, narrative_output, "
            "created_at FROM turns "
            "WHERE session_id = :sid AND status = 'complete' "
            "ORDER BY turn_number DESC LIMIT 10"
        ),
        {"sid": game_id},
    )
    recent = [
        {
            "turn_id": str(t.id),
            "turn_number": t.turn_number,
            "player_input": t.player_input,
            "narrative_output": t.narrative_output,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in reversed(turns_result.all())
    ]

    # Check for in-flight turn
    processing_result = await pg.execute(
        sa.text(
            "SELECT id FROM turns "
            "WHERE session_id = :sid AND status = 'processing' "
            "LIMIT 1"
        ),
        {"sid": game_id},
    )
    processing_row = processing_result.one_or_none()

    return {
        "data": {
            "game_id": str(row.id),
            "player_id": str(row.player_id),
            "status": row.status,
            "turn_count": turn_count,
            "title": row.title,
            "summary": row.summary,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "last_played_at": (
                row.last_played_at.isoformat() if row.last_played_at else None
            ),
            "recent_turns": recent,
            "processing_turn": (str(processing_row.id) if processing_row else None),
        }
    }


# ── Re-exports for backward compatibility ──
# Symbols extracted to games_commands.py
from tta.api.routes.games_commands import (  # noqa: E402, F401
    _KNOWN_COMMANDS,
    _build_character_response,
    _build_relationships_response,
    _dimension_label,
    _execute_end_command,
    _generate_epilogue,
)
