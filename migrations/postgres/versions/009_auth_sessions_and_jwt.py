"""Add JWT auth infrastructure (S11 Player Identity & Sessions).

Adds auth columns to players table, creates auth_sessions (session families)
and refresh_tokens tables for JWT-based authentication.

Revision ID: 009
Revises: 008
"""

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on players table
    op.add_column(
        "players",
        sa.Column("email", sa.String(320), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column("password_hash", sa.String(128), nullable=True),
    )
    op.add_column(
        "players",
        sa.Column(
            "is_anonymous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "players",
        sa.Column(
            "display_name",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'Adventurer'"),
        ),
    )
    op.add_column(
        "players",
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'player'"),
        ),
    )
    op.add_column(
        "players",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_players_email",
        "players",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )

    # Auth sessions (session families for token rotation)
    op.create_table(
        "auth_sessions",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column(
            "is_anonymous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_auth_sessions_player_id",
        "auth_sessions",
        ["player_id"],
    )

    # Refresh tokens tied to session families
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("token_jti", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["auth_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_refresh_tokens_token_jti",
        "refresh_tokens",
        ["token_jti"],
    )
    op.create_index(
        "ix_refresh_tokens_session_id",
        "refresh_tokens",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("auth_sessions")
    op.drop_index("ix_players_email", table_name="players")
    op.drop_column("players", "last_login_at")
    op.drop_column("players", "role")
    op.drop_column("players", "display_name")
    op.drop_column("players", "is_anonymous")
    op.drop_column("players", "password_hash")
    op.drop_column("players", "email")
