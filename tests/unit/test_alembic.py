"""Unit tests for Alembic configuration and initial migration.

No running PostgreSQL required — these validate structure and
importability of migration artefacts.
"""

import configparser
import importlib
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ── AC-1: Alembic configuration ──────────────────────────────────


class TestAlembicConfig:
    """alembic.ini exists and points to the correct directory."""

    def test_alembic_ini_exists(self) -> None:
        assert (ROOT / "alembic.ini").is_file()

    def test_script_location(self) -> None:
        cfg = configparser.ConfigParser()
        cfg.read(ROOT / "alembic.ini")
        assert cfg.get("alembic", "script_location") == ("migrations/postgres")

    def test_env_py_exists(self) -> None:
        assert (ROOT / "migrations" / "postgres" / "env.py").is_file()

    def test_script_mako_exists(self) -> None:
        assert (ROOT / "migrations" / "postgres" / "script.py.mako").is_file()

    def test_versions_dir_exists(self) -> None:
        assert (ROOT / "migrations" / "postgres" / "versions").is_dir()


# ── AC-2 / AC-4: Initial migration structure ─────────────────────


@pytest.fixture()
def migration_module() -> types.ModuleType:
    """Import the initial migration as a Python module."""
    spec = importlib.util.spec_from_file_location(
        "initial_schema",
        ROOT / "migrations" / "postgres" / "versions" / "001_initial_schema.py",
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationModule:
    """The initial migration can be loaded and inspected."""

    def test_import_succeeds(self, migration_module: types.ModuleType) -> None:
        assert migration_module is not None

    def test_has_revision(self, migration_module: types.ModuleType) -> None:
        assert hasattr(migration_module, "revision")
        assert migration_module.revision == "001"

    def test_has_upgrade(self, migration_module: types.ModuleType) -> None:
        assert callable(getattr(migration_module, "upgrade", None))

    def test_has_downgrade(self, migration_module: types.ModuleType) -> None:
        assert callable(getattr(migration_module, "downgrade", None))


# ── AC-2 / AC-3: Table & constraint definitions ──────────────────


@pytest.fixture()
def migration_source() -> str:
    """Raw source of the initial migration for structural checks."""
    path = ROOT / "migrations" / "postgres" / "versions" / "001_initial_schema.py"
    return path.read_text()


_EXPECTED_TABLES = [
    "players",
    "player_sessions",
    "game_sessions",
    "turns",
    "world_events",
]


class TestTableDefinitions:
    """All five normative tables are defined in the migration."""

    @pytest.mark.parametrize("table", _EXPECTED_TABLES)
    def test_table_created(self, migration_source: str, table: str) -> None:
        assert f'"{table}"' in migration_source

    def test_players_handle_unique(self, migration_source: str) -> None:
        assert "unique=True" in migration_source
        assert '"handle"' in migration_source

    def test_player_sessions_token_unique(self, migration_source: str) -> None:
        assert '"token"' in migration_source

    def test_turns_session_turn_unique(self, migration_source: str) -> None:
        assert "uq_turns_session_turn" in migration_source

    def test_turns_idempotency_unique_constraint(self, migration_source: str) -> None:
        assert "uq_turns_session_idempotency" in migration_source

    def test_world_events_session_index(self, migration_source: str) -> None:
        assert "idx_world_events_session" in migration_source


class TestDowngrade:
    """Downgrade drops tables in correct dependency order."""

    def test_downgrade_drops_all_tables(self, migration_source: str) -> None:
        for table in _EXPECTED_TABLES:
            assert f'drop_table("{table}")' in migration_source

    def test_downgrade_order(self, migration_source: str) -> None:
        """Child tables must be dropped before parent tables."""
        src = migration_source
        # world_events and turns before game_sessions
        assert src.index('drop_table("world_events")') < src.index(
            'drop_table("game_sessions")'
        )
        assert src.index('drop_table("turns")') < src.index(
            'drop_table("game_sessions")'
        )
        # player_sessions before players
        assert src.index('drop_table("player_sessions")') < src.index(
            'drop_table("players")'
        )
