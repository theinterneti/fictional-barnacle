"""Unit tests for Alembic migration 011 structure and logic (S33 AC-33.01–33.10).

These tests validate the migration module's constants and structural properties
without executing against a live database (no Postgres required).

AC coverage:
- AC-33.01: Migration inserts universes from game_sessions (idempotent)
- AC-33.02: Migration inserts actors from players (idempotent)
- AC-33.05: Backfill uses ON CONFLICT DO NOTHING for idempotency
- AC-33.06: world_seed column is NOT dropped
- AC-33.07: universe_id is nullable on game_sessions (v1 sessions unaffected)
- AC-33.08: actors column defaults to '[]' (not NULL)
- AC-33.09: Neo4j migration file 004 exists
- AC-33.10: Validation script exists
"""

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
MIGRATION_PATH = (
    REPO_ROOT / "migrations" / "postgres" / "versions" / "011_v2_universe_entity.py"
)
NEO4J_PATH = REPO_ROOT / "migrations" / "neo4j" / "004_universe_extension.cypher"
SCRIPT_PATH = REPO_ROOT / "scripts" / "migrate_validate_v2.py"


@pytest.mark.spec("AC-33.09")
def test_neo4j_migration_004_exists():
    assert NEO4J_PATH.exists(), f"Missing: {NEO4J_PATH}"


@pytest.mark.spec("AC-33.10")
def test_validation_script_exists():
    assert SCRIPT_PATH.exists(), f"Missing: {SCRIPT_PATH}"


def test_migration_file_exists():
    assert MIGRATION_PATH.exists(), f"Missing: {MIGRATION_PATH}"


def test_migration_revision_constants():
    src = MIGRATION_PATH.read_text()
    assert 'revision = "011"' in src
    assert 'down_revision = "010"' in src


@pytest.mark.spec("AC-33.07")
def test_universe_id_is_nullable():
    src = MIGRATION_PATH.read_text()
    # game_sessions universe_id column should be nullable
    assert "universe_id" in src
    # The add_column for universe_id should not specify nullable=False
    # (absence of nullable=False means it defaults to nullable in SA)
    add_col_block = re.search(
        r'add_column\s*\(\s*["\']game_sessions["\'].*?universe_id.*?\)',
        src,
        re.DOTALL,
    )
    assert add_col_block, "add_column for game_sessions.universe_id not found"
    block_text = add_col_block.group()
    assert "nullable=False" not in block_text, (
        "universe_id on game_sessions must be nullable (v1 sessions have no universe)"
    )


@pytest.mark.spec("AC-33.08")
def test_actors_column_has_default_empty_array():
    src = MIGRATION_PATH.read_text()
    # The actors JSONB column should have server_default='[]'
    assert "actors" in src
    assert "[]" in src


@pytest.mark.spec("AC-33.06")
def test_world_seed_not_dropped():
    src = MIGRATION_PATH.read_text()
    # downgrade should NOT drop world_seed
    downgrade_src = src[src.find("def downgrade") :]
    assert "world_seed" not in downgrade_src, (
        "downgrade() must NOT drop world_seed — AC-33.06 requires preservation"
    )


@pytest.mark.spec("AC-33.01")
def test_backfill_inserts_universes_from_game_sessions():
    src = MIGRATION_PATH.read_text()
    assert "INSERT INTO universes" in src


@pytest.mark.spec("AC-33.02")
def test_backfill_inserts_actors_from_players():
    src = MIGRATION_PATH.read_text()
    assert "INSERT INTO actors" in src


@pytest.mark.spec("AC-33.05")
def test_backfill_is_idempotent():
    src = MIGRATION_PATH.read_text()
    assert "ON CONFLICT" in src and "DO NOTHING" in src, (
        "Backfill must use ON CONFLICT DO NOTHING for idempotency (AC-33.05)"
    )


@pytest.mark.spec("AC-33.04")
def test_backfill_inserts_character_states():
    src = MIGRATION_PATH.read_text()
    assert "INSERT INTO character_states" in src


def test_neo4j_migration_backfills_universe_id():
    src = NEO4J_PATH.read_text()
    assert "universe_id = n.session_id" in src
    assert "universe_id IS NULL" in src


def test_neo4j_migration_creates_indexes():
    src = NEO4J_PATH.read_text()
    assert "CREATE INDEX" in src
    assert "universe_id" in src


def test_downgrade_drops_tables_in_order():
    src = MIGRATION_PATH.read_text()
    downgrade_src = src[src.find("def downgrade") :]
    # universe_snapshots before character_states before actors before universes
    pos_snapshots = downgrade_src.find("universe_snapshots")
    pos_chars = downgrade_src.find("character_states")
    pos_actors = downgrade_src.find('"actors"')
    pos_universes = downgrade_src.rfind("universes")  # last drop
    assert pos_snapshots < pos_chars < pos_universes
    assert pos_actors < pos_universes


# ===========================================================================
# AC-33.03 — Backfill sets universe_id on existing game_sessions rows
# ===========================================================================


@pytest.mark.spec("AC-33.03")
def test_migration_backfills_game_sessions_universe_id() -> None:
    """Migration SQL contains UPDATE game_sessions SET universe_id for backfill."""
    text = MIGRATION_PATH.read_text()
    assert "UPDATE game_sessions" in text
    assert "universe_id" in text
    # The backfill sets universe_id where it was NULL (legacy sessions)
    assert "universe_id IS NULL" in text
