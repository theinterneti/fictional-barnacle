"""Add generation_profile column to game_sessions (S64 Phase 3).

Stores the canonical generation serving profile selected for a session.
Default is 'balanced' per S64 FR-64.02.

Revision ID: 014
Revises: 013
"""

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "game_sessions",
        sa.Column(
            "generation_profile",
            sa.Text(),
            nullable=False,
            server_default="balanced",
        ),
    )


def downgrade() -> None:
    op.drop_column("game_sessions", "generation_profile")
