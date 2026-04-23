"""v2 Universe entity: universes, actors, character_states, universe_snapshots.

Also alters game_sessions to add universe_id, actors JSONB columns.
Backfills all v1 game_sessions rows per S33 AC-33.01–33.05.

Revision ID: 011
Revises: 010
"""

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

_JSONB = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    # ── universes ─────────────────────────────────────────────────
    op.create_table(
        "universes",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="dormant",
        ),
        sa.Column("config", _JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["players.id"],
            name="fk_universes_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('dormant','active','paused','archived')",
            name="ck_universes_status",
        ),
    )
    op.create_index("ix_universes_owner", "universes", ["owner_id"])
    op.create_index("ix_universes_status", "universes", ["status"])

    # ── actors ────────────────────────────────────────────────────
    op.create_table(
        "actors",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("avatar_config", _JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_actors_player",
            ondelete="CASCADE",
        ),
    )
    op.create_unique_constraint("uq_actors_player_id", "actors", ["player_id"])

    # ── character_states ──────────────────────────────────────────
    op.create_table(
        "character_states",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("universe_id", sa.Uuid(), nullable=False),
        sa.Column("traits", _JSONB, nullable=False, server_default="[]"),
        sa.Column("inventory", _JSONB, nullable=False, server_default="[]"),
        sa.Column("conditions", _JSONB, nullable=False, server_default="[]"),
        sa.Column("reputation", _JSONB, nullable=False, server_default="{}"),
        sa.Column("relationships", _JSONB, nullable=False, server_default="{}"),
        sa.Column("custom", _JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["actors.id"],
            name="fk_character_states_actor",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["universe_id"],
            ["universes.id"],
            name="fk_character_states_universe",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "actor_id",
            "universe_id",
            name="uq_character_states_actor_universe",
        ),
    )
    op.create_index("ix_character_states_actor", "character_states", ["actor_id"])
    op.create_index("ix_character_states_universe", "character_states", ["universe_id"])

    # ── universe_snapshots ────────────────────────────────────────
    op.create_table(
        "universe_snapshots",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("universe_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot", _JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "snapshot_type",
            sa.Text(),
            nullable=False,
            server_default="session_end",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["universe_id"],
            ["universes.id"],
            name="fk_universe_snapshots_universe",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            name="fk_universe_snapshots_session",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "snapshot_type IN ('session_end','manual','admin')",
            name="ck_universe_snapshots_type",
        ),
    )
    op.create_index(
        "ix_universe_snapshots_universe_created",
        "universe_snapshots",
        ["universe_id", "created_at"],
    )

    # ── alter game_sessions ───────────────────────────────────────
    op.add_column(
        "game_sessions",
        sa.Column("universe_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "actors",
            _JSONB,
            nullable=False,
            server_default="[]",
        ),
    )
    op.create_foreign_key(
        "fk_game_sessions_universe",
        "game_sessions",
        "universes",
        ["universe_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_game_sessions_universe", "game_sessions", ["universe_id"])

    # ── backfill (S33 AC-33.01–33.05, idempotent) ─────────────────
    conn = op.get_bind()

    # AC-33.01: one universe per game_session, config = world_seed, status = 'paused'
    # Use gs.id as the universe id so the linking UPDATE below is deterministic.
    conn.execute(
        sa.text("""
        INSERT INTO universes (id, owner_id, name, description, status, config)
        SELECT
            gs.id,
            gs.player_id,
            COALESCE(gs.title, 'Legacy Universe ' || gs.id::text),
            '',
            'paused',
            CASE
                WHEN gs.world_seed IS NOT NULL THEN gs.world_seed
                ELSE '{}'::jsonb
            END
        FROM game_sessions gs
        WHERE gs.universe_id IS NULL
        ON CONFLICT (id) DO NOTHING
        """)
    )

    # Link game_sessions → their new universe (always joins on gs.id = u.id).
    conn.execute(
        sa.text("""
        UPDATE game_sessions gs
        SET universe_id = gs.id
        WHERE gs.universe_id IS NULL
          AND EXISTS (SELECT 1 FROM universes u WHERE u.id = gs.id)
        """)
    )

    # AC-33.02: one actor per player
    conn.execute(
        sa.text("""
        INSERT INTO actors (id, player_id, display_name)
        SELECT gen_random_uuid(), p.id, p.handle
        FROM players p
        WHERE NOT EXISTS (
            SELECT 1 FROM actors a WHERE a.player_id = p.id
        )
        """)
    )

    # AC-33.03: backfill game_sessions.universe_id (already done above for legacy)
    # For any remaining NULLs (race-condition guard), skip — they are v1 sessions
    # that couldn't be linked. This is AC-33.05 idempotency.

    # AC-33.04: character_states for all sessions with a universe_id
    conn.execute(
        sa.text("""
        INSERT INTO character_states (id, actor_id, universe_id)
        SELECT gen_random_uuid(), a.id, gs.universe_id
        FROM game_sessions gs
        JOIN actors a ON a.player_id = gs.player_id
        WHERE gs.universe_id IS NOT NULL
        ON CONFLICT (actor_id, universe_id) DO NOTHING
        """)
    )


def downgrade() -> None:
    # Remove FK and index on game_sessions first
    op.drop_constraint("fk_game_sessions_universe", "game_sessions", type_="foreignkey")
    op.drop_index("ix_game_sessions_universe", table_name="game_sessions")
    op.drop_column("game_sessions", "actors")
    op.drop_column("game_sessions", "universe_id")

    # Drop tables in reverse dependency order
    op.drop_index(
        "ix_universe_snapshots_universe_created", table_name="universe_snapshots"
    )
    op.drop_table("universe_snapshots")

    op.drop_index("ix_character_states_universe", table_name="character_states")
    op.drop_index("ix_character_states_actor", table_name="character_states")
    op.drop_table("character_states")

    op.drop_constraint("uq_actors_player_id", "actors", type_="unique")
    op.drop_table("actors")

    op.drop_index("ix_universes_status", table_name="universes")
    op.drop_index("ix_universes_owner", table_name="universes")
    op.drop_table("universes")
