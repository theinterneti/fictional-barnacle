"""Admin API router (S26 — Admin & Operator Tooling).

All endpoints require ``Authorization: Bearer ***`` (FR-26.02–FR-26.04).
Non-GET requests create immutable audit-log entries (FR-26.24).

Routes are organised into concern-specific sub-modules:
  §3.2  Player management  → admin_players.py
  §3.3  Game inspection     → admin_games.py
  §3.4  System health       → admin_system.py
  §3.5  Moderation queue    → admin_moderation.py
  §3.6  Rate-limit mgmt     → admin_rate_limits.py
  §3.7  Audit log           → admin_operations.py
  §3.8  Prompts / Jobs      → admin_prompts.py / admin_operations.py

This module re-exports all sub-routers for backward compatibility.
"""

from __future__ import annotations

from tta.api.routes.admin_games import router as games_router
from tta.api.routes.admin_moderation import router as moderation_router
from tta.api.routes.admin_operations import router as operations_router
from tta.api.routes.admin_players import router as players_router
from tta.api.routes.admin_prompts import router as prompts_router
from tta.api.routes.admin_rate_limits import router as rate_limits_router
from tta.api.routes.admin_system import router as system_router

# Legacy router for backward compatibility with direct imports.
# New code should import the specific sub-router needed.
router = None  # Replaced with individual sub-routers at include time.

__all__ = [
    "games_router",
    "moderation_router",
    "operations_router",
    "players_router",
    "prompts_router",
    "rate_limits_router",
    "system_router",
]
