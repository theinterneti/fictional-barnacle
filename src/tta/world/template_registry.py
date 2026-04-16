"""Template registry — loads, validates, and selects templates."""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING

import structlog

from tta.models.world import WorldSeed, WorldTemplate
from tta.world.template_validator import (
    TemplateValidationError,
    validate_template,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger(__name__)


class TemplateRegistry:
    """Loads world templates from a directory and provides
    lookup and scoring-based selection.

    Templates are validated at init time (fail-fast).
    """

    def __init__(self, directory: Path) -> None:
        self._templates: dict[str, WorldTemplate] = {}
        self._directory = directory
        self._load_all()

    # ── Public API ───────────────────────────────────────────

    def select(self, world_seed: WorldSeed) -> WorldTemplate:
        """Score templates by tag overlap with the seed and
        return the best match.  Ties broken by random choice.
        """
        if not self._templates:
            msg = "No templates loaded"
            raise ValueError(msg)

        scored: list[tuple[int, WorldTemplate]] = []
        for tmpl in self._templates.values():
            score = self._score(tmpl, world_seed)
            scored.append((score, tmpl))

        max_score = max(s for s, _ in scored)
        best = [t for s, t in scored if s == max_score]

        chosen = random.choice(best)  # noqa: S311
        logger.info(
            "template_selected",
            template_key=chosen.metadata.template_key,
            score=max_score,
            candidates=len(best),
        )
        return chosen

    def select_by_preferences(
        self,
        preferences: dict[str, str],
    ) -> WorldTemplate:
        """Score templates by preference overlap without a WorldSeed.

        Breaks the circular dependency where WorldSeed requires a
        template, but template selection needs seed preferences.
        """
        if not self._templates:
            msg = "No templates loaded"
            raise ValueError(msg)

        scored: list[tuple[int, WorldTemplate]] = []
        for tmpl in self._templates.values():
            score = self._score_preferences(tmpl, preferences)
            scored.append((score, tmpl))

        max_score = max(s for s, _ in scored)
        best = [t for s, t in scored if s == max_score]

        chosen = random.choice(best)  # noqa: S311
        logger.info(
            "template_selected_by_preferences",
            template_key=chosen.metadata.template_key,
            score=max_score,
            candidates=len(best),
        )
        return chosen

    def get(self, template_key: str) -> WorldTemplate:
        """Direct lookup by template_key."""
        try:
            return self._templates[template_key]
        except KeyError:
            msg = f"Unknown template key: '{template_key}'"
            raise KeyError(msg) from None

    def list_all(self) -> list[WorldTemplate]:
        """Return all loaded templates."""
        return list(self._templates.values())

    # ── Private helpers ──────────────────────────────────────

    def _load_all(self) -> None:
        """Discover and load every .json file in the directory."""
        if not self._directory.is_dir():
            logger.warning(
                "template_dir_missing",
                path=str(self._directory),
            )
            return

        for path in sorted(self._directory.glob("*.json")):
            self._load_one(path)

        logger.info(
            "templates_loaded",
            count=len(self._templates),
            directory=str(self._directory),
        )

    def _load_one(self, path: Path) -> None:
        """Load a single template file, validate, and register."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            template = WorldTemplate.model_validate(raw)
            validate_template(template)
        except (
            json.JSONDecodeError,
            TemplateValidationError,
            Exception,
        ) as exc:
            logger.exception(
                "template_load_failed",
                path=str(path),
                error=str(exc),
            )
            raise

        key = template.metadata.template_key
        if key in self._templates:
            msg = f"Duplicate template_key '{key}' in {path}"
            raise TemplateValidationError(msg)

        self._templates[key] = template
        logger.debug(
            "template_registered",
            template_key=key,
            path=str(path),
        )

    @staticmethod
    def _score(
        template: WorldTemplate,
        seed: WorldSeed,
    ) -> int:
        """Score a template against a WorldSeed.

        +1 for each matching value in compatible_* lists.
        """
        meta = template.metadata
        score = 0

        if seed.tone and seed.tone in meta.compatible_tones:
            score += 1
        if seed.tech_level and seed.tech_level in meta.compatible_tech_levels:
            score += 1
        if seed.magic_presence and seed.magic_presence in meta.compatible_magic:
            score += 1
        if seed.world_scale and seed.world_scale in meta.compatible_scales:
            score += 1

        return score

    @staticmethod
    def _score_preferences(
        template: WorldTemplate,
        preferences: dict[str, str],
    ) -> int:
        """Score a template against a flat preferences dict.

        Same logic as ``_score`` but without requiring a WorldSeed.
        """
        meta = template.metadata
        score = 0

        tone = preferences.get("tone")
        if tone and tone in meta.compatible_tones:
            score += 1
        tech = preferences.get("tech_level")
        if tech and tech in meta.compatible_tech_levels:
            score += 1
        magic = preferences.get("magic_presence")
        if magic and magic in meta.compatible_magic:
            score += 1
        scale = preferences.get("world_scale")
        if scale and scale in meta.compatible_scales:
            score += 1

        return score
