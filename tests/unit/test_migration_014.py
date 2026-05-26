"""Unit tests for Alembic migration 014 structure (S64 Phase 3).

Validates the generation_profile column addition without executing
against a live database (no Postgres required).
"""

import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
MIGRATION_PATH = (
    REPO_ROOT / "migrations" / "postgres" / "versions" / "014_generation_profile.py"
)


def test_migration_file_exists():
    assert MIGRATION_PATH.exists(), f"Missing: {MIGRATION_PATH}"


def test_migration_revision_constants():
    src = MIGRATION_PATH.read_text()
    assert 'revision = "014"' in src
    assert 'down_revision = "013"' in src


def test_adds_generation_profile_column():
    src = MIGRATION_PATH.read_text()
    assert "generation_profile" in src
    assert "add_column" in src
    assert "game_sessions" in src


def test_column_is_not_nullable():
    src = MIGRATION_PATH.read_text()
    assert "nullable=False" in src


def test_column_has_server_default():
    src = MIGRATION_PATH.read_text()
    assert 'server_default="balanced"' in src


def test_column_type_is_text():
    src = MIGRATION_PATH.read_text()
    assert "sa.Text()" in src


def test_downgrade_drops_column():
    src = MIGRATION_PATH.read_text()
    downgrade_src = src[src.find("def downgrade") :]
    assert "drop_column" in downgrade_src
    assert "generation_profile" in downgrade_src
