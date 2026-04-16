"""Neo4j versioned migration runner.

Discovers numbered Cypher scripts in ``migrations/neo4j/``, tracks the
current schema version via a ``_SchemaVersion`` node, and applies only
pending migrations in order.

Usage::

    python -m tta.world.migrate
"""

from __future__ import annotations

import logging
import pathlib
import re
import sys
from datetime import UTC, datetime
from typing import LiteralString, cast

from neo4j import Driver, GraphDatabase

logger = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d{3})_.+\.cypher$")

MIGRATIONS_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent.parent
    / "migrations"
    / "neo4j"
)


def _discover_migrations(
    directory: pathlib.Path,
) -> list[tuple[int, pathlib.Path]]:
    """Return sorted ``(version, path)`` pairs for all migration files."""
    results: list[tuple[int, pathlib.Path]] = []
    if not directory.is_dir():
        return results
    for entry in sorted(directory.iterdir()):
        m = _MIGRATION_RE.match(entry.name)
        if m:
            results.append((int(m.group(1)), entry))
    return results


def get_current_version(driver: Driver) -> int:
    """Read the ``_SchemaVersion`` node and return its version (0 if absent)."""
    with driver.session() as session:
        result = session.run(
            "MATCH (v:_SchemaVersion {id: 'current'}) RETURN v.version AS ver"
        )
        record = result.single()
        return int(record["ver"]) if record else 0


def apply_migration(
    driver: Driver,
    version: int,
    script: str,
) -> None:
    """Execute a Cypher migration script then bump ``_SchemaVersion``.

    Each statement is executed in its own implicit transaction because
    Neo4j does not allow DDL (schema changes) and DML in the same
    explicit transaction.
    """
    statements = _parse_statements(script)

    with driver.session() as session:
        for stmt in statements:
            # Migrations are loaded from files — cast is safe here
            session.run(cast("LiteralString", stmt))

        session.run(
            """
            MERGE (v:_SchemaVersion {id: 'current'})
            SET v.version = $version, v.applied_at = $now
            """,
            version=version,
            now=datetime.now(UTC).isoformat(),
        )


def _parse_statements(script: str) -> list[str]:
    """Split a Cypher script on ``;`` and drop blanks / comment-only lines."""
    stmts: list[str] = []
    for raw in script.split(";"):
        cleaned = "\n".join(
            line
            for line in raw.strip().splitlines()
            if line.strip() and not line.strip().startswith("//")
        )
        if cleaned:
            stmts.append(cleaned)
    return stmts


def run_migrations(
    driver: Driver,
    migrations_dir: pathlib.Path | None = None,
) -> list[int]:
    """Apply all pending migrations. Return the list of applied versions."""
    if migrations_dir is None:
        migrations_dir = MIGRATIONS_DIR

    current = get_current_version(driver)
    pending = [
        (ver, path)
        for ver, path in _discover_migrations(migrations_dir)
        if ver > current
    ]

    applied: list[int] = []
    for ver, path in pending:
        logger.info("Applying migration %03d: %s", ver, path.name)
        script = path.read_text(encoding="utf-8")
        apply_migration(driver, ver, script)
        applied.append(ver)

    if not applied:
        logger.info("Schema is up-to-date at version %d", current)
    else:
        logger.info(
            "Applied %d migration(s), now at version %d",
            len(applied),
            applied[-1],
        )

    return applied


def main() -> None:
    """CLI entry-point: load settings, connect, migrate."""
    from tta.config import get_settings

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = get_settings()
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        applied = run_migrations(driver)
        if applied:
            logger.info("Done — applied versions: %s", applied)
        else:
            logger.info("Nothing to do.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
    sys.exit(0)
