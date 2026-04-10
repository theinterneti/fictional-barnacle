"""Add consent and age gate fields to players (S17 FR-17.22–17.26).

Revision ID: 007
Revises: 006
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("consent_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("consent_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column(
            "consent_categories",
            sa.JSON(),
            nullable=True,
        ),
    )
    op.add_column(
        "players",
        sa.Column("age_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("consent_ip_hash", sa.Text(), nullable=True),
    )
    # Enforce required JSONB keys when consent_categories is non-NULL
    op.execute(
        "ALTER TABLE players ADD CONSTRAINT ck_consent_required_keys "
        "CHECK ("
        "consent_categories IS NULL "
        "OR ("
        "consent_categories ? 'core_gameplay' "
        "AND consent_categories ? 'llm_processing'"
        ")"
        ")"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE players DROP CONSTRAINT IF EXISTS ck_consent_required_keys")
    op.drop_column("players", "consent_ip_hash")
    op.drop_column("players", "age_confirmed_at")
    op.drop_column("players", "consent_categories")
    op.drop_column("players", "consent_accepted_at")
    op.drop_column("players", "consent_version")
