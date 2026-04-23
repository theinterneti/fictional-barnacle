"""Add genesis_state column to game_sessions (S40 — Genesis v2).

Revision ID: 012
Revises: 011
"""

from __future__ import annotations

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS genesis_state JSONB NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE game_sessions DROP COLUMN IF EXISTS genesis_state")
