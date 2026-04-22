"""Migration validation script for v2 Universe schema (AC-33.10).

Validates that migration 011 applied correctly:
- All four new tables exist with expected columns
- game_sessions has universe_id and actors columns
- Backfill counts are non-negative and consistent
- All game_sessions rows have actors = '[]' or a non-null list

Usage:
    uv run python scripts/migrate_validate_v2.py

Exit code 0 = all checks pass.
Exit code 1 = one or more checks failed.
"""

import sys
from typing import Any

import sqlalchemy as sa


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"  OK    {msg}")


def _check(conn: Any, label: str, query: str, expect: Any) -> bool:
    result = conn.execute(sa.text(query)).scalar()
    if result != expect:
        _fail(f"{label}: expected {expect!r}, got {result!r}")
        return False
    _ok(label)
    return True


def _check_gt(conn: Any, label: str, query: str, minimum: int) -> bool:
    result = conn.execute(sa.text(query)).scalar()
    if result is None or result < minimum:
        _fail(f"{label}: expected >= {minimum}, got {result!r}")
        return False
    _ok(label)
    return True


def validate(url: str) -> bool:
    engine = sa.create_engine(url)
    passed = True

    with engine.connect() as conn:
        print("\n── Table existence ──")
        for table in ("universes", "actors", "character_states", "universe_snapshots"):
            ok = _check(
                conn,
                f"table {table} exists",
                f"SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema='public' AND table_name='{table}'",
                1,
            )
            passed = passed and ok

        print("\n── game_sessions columns ──")
        for col in ("universe_id", "actors"):
            ok = _check(
                conn,
                f"game_sessions.{col} exists",
                f"SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_name='game_sessions' AND column_name='{col}'",
                1,
            )
            passed = passed and ok

        print("\n── Backfill consistency ──")
        # Every game_session that has a universe_id points to an existing universe
        bad_fk = conn.execute(
            sa.text("""
            SELECT COUNT(*) FROM game_sessions gs
            WHERE gs.universe_id IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM universes u WHERE u.id = gs.universe_id)
            """)
        ).scalar()
        if bad_fk and bad_fk > 0:
            _fail(f"game_sessions with dangling universe_id FK: {bad_fk}")
            passed = False
        else:
            _ok("No dangling universe_id FKs on game_sessions")

        # Every actor has a corresponding player
        bad_actors = conn.execute(
            sa.text("""
            SELECT COUNT(*) FROM actors a
            WHERE NOT EXISTS (SELECT 1 FROM players p WHERE p.id = a.player_id)
            """)
        ).scalar()
        if bad_actors and bad_actors > 0:
            _fail(f"actors with missing player_id: {bad_actors}")
            passed = False
        else:
            _ok("All actors have valid player_id references")

        # character_states UNIQUE constraint sanity
        dupes = conn.execute(
            sa.text("""
            SELECT COUNT(*) FROM (
                SELECT actor_id, universe_id, COUNT(*) AS n
                FROM character_states
                GROUP BY actor_id, universe_id
                HAVING COUNT(*) > 1
            ) dup
            """)
        ).scalar()
        if dupes and dupes > 0:
            _fail(
                f"character_states has {dupes} duplicate (actor_id, universe_id) pairs"
            )
            passed = False
        else:
            _ok("character_states has no duplicate (actor_id, universe_id) pairs")

        print("\n── Actors default column ──")
        null_actors = conn.execute(
            sa.text("SELECT COUNT(*) FROM game_sessions WHERE actors IS NULL")
        ).scalar()
        if null_actors and null_actors > 0:
            _fail(f"game_sessions with NULL actors column: {null_actors}")
            passed = False
        else:
            _ok("All game_sessions.actors are non-NULL")

    engine.dispose()
    return passed


def main() -> None:
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    print(f"Validating migration 011 at: {url.split('@')[-1]}")
    ok = validate(url)
    if ok:
        print("\n✅  Migration 011 validation PASSED")
        sys.exit(0)
    else:
        print(
            "\n❌  Migration 011 validation FAILED — see errors above", file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
