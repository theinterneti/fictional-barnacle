"""Unit tests for the Neo4j migration runner.

All tests mock the Neo4j driver — no running Neo4j instance required.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

from tta.world.migrate import (
    MIGRATIONS_DIR,
    _discover_migrations,
    _parse_statements,
    apply_migration,
    get_current_version,
    run_migrations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_driver(current_version: int = 0) -> MagicMock:
    """Return a mock Neo4j driver whose session reports *current_version*."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    result = MagicMock()
    if current_version > 0:
        record = {"ver": current_version}
        result.single.return_value = record
    else:
        result.single.return_value = None

    session.run.return_value = result
    return driver


def _make_migration_dir(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Create a temp directory with the given migration files."""
    d = tmp_path / "migrations" / "neo4j"
    d.mkdir(parents=True)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# Migration file discovery
# ---------------------------------------------------------------------------


class TestDiscoverMigrations:
    """Tests for _discover_migrations()."""

    def test_discovers_real_migrations(self) -> None:
        """The real migrations/neo4j/ dir has at least 001."""
        if not MIGRATIONS_DIR.is_dir():
            pytest.skip("migrations dir not present")
        result = _discover_migrations(MIGRATIONS_DIR)
        assert len(result) >= 1
        assert result[0][0] == 1

    def test_discovers_numbered_files(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(
            tmp_path,
            {
                "001_first.cypher": "CREATE (n:A);",
                "002_second.cypher": "CREATE (n:B);",
                "README.md": "not a migration",
            },
        )
        result = _discover_migrations(d)
        assert [(v, p.name) for v, p in result] == [
            (1, "001_first.cypher"),
            (2, "002_second.cypher"),
        ]

    def test_sorted_order(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(
            tmp_path,
            {
                "003_c.cypher": "",
                "001_a.cypher": "",
                "002_b.cypher": "",
            },
        )
        versions = [v for v, _ in _discover_migrations(d)]
        assert versions == [1, 2, 3]

    def test_empty_directory(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(tmp_path, {})
        assert _discover_migrations(d) == []

    def test_nonexistent_directory(self, tmp_path: pathlib.Path) -> None:
        assert _discover_migrations(tmp_path / "nope") == []

    def test_ignores_non_matching_files(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(
            tmp_path,
            {
                "abc_nope.cypher": "",
                "001_.cypher": "",  # no name after underscore? regex needs 1+ chars
            },
        )
        result = _discover_migrations(d)
        # "001_.cypher" has nothing after `_` — it should still not match
        # because our regex requires `.+` after the underscore
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Statement parsing
# ---------------------------------------------------------------------------


class TestParseStatements:
    """Tests for _parse_statements()."""

    def test_splits_on_semicolon(self) -> None:
        script = "CREATE (a:A);\nCREATE (b:B);"
        stmts = _parse_statements(script)
        assert len(stmts) == 2

    def test_strips_comments(self) -> None:
        script = "// comment\nCREATE (a:A);"
        stmts = _parse_statements(script)
        assert stmts == ["CREATE (a:A)"]

    def test_drops_empty_segments(self) -> None:
        script = "CREATE (a:A);;\n;// just a comment\n;"
        stmts = _parse_statements(script)
        assert stmts == ["CREATE (a:A)"]

    def test_real_migration_parses(self) -> None:
        """The real 001 migration file produces non-empty statements."""
        path = MIGRATIONS_DIR / "001_initial_schema.cypher"
        if not path.exists():
            pytest.skip("migration file not present")
        stmts = _parse_statements(path.read_text(encoding="utf-8"))
        assert len(stmts) >= 3  # at least the 3 UNIQUE constraints


# ---------------------------------------------------------------------------
# get_current_version
# ---------------------------------------------------------------------------


class TestGetCurrentVersion:
    """Tests for get_current_version()."""

    def test_returns_zero_when_no_node(self) -> None:
        driver = _make_mock_driver(current_version=0)
        assert get_current_version(driver) == 0

    def test_returns_stored_version(self) -> None:
        driver = _make_mock_driver(current_version=5)
        assert get_current_version(driver) == 5


# ---------------------------------------------------------------------------
# apply_migration
# ---------------------------------------------------------------------------


class TestApplyMigration:
    """Tests for apply_migration()."""

    def test_executes_statements_and_updates_version(self) -> None:
        driver = _make_mock_driver()
        session = driver.session.return_value.__enter__.return_value

        script = "CREATE CONSTRAINT foo IF NOT EXISTS FOR (n:A) REQUIRE n.id IS UNIQUE;"

        apply_migration(driver, version=1, script=script)

        # Should have run the DDL statement + the MERGE for version
        assert session.run.call_count == 2
        # First call: the DDL
        first_stmt = session.run.call_args_list[0][0][0]
        assert "CONSTRAINT" in first_stmt
        # Second call: the version update
        second_stmt = session.run.call_args_list[1][0][0]
        assert "MERGE" in second_stmt
        assert "_SchemaVersion" in second_stmt


# ---------------------------------------------------------------------------
# run_migrations
# ---------------------------------------------------------------------------


class TestRunMigrations:
    """Tests for run_migrations()."""

    def test_applies_pending_migrations(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(
            tmp_path,
            {
                "001_first.cypher": "CREATE (a:A);",
                "002_second.cypher": "CREATE (b:B);",
            },
        )
        driver = _make_mock_driver(current_version=0)
        applied = run_migrations(driver, migrations_dir=d)
        assert applied == [1, 2]

    def test_skips_already_applied(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(
            tmp_path,
            {
                "001_first.cypher": "CREATE (a:A);",
                "002_second.cypher": "CREATE (b:B);",
                "003_third.cypher": "CREATE (c:C);",
            },
        )
        driver = _make_mock_driver(current_version=2)
        applied = run_migrations(driver, migrations_dir=d)
        assert applied == [3]

    def test_nothing_to_apply(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(
            tmp_path,
            {"001_first.cypher": "CREATE (a:A);"},
        )
        driver = _make_mock_driver(current_version=1)
        applied = run_migrations(driver, migrations_dir=d)
        assert applied == []

    def test_empty_migrations_dir(self, tmp_path: pathlib.Path) -> None:
        d = _make_migration_dir(tmp_path, {})
        driver = _make_mock_driver(current_version=0)
        applied = run_migrations(driver, migrations_dir=d)
        assert applied == []

    def test_idempotent_rerun(self, tmp_path: pathlib.Path) -> None:
        """Running twice with same version should apply nothing the second time."""
        d = _make_migration_dir(
            tmp_path,
            {"001_first.cypher": "CREATE (a:A);"},
        )
        # First run — version 0, should apply
        driver1 = _make_mock_driver(current_version=0)
        applied1 = run_migrations(driver1, migrations_dir=d)
        assert applied1 == [1]

        # Second run — version already 1
        driver2 = _make_mock_driver(current_version=1)
        applied2 = run_migrations(driver2, migrations_dir=d)
        assert applied2 == []
