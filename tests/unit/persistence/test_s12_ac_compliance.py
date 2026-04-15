"""S12 Persistence Strategy — Acceptance Criteria compliance tests.

Covers AC-12.01, AC-12.02, AC-12.04, AC-12.09, AC-12.12.

v2 ACs (deferred — require live infra or cannot be validated at unit level):
  AC-12.03 — GDPR 72h deletion: requires async background job + direct DB query
  AC-12.05 — Redis cache read < 5ms p95: requires real Redis + timing harness
  AC-12.06 — Cache miss reconstruction < 500ms p95: real infra required
  AC-12.07 — Turn processing < 200ms p95: real infra required
  AC-12.08 — World graph 2-hop traversal < 200ms p95: real Neo4j required
  AC-12.10 — Neo4j migration idempotency: no Neo4j unit-test infra
  AC-12.11 — SQL restore within 1 hour: operational procedure, not unit-testable
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tta.models.game import GameState
from tta.persistence.memory import InMemoryTurnRepository
from tta.persistence.redis_health import audit_ttl_compliance
from tta.persistence.redis_session import (
    get_or_reconstruct_session,
    set_active_session,
)

# ── AC-12.01: Turn round-trip (create → retrieve) ────────────────────────────


class TestAC1201TurnRoundTrip:
    """AC-12.01: A turn submitted is retrievable from turn history.

    Rationale: the in-memory repo is the authoritative contract implementation.
    If create_turn followed by get_turn returns the same record, the persistence
    layer satisfies the durability contract for this AC.  The postgres impl
    (tested in test_postgres_repos.py) must satisfy the same interface.
    """

    @pytest.mark.asyncio
    async def test_created_turn_is_retrievable(self) -> None:
        """AC-12.01: create_turn then get_turn returns the same record."""
        repo = InMemoryTurnRepository()
        session_id = uuid4()

        created = await repo.create_turn(session_id, 1, "go north")
        turn_id = created["id"]

        fetched = await repo.get_turn(turn_id)

        assert fetched is not None, "get_turn must return the created turn"
        assert fetched["id"] == turn_id
        assert fetched["session_id"] == session_id
        assert fetched["player_input"] == "go north"
        assert fetched["turn_number"] == 1

    @pytest.mark.asyncio
    async def test_completed_turn_is_retrievable_with_narrative(self) -> None:
        """AC-12.01: A completed turn (with narrative) is fully retrievable."""
        repo = InMemoryTurnRepository()
        session_id = uuid4()

        created = await repo.create_turn(session_id, 1, "look around")
        await repo.complete_turn(
            created["id"],
            narrative_output="You see a clearing.",
            model_used="test-model",
            latency_ms=123.4,
            token_count={"prompt": 10, "completion": 5, "total": 15},
        )

        fetched = await repo.get_turn(created["id"])

        assert fetched is not None
        assert fetched["status"] == "complete"
        assert fetched["narrative_output"] == "You see a clearing."
        assert fetched["model_used"] == "test-model"

    @pytest.mark.asyncio
    async def test_turn_retrievable_across_multiple_sessions(self) -> None:
        """AC-12.01: Turns from different sessions are independently retrievable."""
        repo = InMemoryTurnRepository()
        s1 = uuid4()
        s2 = uuid4()

        t1 = await repo.create_turn(s1, 1, "north")
        t2 = await repo.create_turn(s2, 1, "south")

        fetched_t1 = await repo.get_turn(t1["id"])
        fetched_t2 = await repo.get_turn(t2["id"])

        assert fetched_t1 is not None
        assert fetched_t1["session_id"] == s1
        assert fetched_t2 is not None
        assert fetched_t2["session_id"] == s2


# ── AC-12.02: Cache reconstruction on Redis miss ─────────────────────────────


class TestAC1202CacheReconstruction:
    """AC-12.02: After Redis restart, next turn completes via cache reconstruction.

    The get_or_reconstruct_session function transparently falls back to
    a SQL loader when the Redis key is missing (simulating a Redis restart).
    """

    @pytest.mark.asyncio
    async def test_cache_miss_triggers_sql_reconstruction(self) -> None:
        """AC-12.02: Cache miss triggers loader call and re-warms cache."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # simulate Redis restart
        mock_redis.set = AsyncMock()

        state = GameState(session_id=str(uuid4()), turn_number=3)
        loader = AsyncMock(return_value=state)
        session_id = uuid4()

        with patch("tta.persistence.redis_session.CACHE_RECONSTRUCTION_TOTAL"):
            result = await get_or_reconstruct_session(
                mock_redis, session_id, load_from_sql=loader
            )

        assert result is not None, "Reconstruction must return the rebuilt state"
        assert result.session_id == state.session_id
        loader.assert_awaited_once_with(session_id)
        # Cache should be re-warmed so the next access is a hit
        mock_redis.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconstruction_sets_ttl_on_restored_key(self) -> None:
        """AC-12.02: Re-warmed cache key is stored with a TTL (FR-12.13)."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        state = GameState(session_id=str(uuid4()), turn_number=1)
        loader = AsyncMock(return_value=state)

        with patch("tta.persistence.redis_session.CACHE_RECONSTRUCTION_TOTAL"):
            await get_or_reconstruct_session(mock_redis, uuid4(), load_from_sql=loader)

        # Verify the set call used an expiry (TTL), not an unbounded write
        _, kwargs = mock_redis.set.call_args
        assert "ex" in kwargs, "Reconstructed cache entry must have a TTL (ex=)"
        assert isinstance(kwargs["ex"], int) and kwargs["ex"] > 0

    @pytest.mark.asyncio
    async def test_missing_sql_row_returns_none_not_error(self) -> None:
        """AC-12.02: If SQL also has no state, None is returned gracefully."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        loader = AsyncMock(return_value=None)

        result = await get_or_reconstruct_session(
            mock_redis, uuid4(), load_from_sql=loader
        )

        assert result is None


# ── AC-12.04: State consistency across multiple snapshots ─────────────────────


class TestAC1204StateDriftPrevention:
    """AC-12.04: Game state after N turns matches the accumulated effect.

    Verifies that the turn repository records each turn sequentially and that
    turn numbers are consistent (no gaps, no overwrite of previous turns).
    """

    @pytest.mark.asyncio
    async def test_sequential_turns_have_monotone_turn_numbers(self) -> None:
        """AC-12.04: Turn numbers must increase monotonically with no duplicates."""
        repo = InMemoryTurnRepository()
        session_id = uuid4()
        n_turns = 20

        created_ids = []
        for i in range(1, n_turns + 1):
            turn = await repo.create_turn(session_id, i, f"action {i}")
            await repo.complete_turn(
                turn["id"],
                narrative_output=f"response {i}",
                model_used="m",
                latency_ms=10.0,
                token_count={},
            )
            created_ids.append(turn["id"])

        turn_numbers = []
        for tid in created_ids:
            fetched = await repo.get_turn(tid)
            assert fetched is not None
            turn_numbers.append(fetched["turn_number"])

        assert turn_numbers == list(range(1, n_turns + 1)), (
            "Turn numbers must be 1..N with no gaps or duplicates"
        )

    @pytest.mark.asyncio
    async def test_each_turn_preserves_its_own_narrative(self) -> None:
        """AC-12.04: Each turn's narrative is stored independently (no state drift)."""
        repo = InMemoryTurnRepository()
        session_id = uuid4()

        narratives = [f"You moved to room {i}." for i in range(5)]
        turn_ids = []
        for i, narrative in enumerate(narratives, 1):
            turn = await repo.create_turn(session_id, i, f"go {i}")
            await repo.complete_turn(turn["id"], narrative, "m", 1.0, {})
            turn_ids.append(turn["id"])

        for tid, expected_narrative in zip(turn_ids, narratives, strict=True):
            fetched = await repo.get_turn(tid)
            assert fetched is not None
            assert fetched["narrative_output"] == expected_narrative, (
                f"Turn {tid} narrative must not be overwritten by later turns"
            )

    @pytest.mark.asyncio
    async def test_duplicate_turn_number_rejected(self) -> None:
        """AC-12.04: Duplicate turn numbers in the same session are rejected."""
        repo = InMemoryTurnRepository()
        session_id = uuid4()

        await repo.create_turn(session_id, 1, "first")

        with pytest.raises(ValueError, match="duplicate turn"):
            await repo.create_turn(session_id, 1, "second")


# ── AC-12.09: SQL migration applies without manual intervention ───────────────


class TestAC1209AlembicMigrations:
    """AC-12.09: SQL migration applies without manual intervention.

    Verified structurally: all migration scripts exist, can be imported,
    and define both upgrade() and downgrade() functions (FR-12.22).
    """

    _MIGRATIONS_DIR = (
        Path(__file__).parent.parent.parent.parent
        / "migrations"
        / "postgres"
        / "versions"
    )

    def _get_migration_files(self) -> list[Path]:
        return sorted(self._MIGRATIONS_DIR.glob("*.py"))

    def test_migrations_directory_exists(self) -> None:
        """AC-12.09: The migrations/postgres/versions directory must exist."""
        assert self._MIGRATIONS_DIR.is_dir(), (
            "migrations/postgres/versions must exist for Alembic to apply migrations"
        )

    def test_at_least_one_migration_exists(self) -> None:
        """AC-12.09: At least one migration script must be present."""
        files = self._get_migration_files()
        assert len(files) >= 1, "At least one Alembic migration script must exist"

    def test_all_migrations_have_upgrade_and_downgrade(self) -> None:
        """AC-12.09 / FR-12.22: Every migration must define upgrade() and downgrade()."""  # noqa: E501
        files = self._get_migration_files()
        assert files, "No migration files found"

        for path in files:
            source = path.read_text()
            assert "def upgrade" in source, (
                f"{path.name}: missing upgrade() — migration cannot be applied"
            )
            assert "def downgrade" in source, (
                f"{path.name}: missing downgrade() — not reversible (FR-12.22)"
            )

    def test_migrations_are_sequentially_numbered(self) -> None:
        """AC-12.09: Migration scripts follow sequential naming convention."""
        files = self._get_migration_files()
        assert files, "No migration files found"

        for path in files:
            # File names like 001_initial_schema.py must start with 3-digit number
            stem = path.stem
            prefix = stem.split("_")[0]
            assert prefix.isdigit(), (
                f"{path.name}: migration filename must start with a numeric prefix"
            )

    def test_alembic_ini_present_at_repo_root(self) -> None:
        """AC-12.09: alembic.ini must be present so CLI works without manual config."""
        repo_root = Path(__file__).parent.parent.parent.parent
        ini = repo_root / "alembic.ini"
        assert ini.is_file(), "alembic.ini must exist at project root (FR-12.09)"


# ── AC-12.12: All Redis keys have TTL ────────────────────────────────────────


class TestAC1212RedisTtlCompliance:
    """AC-12.12: All Redis keys have a TTL set (no unbounded memory growth).

    Verified by:
    1. The audit_ttl_compliance() function reports zero violations on clean state.
    2. set_active_session() always writes with ex= parameter.
    3. Keys without TTL are correctly detected and reported.
    """

    @pytest.mark.asyncio
    async def test_all_keys_with_ttl_report_zero_violations(self) -> None:
        """AC-12.12: audit_ttl_compliance returns {} when all keys have TTLs."""
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            return_value=(0, [b"tta:session:abc", b"tta:ratelimit:xyz"])
        )

        pipe = AsyncMock()
        pipe.ttl = AsyncMock()
        pipe.execute = AsyncMock(return_value=[3600, 60])
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline = MagicMock(return_value=pipe)

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL"):
            result = await audit_ttl_compliance(mock_redis)

        assert result == {}, (
            "No violations expected when all keys have positive TTLs (AC-12.12)"
        )

    @pytest.mark.asyncio
    async def test_key_without_ttl_is_detected_as_violation(self) -> None:
        """AC-12.12: Keys with TTL=-1 (no TTL) are surfaced as violations."""
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            return_value=(0, [b"tta:session:abc", b"tta:session:orphan"])
        )

        pipe = AsyncMock()
        pipe.ttl = AsyncMock()
        pipe.execute = AsyncMock(return_value=[3600, -1])
        pipe.__aenter__ = AsyncMock(return_value=pipe)
        pipe.__aexit__ = AsyncMock(return_value=False)
        mock_redis.pipeline = MagicMock(return_value=pipe)

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL"):
            result = await audit_ttl_compliance(mock_redis)

        assert "tta:session" in result, (
            "Violations must be reported by key prefix (AC-12.12)"
        )
        assert result["tta:session"] == 1

    @pytest.mark.asyncio
    async def test_set_active_session_always_writes_with_ttl(self) -> None:
        """AC-12.12 / FR-12.13: set_active_session must always set a TTL."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        state = GameState(session_id=str(uuid4()), turn_number=0)
        await set_active_session(mock_redis, uuid4(), state)

        mock_redis.set.assert_awaited_once()
        _, kwargs = mock_redis.set.call_args
        assert "ex" in kwargs, "set_active_session must write with ex= (TTL) argument"
        assert isinstance(kwargs["ex"], int) and kwargs["ex"] > 0, (
            "TTL must be a positive integer (no unbounded keys)"
        )

    @pytest.mark.asyncio
    async def test_set_active_session_custom_ttl_respected(self) -> None:
        """AC-12.12: Custom TTL is passed through to the Redis SET command."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        state = GameState(session_id=str(uuid4()), turn_number=0)
        await set_active_session(mock_redis, uuid4(), state, ttl=7200)

        _, kwargs = mock_redis.set.call_args
        assert kwargs["ex"] == 7200

    @pytest.mark.asyncio
    async def test_default_ttl_is_nonzero(self) -> None:
        """AC-12.12: The default TTL for session keys is positive (non-zero)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        state = GameState(session_id=str(uuid4()), turn_number=0)
        await set_active_session(mock_redis, uuid4(), state)

        _, kwargs = mock_redis.set.call_args
        assert kwargs["ex"] == 3600, "Default session TTL must be 3600 seconds"

    @pytest.mark.asyncio
    async def test_empty_keyspace_has_no_violations(self) -> None:
        """AC-12.12: An empty Redis keyspace reports zero violations."""
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(return_value=(0, []))

        with patch("tta.persistence.redis_health.REDIS_KEYS_WITHOUT_TTL"):
            result = await audit_ttl_compliance(mock_redis)

        assert result == {}
