"""Add game lifecycle columns to game_sessions (S27 FR-27.01–FR-27.04).

Revision ID: 002
Revises: 001
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column("title", sa.Text(), nullable=True),
    )
    op.add_column(
        "game_sessions",
        sa.Column("summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "last_played_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "game_sessions",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "needs_recovery",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "turn_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )

    # Index for listing games by recency (S27 FR-27.08)
    op.create_index(
        "ix_game_sessions_player_last_played",
        "game_sessions",
        ["player_id", sa.text("last_played_at DESC")],
    )

    # Backfill last_played_at from updated_at for existing rows
    op.execute("UPDATE game_sessions SET last_played_at = updated_at")

    # Add 'completed' to status check if one exists (none in v1, so no-op)


def downgrade() -> None:
    op.drop_index("ix_game_sessions_player_last_played", "game_sessions")
    op.drop_column("game_sessions", "turn_count")
    op.drop_column("game_sessions", "needs_recovery")
    op.drop_column("game_sessions", "deleted_at")
    op.drop_column("game_sessions", "last_played_at")
    op.drop_column("game_sessions", "summary")
    op.drop_column("game_sessions", "title")
