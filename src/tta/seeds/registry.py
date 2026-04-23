from __future__ import annotations

from pathlib import Path

import structlog

from tta.seeds.manifest import (
    CompositionValidationError,
    SeedManifest,
    SeedSchemaError,
)
from tta.seeds.validator import SeedValidator

log = structlog.get_logger(__name__)


class SeedRegistry:
    """Loads and indexes scenario seeds from a directory of YAML files.

    Implements AC-41.01 through AC-41.05.
    """

    def __init__(self, seeds_dir: Path) -> None:
        self._seeds: dict[str, SeedManifest] = {}
        self._load(seeds_dir)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self, directory: Path) -> None:
        if not directory.exists():
            log.warning("seed_registry_dir_missing", path=str(directory))
            return
        validator = SeedValidator()
        collisions: set[str] = set()
        pending: dict[str, SeedManifest] = {}
        path_map: dict[str, Path] = {}
        for path in sorted(directory.rglob("*.yaml")):  # FR-41.01: recursive
            try:
                manifest = validator.load_and_validate(path)
            except (SeedSchemaError, CompositionValidationError) as exc:
                log.error(  # AC-41.04: error-level (not warning)
                    "seed_load_failed", file=str(path), reason=str(exc)
                )
                continue
            if manifest.id in collisions:
                log.error(  # AC-41.05: error naming both paths
                    "seed_collision",
                    seed_id=manifest.id,
                    file_a=str(path_map.get(manifest.id, "<unknown>")),
                    file_b=str(path),
                )
                continue
            if manifest.id in pending:
                first_path = path_map[manifest.id]
                log.error(  # AC-41.05: error naming both paths
                    "seed_collision",
                    seed_id=manifest.id,
                    file_a=str(first_path),
                    file_b=str(path),
                )
                del pending[manifest.id]
                collisions.add(manifest.id)
                continue
            pending[manifest.id] = manifest
            path_map[manifest.id] = path
        self._seeds = pending
        if not self._seeds:  # FR-41.02: critical when zero seeds loaded
            log.critical("seed_registry_empty", directory=str(directory))
        else:
            log.info("seed_registry_loaded", count=len(self._seeds))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, seed_id: str) -> SeedManifest | None:
        """Return the seed with *seed_id*, or ``None`` if not found."""
        return self._seeds.get(seed_id)

    def list(
        self,
        tags: list[str] | None = None,
        genre: str | None = None,
    ) -> list[SeedManifest]:
        """Return seeds matching any of *tags* and/or *genre*."""
        results = list(self._seeds.values())
        if tags:
            results = [s for s in results if any(t in s.tags for t in tags)]
        if genre:
            results = [s for s in results if s.composition.primary_genre == genre]
        return sorted(results, key=lambda s: s.id)  # AC-41.03: alphabetical

    def loaded_count(self) -> int:
        """Return the number of successfully loaded seeds."""
        return len(self._seeds)
