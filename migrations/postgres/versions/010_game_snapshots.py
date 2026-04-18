"""Add game_snapshots table for AC-12.04 periodic state snapshots.

Revision ID: 010
Revises: 009
"""

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "game_snapshots",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("game_session_id", sa.Uuid(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column(
            "world_state",
            sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["game_session_id"],
            ["game_sessions.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_game_snapshots_session_turn",
        "game_snapshots",
        ["game_session_id", "turn_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_game_snapshots_session_turn", table_name="game_snapshots")
    op.drop_table("game_snapshots")
