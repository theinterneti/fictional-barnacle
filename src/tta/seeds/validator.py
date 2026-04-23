from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tta.seeds.manifest import (
    CompositionValidationError,
    SeedManifest,
    SeedSchemaError,
)
from tta.universe.composition import CompositionValidator, UniverseComposition

_REQUIRED_FIELDS = {
    "schema_version",
    "id",
    "name",
    "version",
    "description",
    "tags",
    "composition",
}
_MIN_DESCRIPTION_LEN = 10
_ID_PATTERN = re.compile(r"^[a-z0-9-]+$")
_MAX_ID_LEN = 64
_SCHEMA_VERSION = "1.0"
_MAX_TAGS = 10


class SeedValidator:
    """Parses and validates a single seed YAML file (AC-41.04/05)."""

    def load_and_validate(self, path: Path) -> SeedManifest:
        """Load *path* and return a validated :class:`SeedManifest`.

        Raises :class:`SeedSchemaError` or
        :class:`CompositionValidationError` on invalid input.
        """
        raw = self._load_yaml(path)
        self._check_required(raw, path)
        self._check_schema_version(raw, path)
        self._check_id(raw, path)
        self._check_description(raw, path)
        self._check_tags(raw, path)
        comp = self._validate_composition(raw, path)
        return SeedManifest(
            schema_version=str(raw["schema_version"]),
            id=str(raw["id"]),
            name=str(raw["name"]),
            version=str(raw["version"]),
            description=str(raw["description"]),
            tags=tuple(str(t) for t in raw["tags"]),
            composition=comp,
            genesis_hints=dict(raw.get("genesis_hints", {})),
            intended_audience=tuple(str(a) for a in raw.get("intended_audience", [])),
        )

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SeedSchemaError(f"Cannot parse YAML at {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SeedSchemaError(
                f"Seed at {path} must be a YAML mapping, got {type(data).__name__}"
            )
        return data

    def _check_required(self, raw: dict[str, Any], path: Path) -> None:
        missing = _REQUIRED_FIELDS - raw.keys()
        if missing:
            raise SeedSchemaError(
                f"Seed at {path} is missing required fields: {sorted(missing)}"
            )

    def _check_description(self, raw: dict[str, Any], path: Path) -> None:
        desc = str(raw.get("description", "")).strip()
        if len(desc) < _MIN_DESCRIPTION_LEN:
            raise SeedSchemaError(
                f"Seed at {path}: description must be at least"
                f" {_MIN_DESCRIPTION_LEN} chars, got {len(desc)}"
            )

    def _check_schema_version(self, raw: dict[str, Any], path: Path) -> None:
        ver = str(raw.get("schema_version", ""))
        if ver != _SCHEMA_VERSION:
            raise SeedSchemaError(
                f"Seed at {path}: schema_version must be {_SCHEMA_VERSION!r},"
                f" got {ver!r}"
            )

    def _check_id(self, raw: dict[str, Any], path: Path) -> None:
        seed_id = str(raw.get("id", ""))
        if not _ID_PATTERN.match(seed_id):
            raise SeedSchemaError(
                f"Seed at {path}: id {seed_id!r} must match [a-z0-9-]+"
            )
        if len(seed_id) > _MAX_ID_LEN:
            raise SeedSchemaError(
                f"Seed at {path}: id must be at most {_MAX_ID_LEN} chars,"
                f" got {len(seed_id)}"
            )

    def _check_tags(self, raw: dict[str, Any], path: Path) -> None:
        tags = raw.get("tags", [])
        if not isinstance(tags, list):
            raise SeedSchemaError(f"Seed at {path}: tags must be a list")
        if len(tags) < 1:
            raise SeedSchemaError(f"Seed at {path}: tags must have at least 1 entry")
        if len(tags) > _MAX_TAGS:
            raise SeedSchemaError(
                f"Seed at {path}: tags must have at most {_MAX_TAGS} entries,"
                f" got {len(tags)}"
            )

    def _validate_composition(
        self, raw: dict[str, Any], path: Path
    ) -> UniverseComposition:
        comp_raw = raw.get("composition", {})
        loc = f" (in {path.name})"
        try:
            comp = UniverseComposition.from_config({"composition": comp_raw})
        except Exception as exc:
            raise CompositionValidationError(
                f"Composition parse failed{loc}: {exc}"
            ) from exc
        errors = CompositionValidator().validate(comp)
        if errors:
            raise CompositionValidationError(
                f"Composition validation failed{loc}: {';'.join(errors)}"
            )
        return comp
