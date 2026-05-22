"""Admin API router (S26 — Admin & Operator Tooling).

All endpoints require ``Authorization: Bearer ***`` (FR-26.02–FR-26.04).
Non-GET requests create immutable audit-log entries (FR-26.24).

Routes are organised into concern-specific sub-modules — this module
aggregates them into a single router for backward compatibility:
  §3.2  Player management  → admin_players.py
  §3.3  Game inspection     → admin_games.py
  §3.4  System health       → admin_system.py
  §3.5  Moderation queue    → admin_moderation.py
  §3.6  Rate-limit mgmt     → admin_rate_limits.py
  §3.7  Audit log           → admin_operations.py
  §3.8  Prompts / Jobs      → admin_prompts.py / admin_operations.py
"""

from __future__ import annotations

from fastapi import APIRouter

from tta.api.routes.admin_games import router as _games
from tta.api.routes.admin_moderation import router as _moderation
from tta.api.routes.admin_operations import router as _operations
from tta.api.routes.admin_players import router as _players
from tta.api.routes.admin_prompts import router as _prompts
from tta.api.routes.admin_rate_limits import router as _rate_limits
from tta.api.routes.admin_system import router as _system

router = APIRouter(tags=["admin"])
router.include_router(_players)
router.include_router(_games)
router.include_router(_system)
router.include_router(_moderation)
router.include_router(_rate_limits)
router.include_router(_operations)
router.include_router(_prompts)

# Re-export sub-routers for direct imports
games_router = _games
moderation_router = _moderation
operations_router = _operations
players_router = _players
prompts_router = _prompts
rate_limits_router = _rate_limits
system_router = _system

__all__ = [
    "router",
    "games_router",
    "moderation_router",
    "operations_router",
    "players_router",
    "prompts_router",
    "rate_limits_router",
    "system_router",
]
