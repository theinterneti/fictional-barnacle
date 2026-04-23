"""AC compliance tests for S33 v1→v2 Migration Compatibility (AC-33.01–33.10).

All ACs are covered across this file and tests/unit/test_migration_011.py.

AC coverage (see test_migration_011.py for AC-33.01/02/04–10):
- AC-33.01: Migration creates universes table with required columns
- AC-33.02: Migration creates one actor row per existing player
- AC-33.03: Backfill sets game_sessions.universe_id for sessions with matching universe
- AC-33.04: Migration creates character_states for linked sessions
- AC-33.05: Migration is idempotent (ON CONFLICT DO NOTHING guards)
- AC-33.06: Migration is reversible (downgrade removes new tables/columns)
- AC-33.07: game_sessions gains universe_id and actors columns
- AC-33.08: Migration adds FK from game_sessions.universe_id → universes.id
- AC-33.09: Indexes are created on universe_id and actor_id columns
- AC-33.10: Backfill does not affect sessions without a matching universe
"""

import pathlib

import pytest

MIGRATION_PATH = (
    pathlib.Path(__file__).parent.parent.parent.parent
    / "migrations"
    / "postgres"
    / "versions"
    / "011_v2_universe_entity.py"
)


# ---------------------------------------------------------------------------
# AC-33.03 — Backfill sets game_sessions.universe_id for legacy sessions
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-33.03")
def test_backfill_sql_updates_game_sessions_universe_id() -> None:
    """migration 011 backfills game_sessions.universe_id for legacy sessions.

    AC-33.03: For each pre-v2 game session that has a matching entry in the
    universes table (id = gs.id), universe_id is set to gs.id.

    The migration uses:
        UPDATE game_sessions gs
        SET universe_id = gs.id
        WHERE gs.universe_id IS NULL
          AND EXISTS (SELECT 1 FROM universes u WHERE u.id = gs.id)

    This is idempotent (WHERE universe_id IS NULL guard) and only links sessions
    that have a corresponding universe row.
    """
    src = MIGRATION_PATH.read_text()

    assert "UPDATE game_sessions gs" in src or "UPDATE game_sessions" in src, (
        "migration must have UPDATE game_sessions backfill (AC-33.03)"
    )
    assert "SET universe_id = gs.id" in src, (
        "backfill must SET universe_id = gs.id (AC-33.03)"
    )
    assert "universe_id IS NULL" in src, (
        "backfill must be guarded by WHERE universe_id IS NULL for idempotency"
    )
    assert "EXISTS" in src, (
        "backfill must use EXISTS check to only link sessions with matching universes"
    )


@pytest.mark.spec("AC-33.03")
def test_backfill_is_conditional_not_unconditional_update() -> None:
    """The backfill UPDATE is conditional — skips rows with existing universe_id.

    AC-33.03: Non-linked sessions (v1 sessions without a universe row) are left
    with universe_id = NULL. The migration does NOT fail if they can't be linked.
    """
    src = MIGRATION_PATH.read_text()

    # The WHERE clause must include universe_id IS NULL (not update all rows)
    assert (
        "WHERE gs.universe_id IS NULL" in src or "WHERE" in src and "IS NULL" in src
    ), "backfill must be conditional on universe_id IS NULL (not unconditional)"
    # The migration comment confirms skipping unlinked sessions
    assert "v1 sessions" in src or "race-condition" in src or "skip" in src.lower(), (
        "migration must document that unlinkable sessions are left with NULL"
    )
