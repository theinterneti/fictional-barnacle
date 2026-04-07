"""Tests for TemplateRegistry — loading, selection, and lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tta.models.world import (
    WorldSeed,
    WorldTemplate,
)
from tta.world.template_registry import TemplateRegistry
from tta.world.template_validator import TemplateValidationError

# ── Helpers ──────────────────────────────────────────────────────

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "tta" / "world" / "templates"
)


def _minimal_template_dict(
    key: str = "test_tmpl",
    *,
    tones: list[str] | None = None,
    tech: list[str] | None = None,
    magic: list[str] | None = None,
    scales: list[str] | None = None,
) -> dict:
    """Return the smallest valid template as a dict."""
    return {
        "metadata": {
            "template_key": key,
            "display_name": f"Test {key}",
            "tags": [],
            "compatible_tones": tones or [],
            "compatible_tech_levels": tech or [],
            "compatible_magic": magic or [],
            "compatible_scales": scales or [],
            "location_count": 1,
            "npc_count": 0,
        },
        "regions": [{"key": "r1", "archetype": "test"}],
        "locations": [
            {
                "key": "loc1",
                "region_key": "r1",
                "type": "interior",
                "archetype": "test",
                "is_starting_location": True,
            }
        ],
        "connections": [],
        "npcs": [],
        "items": [],
        "knowledge": [],
    }


def _write_template(
    directory: Path,
    filename: str,
    data: dict,
) -> Path:
    path = directory / filename
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _make_seed(
    template: WorldTemplate | None = None,
    *,
    tone: str | None = None,
    tech_level: str | None = None,
    magic_presence: str | None = None,
    world_scale: str | None = None,
) -> WorldSeed:
    """Build a WorldSeed for testing."""
    if template is None:
        template = WorldTemplate.model_validate(_minimal_template_dict())
    return WorldSeed(
        template=template,
        tone=tone,
        tech_level=tech_level,
        magic_presence=magic_presence,
        world_scale=world_scale,
    )


# ── Loading tests ────────────────────────────────────────────────


class TestRegistryLoading:
    def test_load_bundled_templates(self) -> None:
        # Arrange / Act
        registry = TemplateRegistry(TEMPLATES_DIR)

        # Assert
        templates = registry.list_all()
        assert len(templates) >= 2

    def test_load_from_empty_dir(self, tmp_path: Path) -> None:
        # Arrange / Act
        registry = TemplateRegistry(tmp_path)

        # Assert
        assert registry.list_all() == []

    def test_load_from_missing_dir(self, tmp_path: Path) -> None:
        # Arrange
        missing = tmp_path / "nope"

        # Act
        registry = TemplateRegistry(missing)

        # Assert
        assert registry.list_all() == []

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        # Arrange
        (tmp_path / "bad.json").write_text("NOT JSON", encoding="utf-8")

        # Act / Assert
        with pytest.raises(json.JSONDecodeError):
            TemplateRegistry(tmp_path)

    def test_invalid_template_raises(self, tmp_path: Path) -> None:
        # Arrange — valid JSON but fails validation (no
        # locations)
        data = _minimal_template_dict()
        data["locations"] = []
        _write_template(tmp_path, "bad.json", data)

        # Act / Assert
        with pytest.raises(TemplateValidationError):
            TemplateRegistry(tmp_path)

    def test_duplicate_template_key_raises(self, tmp_path: Path) -> None:
        # Arrange — two files with same template_key
        d1 = _minimal_template_dict("same_key")
        d2 = _minimal_template_dict("same_key")
        _write_template(tmp_path, "a.json", d1)
        _write_template(tmp_path, "b.json", d2)

        # Act / Assert
        with pytest.raises(TemplateValidationError):
            TemplateRegistry(tmp_path)


# ── get() tests ──────────────────────────────────────────────────


class TestRegistryGet:
    def test_get_known_key(self) -> None:
        # Arrange
        registry = TemplateRegistry(TEMPLATES_DIR)

        # Act
        tmpl = registry.get("quiet_village")

        # Assert
        assert tmpl.metadata.template_key == "quiet_village"

    def test_get_unknown_key_raises(self) -> None:
        # Arrange
        registry = TemplateRegistry(TEMPLATES_DIR)

        # Act / Assert
        with pytest.raises(KeyError, match="Unknown template"):
            registry.get("nonexistent")


# ── select() tests ───────────────────────────────────────────────


class TestRegistrySelect:
    def test_select_with_no_templates_raises(self, tmp_path: Path) -> None:
        # Arrange
        registry = TemplateRegistry(tmp_path)
        seed = _make_seed()

        # Act / Assert
        with pytest.raises(ValueError, match="No templates"):
            registry.select(seed)

    def test_select_best_match(self, tmp_path: Path) -> None:
        # Arrange — tmpl_a matches tone+tech, tmpl_b only tone
        d_a = _minimal_template_dict("tmpl_a", tones=["dark"], tech=["medieval"])
        d_b = _minimal_template_dict("tmpl_b", tones=["dark"], tech=["futuristic"])
        _write_template(tmp_path, "a.json", d_a)
        _write_template(tmp_path, "b.json", d_b)
        registry = TemplateRegistry(tmp_path)

        seed = _make_seed(tone="dark", tech_level="medieval")

        # Act
        result = registry.select(seed)

        # Assert
        assert result.metadata.template_key == "tmpl_a"

    def test_select_returns_template(self, tmp_path: Path) -> None:
        # Arrange
        d = _minimal_template_dict("only")
        _write_template(tmp_path, "only.json", d)
        registry = TemplateRegistry(tmp_path)
        seed = _make_seed()

        # Act
        result = registry.select(seed)

        # Assert
        assert isinstance(result, WorldTemplate)
        assert result.metadata.template_key == "only"

    def test_select_with_all_none_seed(self, tmp_path: Path) -> None:
        # Arrange — all seed fields None → every template
        # scores 0
        d = _minimal_template_dict("fallback")
        _write_template(tmp_path, "f.json", d)
        registry = TemplateRegistry(tmp_path)
        seed = _make_seed()

        # Act
        result = registry.select(seed)

        # Assert
        assert result.metadata.template_key == "fallback"

    def test_select_scores_all_four_axes(self, tmp_path: Path) -> None:
        # Arrange — one template matches all 4 axes
        d_full = _minimal_template_dict(
            "full",
            tones=["dark"],
            tech=["medieval"],
            magic=["rare"],
            scales=["intimate"],
        )
        d_partial = _minimal_template_dict(
            "partial",
            tones=["dark"],
            tech=["futuristic"],
            magic=["none"],
            scales=["epic"],
        )
        _write_template(tmp_path, "full.json", d_full)
        _write_template(tmp_path, "partial.json", d_partial)
        registry = TemplateRegistry(tmp_path)

        seed = _make_seed(
            tone="dark",
            tech_level="medieval",
            magic_presence="rare",
            world_scale="intimate",
        )

        # Act
        result = registry.select(seed)

        # Assert — full matches 4, partial matches 1
        assert result.metadata.template_key == "full"


# ── list_all() tests ─────────────────────────────────────────────


class TestRegistryListAll:
    def test_list_all_returns_all(self, tmp_path: Path) -> None:
        # Arrange
        for i in range(3):
            d = _minimal_template_dict(f"t{i}")
            _write_template(tmp_path, f"t{i}.json", d)
        registry = TemplateRegistry(tmp_path)

        # Act
        result = registry.list_all()

        # Assert
        assert len(result) == 3
        keys = {t.metadata.template_key for t in result}
        assert keys == {"t0", "t1", "t2"}
