"""Add cost tracking fields to game_sessions (S07 FR-07.17–07.20).

Revision ID: 008
Revises: 007
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column(
            "total_cost_usd",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "game_sessions",
        sa.Column(
            "cost_warning_sent",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("game_sessions", "cost_warning_sent")
    op.drop_column("game_sessions", "total_cost_usd")
