"""Add summary_generated_at column to game_sessions (S27 FR-27.20).

Revision ID: 004
Revises: 003
"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column("summary_generated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("game_sessions", "summary_generated_at")
