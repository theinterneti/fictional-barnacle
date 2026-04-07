"""Initial schema — normative PostgreSQL tables.

Tables: players, player_sessions, game_sessions, turns, world_events
Reference: system.md §3.2

Revision ID: 001
Revises: None
Create Date: 2025-01-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ---------------------------------------------------------------------------
# Shared defaults
# ---------------------------------------------------------------------------
_UUID_PK = {
    "type_": sa.UUID(),
    "nullable": False,
    "server_default": sa.text("gen_random_uuid()"),
}
_CREATED_AT = {
    "type_": sa.DateTime(timezone=True),
    "nullable": False,
    "server_default": sa.func.now(),
}
_UPDATED_AT = {
    "type_": sa.DateTime(timezone=True),
    "nullable": False,
    "server_default": sa.func.now(),
}


def upgrade() -> None:
    # ── players ───────────────────────────────────────────────────
    op.create_table(
        "players",
        sa.Column("id", **_UUID_PK),
        sa.Column("handle", sa.VARCHAR(), nullable=False, unique=True),
        sa.Column("created_at", **_CREATED_AT),
        sa.Column("updated_at", **_UPDATED_AT),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── player_sessions ───────────────────────────────────────────
    op.create_table(
        "player_sessions",
        sa.Column("id", **_UUID_PK),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column("token", sa.VARCHAR(), nullable=False, unique=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("created_at", **_CREATED_AT),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )

    # ── game_sessions ─────────────────────────────────────────────
    op.create_table(
        "game_sessions",
        sa.Column("id", **_UUID_PK),
        sa.Column("player_id", sa.UUID(), nullable=False),
        sa.Column(
            "world_seed",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("status", sa.VARCHAR(), nullable=False),
        sa.Column("created_at", **_CREATED_AT),
        sa.Column("updated_at", **_UPDATED_AT),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )

    # ── turns ─────────────────────────────────────────────────────
    op.create_table(
        "turns",
        sa.Column("id", **_UUID_PK),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("player_input", sa.Text(), nullable=False),
        sa.Column("narrative_output", sa.Text(), nullable=True),
        sa.Column("model_used", sa.VARCHAR(), nullable=True),
        sa.Column(
            "token_count",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.VARCHAR(), nullable=False),
        sa.Column("idempotency_key", sa.UUID(), nullable=True),
        sa.Column(
            "safety_flags",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", **_CREATED_AT),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "session_id",
            "turn_number",
            name="uq_turns_session_turn",
        ),
    )

    # Partial unique index: idempotency_key only when non-null
    op.create_index(
        "ix_turns_session_idempotency",
        "turns",
        ["session_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_index(
        "ix_turns_session_id",
        "turns",
        ["session_id"],
    )

    # ── world_events ──────────────────────────────────────────────
    op.create_table(
        "world_events",
        sa.Column("id", **_UUID_PK),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.VARCHAR(), nullable=False),
        sa.Column("entity_id", sa.VARCHAR(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", **_CREATED_AT),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["turn_id"], ["turns.id"], ondelete="SET NULL"),
    )

    op.create_index(
        "ix_world_events_session_id",
        "world_events",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_table("world_events")
    op.drop_table("turns")
    op.drop_table("game_sessions")
    op.drop_table("player_sessions")
    op.drop_table("players")
