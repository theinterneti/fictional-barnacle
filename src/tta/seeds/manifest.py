from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tta.universe.composition import UniverseComposition


class SeedSchemaError(ValueError):
    """Raised when a seed YAML fails structural or schema validation."""


class SeedCollisionError(ValueError):
    """Raised when two seeds share the same ID."""


class CompositionValidationError(ValueError):
    """Raised when a seed's composition block fails S39 validation."""


@dataclass(frozen=True)
class SeedManifest:
    """Immutable representation of a loaded scenario seed (S41 SS3)."""

    schema_version: str
    id: str
    name: str
    version: str
    description: str
    tags: tuple[str, ...]
    composition: UniverseComposition
    genesis_hints: dict[str, Any]
    intended_audience: tuple[str, ...]
