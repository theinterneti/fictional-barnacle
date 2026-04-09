"""Add moderation_records table (S24 FR-24.09–FR-24.14).

Stores every moderation action with the original content in an
access-controlled table.  General logs reference moderation_id
and content_hash only — never raw content.

Revision ID: 003
Revises: 002
"""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_records",
        sa.Column("moderation_id", sa.Text(), primary_key=True),
        sa.Column("turn_id", sa.Text(), nullable=False),
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("player_id", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Query by game + time range (FR-24.10)
    op.create_index(
        "ix_moderation_records_game_ts",
        "moderation_records",
        ["game_id", sa.text("timestamp DESC")],
    )
    # Query by player + time range (FR-24.10)
    op.create_index(
        "ix_moderation_records_player_ts",
        "moderation_records",
        ["player_id", sa.text("timestamp DESC")],
    )
    # Filter by category + verdict (FR-24.10)
    op.create_index(
        "ix_moderation_records_category_verdict",
        "moderation_records",
        ["category", "verdict"],
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_records_category_verdict", "moderation_records")
    op.drop_index("ix_moderation_records_player_ts", "moderation_records")
    op.drop_index("ix_moderation_records_game_ts", "moderation_records")
    op.drop_table("moderation_records")
