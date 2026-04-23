"""Universe lifecycle service (S29 AC-29.01–29.13)."""

from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.universe.exceptions import (
    CompositionValidationError,
    SeedImmutabilityError,
    UniverseAlreadyActiveError,
    UniverseArchivedError,
    UniverseNotFoundError,
    UniverseStatusTransitionError,
)
from tta.universe.models import Universe

# Valid status transitions: {from_status: allowed_to_statuses}
_TRANSITIONS: dict[str, set[str]] = {
    "dormant": {"active", "archived"},
    "active": {"paused", "archived"},
    "paused": {"active", "archived"},
    "archived": set(),
}

UniverseStatus = Literal["dormant", "active", "paused", "archived"]


def _row_to_universe(row: sa.Row) -> Universe:  # type: ignore[type-arg]
    return Universe(
        id=row.id,
        owner_id=row.owner_id,
        name=row.name,
        description=row.description or "",
        status=row.status,
        config=row.config if row.config is not None else {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class UniverseService:
    """Application service for Universe lifecycle (S29).

    All mutations use SELECT FOR UPDATE to enforce the singleton policy
    (AC-29.09) without a DB UNIQUE constraint on universe_id.
    """

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get(self, universe_id: UUID, pg: AsyncSession) -> Universe:
        """Return Universe by id; raise UniverseNotFoundError if absent."""
        result = await pg.execute(
            sa.text(
                "SELECT id, owner_id, name, description, status, config, "
                "created_at, updated_at "
                "FROM universes WHERE id = :id"
            ),
            {"id": universe_id},
        )
        row = result.one_or_none()
        if row is None:
            raise UniverseNotFoundError(universe_id)
        return _row_to_universe(row)

    async def list_for_player(
        self,
        player_id: UUID,
        pg: AsyncSession,
        status: UniverseStatus | None = None,
    ) -> list[Universe]:
        """Return universes owned by player, optionally filtered by status.

        AC-29.12: lists all universes for a player.
        """
        if status is not None:
            result = await pg.execute(
                sa.text(
                    "SELECT id, owner_id, name, description, status, config, "
                    "created_at, updated_at "
                    "FROM universes WHERE owner_id = :pid AND status = :status "
                    "ORDER BY created_at DESC"
                ),
                {"pid": player_id, "status": status},
            )
        else:
            result = await pg.execute(
                sa.text(
                    "SELECT id, owner_id, name, description, status, config, "
                    "created_at, updated_at "
                    "FROM universes WHERE owner_id = :pid "
                    "ORDER BY created_at DESC"
                ),
                {"pid": player_id},
            )
        return [_row_to_universe(r) for r in result.fetchall()]

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(
        self,
        owner_id: UUID,
        name: str,
        pg: AsyncSession,
        description: str = "",
        config: dict | None = None,
    ) -> Universe:
        """Create a new dormant universe (AC-29.01)."""
        universe = Universe(
            owner_id=owner_id,
            name=name,
            description=description,
            config=config or {},
        )
        await pg.execute(
            sa.text(
                "INSERT INTO universes "
                "(id, owner_id, name, description, status, config, "
                "created_at, updated_at) "
                "VALUES (:id, :owner_id, :name, :description, :status, "
                ":config::jsonb, :created_at, :updated_at)"
            ),
            {
                "id": universe.id,
                "owner_id": universe.owner_id,
                "name": universe.name,
                "description": universe.description,
                "status": universe.status,
                "config": json.dumps(universe.config),
                "created_at": universe.created_at,
                "updated_at": universe.updated_at,
            },
        )
        return universe

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    async def activate(self, universe_id: UUID, pg: AsyncSession) -> Universe:
        """Transition universe to active; enforce singleton policy (AC-29.09)."""
        row = await self._lock_row(universe_id, pg)
        universe = _row_to_universe(row)

        if universe.status == "active":
            raise UniverseAlreadyActiveError(universe_id)
        if universe.status == "archived":
            raise UniverseArchivedError(universe_id)
        if "active" not in _TRANSITIONS.get(universe.status, set()):
            raise UniverseStatusTransitionError(universe.status, "active")

        # AC-29.09: ensure no other session currently has this universe active
        active_check = await pg.execute(
            sa.text(
                "SELECT 1 FROM game_sessions "
                "WHERE universe_id = :uid AND status IN ('created', 'active') "
                "LIMIT 1"
            ),
            {"uid": universe_id},
        )
        if active_check.one_or_none() is not None:
            raise UniverseAlreadyActiveError(universe_id)

        return await self._set_status(universe_id, "active", pg)

    async def pause(self, universe_id: UUID, pg: AsyncSession) -> Universe:
        """Transition universe to paused (AC-29.06, AC-29.08)."""
        row = await self._lock_row(universe_id, pg)
        universe = _row_to_universe(row)

        if "paused" not in _TRANSITIONS.get(universe.status, set()):
            raise UniverseStatusTransitionError(universe.status, "paused")

        return await self._set_status(universe_id, "paused", pg)

    async def archive(self, universe_id: UUID, pg: AsyncSession) -> Universe:
        """Archive a universe (any→archived, explicit call required — AC-29.08)."""
        row = await self._lock_row(universe_id, pg)
        universe = _row_to_universe(row)

        if universe.status == "archived":
            return universe  # idempotent
        if "archived" not in _TRANSITIONS.get(universe.status, set()):
            raise UniverseStatusTransitionError(universe.status, "archived")

        return await self._set_status(universe_id, "archived", pg)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _lock_row(self, universe_id: UUID, pg: AsyncSession) -> sa.Row:  # type: ignore[type-arg]
        result = await pg.execute(
            sa.text(
                "SELECT id, owner_id, name, description, status, config, "
                "created_at, updated_at "
                "FROM universes WHERE id = :id FOR UPDATE"
            ),
            {"id": universe_id},
        )
        row = result.one_or_none()
        if row is None:
            raise UniverseNotFoundError(universe_id)
        return row

    async def _set_status(
        self, universe_id: UUID, status: str, pg: AsyncSession
    ) -> Universe:
        await pg.execute(
            sa.text(
                "UPDATE universes SET status = :status, updated_at = now() "
                "WHERE id = :id"
            ),
            {"status": status, "id": universe_id},
        )
        return await self.get(universe_id, pg)

    # ------------------------------------------------------------------
    # S39 — Universe Composition & seed management
    # ------------------------------------------------------------------

    async def patch_config(
        self,
        universe_id: UUID,
        config_patch: dict,
        pg: AsyncSession,
    ) -> Universe:
        """Merge *config_patch* into ``universes.config`` (FR-39.09).

        Rules:
        - ``"seed"`` key in the patch → raise :exc:`SeedImmutabilityError`
          if the universe already has a seed (AC-39.05 / FR-39.11).
        - ``"composition"`` key validated by :class:`CompositionValidator`
          before being merged (AC-39.07/08).
        - Subsystem namespaces (``memory``, ``time``, ``npc``) are passed
          through untouched — the validator must not reject them.
        """
        from tta.universe.composition import CompositionValidator, UniverseComposition

        universe = await self._lock_row(universe_id, pg)
        current_config: dict = universe.config or {}

        # Reject seed overwrites
        if "seed" in config_patch:
            if current_config.get("seed") is not None:
                raise SeedImmutabilityError(
                    f"Universe {universe_id} already has a seed — it cannot be changed."
                )

        # Validate composition block if present
        if "composition" in config_patch:
            blob = config_patch["composition"] or {}
            # Parse into dataclass to normalise, then validate
            test_config = {"composition": blob}
            comp = UniverseComposition.from_config(test_config)
            validator = CompositionValidator()
            errors = validator.validate(comp)
            if errors:
                raise CompositionValidationError(
                    "Composition validation failed: " + "; ".join(errors)
                )

        # Merge (shallow merge at top level — subsystem namespaces are preserved)
        merged = {**current_config, **config_patch}

        await pg.execute(
            sa.text(
                "UPDATE universes SET config = CAST(:cfg AS jsonb),"
                " updated_at = now() WHERE id = :id"
            ),
            {"cfg": json.dumps(merged), "id": universe_id},
        )
        await pg.commit()
        return await self.get(universe_id, pg)

    async def ensure_seed(self, universe_id: UUID, pg: AsyncSession) -> str:
        """Return the universe seed, generating one if absent (AC-39.02).

        The seed is stored at ``config["seed"]`` and is immutable once set.
        """
        import secrets

        universe = await self._lock_row(universe_id, pg)
        config: dict = universe.config or {}

        if config.get("seed") is not None:
            return str(config["seed"])

        seed = int.from_bytes(secrets.token_bytes(8), "big")
        config["seed"] = seed

        await pg.execute(
            sa.text(
                "UPDATE universes SET config = CAST(:cfg AS jsonb),"
                " updated_at = now() WHERE id = :id"
            ),
            {"cfg": json.dumps(config), "id": universe_id},
        )
        await pg.commit()
        return str(seed)
