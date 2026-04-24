"""Add paused_at column to game_sessions (S11 FR-11.41).

Tracks when a game entered paused state so the 30-day expiry window
is measured from pause time rather than last-played time.

Revision ID: 013
Revises: 012
"""

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill: for existing paused games, use updated_at as a best-effort proxy
    op.execute(
        "UPDATE game_sessions SET paused_at = updated_at WHERE status = 'paused'"
    )


def downgrade() -> None:
    op.drop_column("game_sessions", "paused_at")
