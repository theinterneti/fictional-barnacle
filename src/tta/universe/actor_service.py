"""Actor identity and CharacterState service (S31 AC-31.01–31.09)."""

from __future__ import annotations

import json
from uuid import UUID

import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from tta.universe.exceptions import ActorNotFoundError, CharacterStateNotFoundError
from tta.universe.models import Actor, CharacterState


def _row_to_actor(row: sa.Row) -> Actor:  # type: ignore[type-arg]
    return Actor(
        id=row.id,
        player_id=row.player_id,
        display_name=row.display_name,
        avatar_config=row.avatar_config if row.avatar_config is not None else {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_character_state(row: sa.Row) -> CharacterState:  # type: ignore[type-arg]
    return CharacterState(
        id=row.id,
        actor_id=row.actor_id,
        universe_id=row.universe_id,
        traits=row.traits if row.traits is not None else [],
        inventory=row.inventory if row.inventory is not None else [],
        conditions=row.conditions if row.conditions is not None else [],
        reputation=row.reputation if row.reputation is not None else {},
        relationships=row.relationships if row.relationships is not None else {},
        custom=row.custom if row.custom is not None else {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ActorService:
    """Application service for Actor identity and CharacterState (S31).

    Actors are created once per player registration (AC-31.01).
    CharacterStates are created lazily on first session within a universe (AC-31.03).
    """

    # ------------------------------------------------------------------
    # Actor operations
    # ------------------------------------------------------------------

    async def get_or_create_for_player(
        self,
        player_id: UUID,
        display_name: str,
        pg: AsyncSession,
    ) -> Actor:
        """Return existing actor for player, or create one (AC-31.01).

        Idempotent: concurrent calls for the same player_id are safe.
        Uses INSERT … ON CONFLICT DO NOTHING backed by the uq_actors_player_id
        unique constraint to eliminate the SELECT→INSERT TOCTOU race.
        """
        actor = Actor(player_id=player_id, display_name=display_name)
        await pg.execute(
            sa.text(
                "INSERT INTO actors (id, player_id, display_name, avatar_config, "
                "created_at, updated_at) "
                "VALUES (:id, :pid, :display_name, '{}', :created_at, :updated_at) "
                "ON CONFLICT (player_id) DO NOTHING"
            ),
            {
                "id": actor.id,
                "pid": actor.player_id,
                "display_name": actor.display_name,
                "created_at": actor.created_at,
                "updated_at": actor.updated_at,
            },
        )
        # Re-SELECT: on conflict the pre-existing row is returned; on insert
        # we get the row we just created.  Both paths produce a valid Actor.
        result = await pg.execute(
            sa.text(
                "SELECT id, player_id, display_name, avatar_config, "
                "created_at, updated_at "
                "FROM actors WHERE player_id = :pid LIMIT 1"
            ),
            {"pid": player_id},
        )
        row = result.one_or_none()
        if row is not None:
            return _row_to_actor(row)
        raise ActorNotFoundError(str(player_id))  # unreachable; satisfies type-checker

    async def get_by_player(self, player_id: UUID, pg: AsyncSession) -> list[Actor]:
        """Return all actors for a player (AC-31.08)."""
        result = await pg.execute(
            sa.text(
                "SELECT id, player_id, display_name, avatar_config, "
                "created_at, updated_at "
                "FROM actors WHERE player_id = :pid ORDER BY created_at"
            ),
            {"pid": player_id},
        )
        return [_row_to_actor(r) for r in result.fetchall()]

    async def get(self, actor_id: UUID, pg: AsyncSession) -> Actor:
        """Return actor by id; raise ActorNotFoundError if absent."""
        result = await pg.execute(
            sa.text(
                "SELECT id, player_id, display_name, avatar_config, "
                "created_at, updated_at "
                "FROM actors WHERE id = :id"
            ),
            {"id": actor_id},
        )
        row = result.one_or_none()
        if row is None:
            raise ActorNotFoundError(actor_id)
        return _row_to_actor(row)

    # ------------------------------------------------------------------
    # CharacterState operations
    # ------------------------------------------------------------------

    async def get_character_state(
        self,
        actor_id: UUID,
        universe_id: UUID,
        pg: AsyncSession,
    ) -> CharacterState | None:
        """Return CharacterState for (actor, universe), or None (AC-31.09)."""
        result = await pg.execute(
            sa.text(
                "SELECT id, actor_id, universe_id, traits, inventory, conditions, "
                "reputation, relationships, custom, created_at, updated_at "
                "FROM character_states "
                "WHERE actor_id = :aid AND universe_id = :uid"
            ),
            {"aid": actor_id, "uid": universe_id},
        )
        row = result.one_or_none()
        if row is None:
            return None
        return _row_to_character_state(row)

    async def get_or_create_character_state(
        self,
        actor_id: UUID,
        universe_id: UUID,
        pg: AsyncSession,
    ) -> CharacterState:
        """Return or lazily create CharacterState (AC-31.03, AC-31.04).

        Uses INSERT ... ON CONFLICT DO NOTHING to satisfy AC-31.05
        (DB UNIQUE constraint prevents duplicates).
        """
        state = await self.get_character_state(actor_id, universe_id, pg)
        if state is not None:
            return state

        new_state = CharacterState(actor_id=actor_id, universe_id=universe_id)
        await pg.execute(
            sa.text(
                "INSERT INTO character_states "
                "(id, actor_id, universe_id, traits, inventory, conditions, "
                "reputation, relationships, custom, created_at, updated_at) "
                "VALUES (:id, :aid, :uid, '[]', '[]', '[]', '{}', '{}', '{}', "
                ":created_at, :updated_at) "
                "ON CONFLICT (actor_id, universe_id) DO NOTHING"
            ),
            {
                "id": new_state.id,
                "aid": actor_id,
                "uid": universe_id,
                "created_at": new_state.created_at,
                "updated_at": new_state.updated_at,
            },
        )
        # Re-fetch to get the definitive row (handles the ON CONFLICT case)
        result = await self.get_character_state(actor_id, universe_id, pg)
        assert result is not None  # noqa: S101
        return result

    async def upsert_character_state(
        self,
        actor_id: UUID,
        universe_id: UUID,
        pg: AsyncSession,
        *,
        traits: list | None = None,
        inventory: list | None = None,
        conditions: list | None = None,
        reputation: dict | None = None,
        relationships: dict | None = None,
        custom: dict | None = None,
    ) -> CharacterState:
        """Update mutable fields on a CharacterState (S31 FR-31.07).

        Raises CharacterStateNotFoundError if the state doesn't exist yet.
        Callers should use get_or_create_character_state first.
        """
        existing = await self.get_character_state(actor_id, universe_id, pg)
        if existing is None:
            raise CharacterStateNotFoundError(actor_id, universe_id)

        updates: dict[str, object] = {"aid": actor_id, "uid": universe_id}
        set_clauses: list[str] = ["updated_at = now()"]

        if traits is not None:
            updates["traits"] = json.dumps(traits)
            set_clauses.append("traits = :traits::jsonb")
        if inventory is not None:
            updates["inventory"] = json.dumps(inventory)
            set_clauses.append("inventory = :inventory::jsonb")
        if conditions is not None:
            updates["conditions"] = json.dumps(conditions)
            set_clauses.append("conditions = :conditions::jsonb")
        if reputation is not None:
            updates["reputation"] = json.dumps(reputation)
            set_clauses.append("reputation = :reputation::jsonb")
        if relationships is not None:
            updates["relationships"] = json.dumps(relationships)
            set_clauses.append("relationships = :relationships::jsonb")
        if custom is not None:
            updates["custom"] = json.dumps(custom)
            set_clauses.append("custom = :custom::jsonb")

        await pg.execute(
            sa.text(
                f"UPDATE character_states SET {', '.join(set_clauses)} "  # noqa: S608
                "WHERE actor_id = :aid AND universe_id = :uid"
            ),
            updates,
        )
        result = await self.get_character_state(actor_id, universe_id, pg)
        assert result is not None  # noqa: S101
        return result
