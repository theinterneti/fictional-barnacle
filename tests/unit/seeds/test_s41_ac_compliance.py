"""Spec AC compliance tests for S41 — Scenario Seed Library.

Each test is decorated with @pytest.mark.spec("AC-41.XX") per the
AC traceability standard (spec/tool-ac-traceability.md).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from tta.seeds.registry import SeedRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATA_SEEDS = Path(__file__).resolve().parents[3] / "data" / "seeds"


@pytest.fixture()
def seed_registry() -> SeedRegistry:
    """Return a SeedRegistry loaded from the canonical data/seeds/ directory."""
    return SeedRegistry(DATA_SEEDS)


@pytest.fixture()
def invalid_seed_dir(tmp_path: Path, seed_registry: SeedRegistry) -> Path:
    """A temp directory with 3 valid seeds + 1 invalid (missing composition)."""
    valid_dir = DATA_SEEDS
    dest = tmp_path / "seeds"
    dest.mkdir()
    # Copy the three strange-mundane seeds as valid fixtures
    for name in (
        "bus-stop-shimmer.yaml",
        "cafe-with-strange-symbols.yaml",
        "library-forbidden-book.yaml",
    ):
        (dest / name).write_text(
            (valid_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    # Write an invalid seed (missing required field: composition)
    bad: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "bad-seed",
        "name": "Bad Seed",
        "version": "1.0.0",
        "description": "A seed with no composition block.",
        "tags": ["mystery"],
        # 'composition' intentionally omitted
    }
    (dest / "bad-seed.yaml").write_text(yaml.dump(bad), encoding="utf-8")
    return dest


@pytest.fixture()
def collision_seed_dir(tmp_path: Path) -> Path:
    """A temp directory where two files share the same seed id."""
    valid_dir = DATA_SEEDS
    dest = tmp_path / "seeds"
    dest.mkdir()
    original = (valid_dir / "bus-stop-shimmer.yaml").read_text(encoding="utf-8")
    (dest / "bus-stop-shimmer.yaml").write_text(original, encoding="utf-8")
    (dest / "bus-stop-shimmer-copy.yaml").write_text(original, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# AC-41.01 — All canonical seeds load without error
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-41.01")
def test_all_canonical_seeds_load(seed_registry: SeedRegistry) -> None:
    """SeedRegistry.loaded_count() == 4 for the canonical data/seeds/ dir."""
    assert seed_registry.loaded_count() == 4


@pytest.mark.spec("AC-41.01")
def test_canonical_seeds_no_error_logs(
    seed_registry: SeedRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    """No ERROR-level logs are emitted during canonical seed loading."""
    with caplog.at_level(logging.ERROR, logger="tta.seeds.registry"):
        SeedRegistry(DATA_SEEDS)
    assert not caplog.records, (
        f"Expected no errors, got: {[r.message for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# AC-41.02 — Lookup by ID returns correct seed
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-41.02")
def test_get_by_id_returns_manifest(seed_registry: SeedRegistry) -> None:
    """get('bus-stop-shimmer') returns a manifest with the expected id."""
    manifest = seed_registry.get("bus-stop-shimmer")
    assert manifest is not None
    assert manifest.id == "bus-stop-shimmer"


@pytest.mark.spec("AC-41.02")
def test_get_by_id_correct_genre(seed_registry: SeedRegistry) -> None:
    """The returned manifest has composition.primary_genre == 'urban_fantasy'."""
    manifest = seed_registry.get("bus-stop-shimmer")
    assert manifest is not None
    assert manifest.composition.primary_genre == "urban_fantasy"


@pytest.mark.spec("AC-41.02")
def test_get_unknown_id_returns_none(seed_registry: SeedRegistry) -> None:
    """get() returns None for an unknown id."""
    assert seed_registry.get("does-not-exist") is None


# ---------------------------------------------------------------------------
# AC-41.03 — Filter by tag returns only matching seeds
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-41.03")
def test_list_by_tag_strange_mundane(seed_registry: SeedRegistry) -> None:
    """list(tags=['strange-mundane']) returns exactly the 3 matching seeds."""
    results = seed_registry.list(tags=["strange-mundane"])
    ids = [m.id for m in results]
    assert len(results) == 3
    assert "bus-stop-shimmer" in ids
    assert "cafe-with-strange-symbols" in ids
    assert "library-forbidden-book" in ids


@pytest.mark.spec("AC-41.03")
def test_list_by_tag_excludes_dirty_frodo(seed_registry: SeedRegistry) -> None:
    """dirty-frodo is NOT returned when filtering for 'strange-mundane'."""
    results = seed_registry.list(tags=["strange-mundane"])
    ids = [m.id for m in results]
    assert "dirty-frodo" not in ids


@pytest.mark.spec("AC-41.03")
def test_list_results_are_sorted(seed_registry: SeedRegistry) -> None:
    """list() returns seeds sorted alphabetically by id."""
    results = seed_registry.list()
    ids = [m.id for m in results]
    assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# AC-41.04 — Invalid seed file is excluded from registry
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-41.04")
def test_invalid_seed_excluded(invalid_seed_dir: Path) -> None:
    """A seed with a missing required field is excluded from the registry."""
    registry = SeedRegistry(invalid_seed_dir)
    assert registry.get("bad-seed") is None
    assert registry.loaded_count() == 3


@pytest.mark.spec("AC-41.04")
def test_invalid_seed_logs_error(
    invalid_seed_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Loading an invalid seed emits an ERROR log naming the file."""
    with caplog.at_level(logging.ERROR, logger="tta.seeds.registry"):
        SeedRegistry(invalid_seed_dir)
    error_msgs = [r.message for r in caplog.records if r.levelno == logging.ERROR]
    assert any("bad-seed" in msg for msg in error_msgs), (
        f"Expected error naming 'bad-seed', got: {error_msgs}"
    )


@pytest.mark.spec("AC-41.04")
def test_valid_seeds_survive_invalid_peer(invalid_seed_dir: Path) -> None:
    """The 3 valid seeds are still available after one invalid seed is rejected."""
    registry = SeedRegistry(invalid_seed_dir)
    for seed_id in (
        "bus-stop-shimmer",
        "cafe-with-strange-symbols",
        "library-forbidden-book",
    ):
        assert registry.get(seed_id) is not None


# ---------------------------------------------------------------------------
# AC-41.05 — Duplicate seed ID rejects both
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-41.05")
def test_collision_both_seeds_excluded(collision_seed_dir: Path) -> None:
    """Both seeds sharing an id are excluded from the registry."""
    registry = SeedRegistry(collision_seed_dir)
    assert registry.get("bus-stop-shimmer") is None
    assert registry.loaded_count() == 0


@pytest.mark.spec("AC-41.05")
def test_collision_logs_both_paths(
    collision_seed_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The collision error log names both conflicting file paths."""
    with caplog.at_level(logging.ERROR, logger="tta.seeds.registry"):
        SeedRegistry(collision_seed_dir)
    error_msgs = " ".join(
        r.message for r in caplog.records if r.levelno == logging.ERROR
    )
    assert "bus-stop-shimmer.yaml" in error_msgs
    assert "bus-stop-shimmer-copy.yaml" in error_msgs


# ---------------------------------------------------------------------------
# AC-41.06 — Seed applied to universe composition at Genesis
# ---------------------------------------------------------------------------


@pytest.mark.spec("AC-41.06")
def test_apply_seed_composition_sets_composition(seed_registry: SeedRegistry) -> None:
    """apply_seed_composition populates config['composition'] from the seed."""
    from tta.genesis.genesis_v2 import apply_seed_composition

    config: dict[str, Any] = {"genesis": {"seed_id": "bus-stop-shimmer"}}
    apply_seed_composition(config, seed_registry)
    assert "composition" in config
    assert config["composition"]["seed_id"] == "bus-stop-shimmer"
    assert config["composition"]["seed_version"] == "1.0.0"


@pytest.mark.spec("AC-41.06")
def test_apply_seed_composition_no_seed_id_is_noop(
    seed_registry: SeedRegistry,
) -> None:
    """apply_seed_composition does nothing when seed_id is absent."""
    from tta.genesis.genesis_v2 import apply_seed_composition

    config: dict[str, Any] = {"genesis": {}}
    apply_seed_composition(config, seed_registry)
    assert "composition" not in config


@pytest.mark.spec("AC-41.06")
def test_apply_seed_composition_unknown_id_is_noop(
    seed_registry: SeedRegistry,
) -> None:
    """apply_seed_composition does nothing (logs warning) for unknown seed_id."""
    from tta.genesis.genesis_v2 import apply_seed_composition

    config: dict[str, Any] = {"genesis": {"seed_id": "no-such-seed"}}
    apply_seed_composition(config, seed_registry)
    assert "composition" not in config
