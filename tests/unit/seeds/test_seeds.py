"""Edge-case unit tests for S41 seeds (validator, registry, manifest)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tta.seeds.manifest import SeedSchemaError
from tta.seeds.validator import SeedValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_SEEDS = Path(__file__).resolve().parents[3] / "data" / "seeds"

_MINIMAL_VALID: dict[str, Any] = {
    "schema_version": "1.0",
    "id": "test-seed",
    "name": "Test Seed",
    "version": "1.0.0",
    "description": "A minimal valid seed for unit testing purposes.",
    "tags": ["mystery"],
    "composition": {
        "primary_genre": "urban_fantasy",
        "themes": [{"name": "liminal_space", "weight": 0.5}],
        "tropes": [],
        "archetypes": [],
        "genre_twists": [],
        "prose": {
            "voice": "second_person",
            "pacing": "slow",
            "description_density": "rich",
        },
        "tone": {"primary": "melancholic", "secondary": "wonder"},
    },
}


def _write_seed(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# SeedValidator — schema_version
# ---------------------------------------------------------------------------


class TestValidatorSchemaVersion:
    def test_wrong_version_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "schema_version": "2.0"}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="schema_version"):
            SeedValidator().load_and_validate(p)

    def test_correct_version_ok(self, tmp_path: Path) -> None:
        p = _write_seed(tmp_path / "s.yaml", _MINIMAL_VALID)
        m = SeedValidator().load_and_validate(p)
        assert m.schema_version == "1.0"


# ---------------------------------------------------------------------------
# SeedValidator — id rules
# ---------------------------------------------------------------------------


class TestValidatorId:
    def test_id_with_uppercase_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "id": "MyBadId"}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="id"):
            SeedValidator().load_and_validate(p)

    def test_id_with_underscore_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "id": "bad_id"}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="id"):
            SeedValidator().load_and_validate(p)

    def test_id_too_long_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "id": "a" * 65}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="id"):
            SeedValidator().load_and_validate(p)

    def test_id_exactly_64_chars_ok(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "id": "a" * 64}
        p = _write_seed(tmp_path / "s.yaml", data)
        m = SeedValidator().load_and_validate(p)
        assert len(m.id) == 64

    def test_id_with_digits_ok(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "id": "seed-42"}
        p = _write_seed(tmp_path / "s.yaml", data)
        m = SeedValidator().load_and_validate(p)
        assert m.id == "seed-42"


# ---------------------------------------------------------------------------
# SeedValidator — tags rules
# ---------------------------------------------------------------------------


class TestValidatorTags:
    def test_empty_tags_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "tags": []}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="tags"):
            SeedValidator().load_and_validate(p)

    def test_eleven_tags_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "tags": [f"tag-{i}" for i in range(11)]}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="tags"):
            SeedValidator().load_and_validate(p)

    def test_ten_tags_ok(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "tags": [f"tag-{i}" for i in range(10)]}
        p = _write_seed(tmp_path / "s.yaml", data)
        m = SeedValidator().load_and_validate(p)
        assert len(m.tags) == 10

    def test_tags_not_list_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "tags": "mystery"}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="tags"):
            SeedValidator().load_and_validate(p)


# ---------------------------------------------------------------------------
# SeedValidator — description rules
# ---------------------------------------------------------------------------


class TestValidatorDescription:
    def test_short_description_raises(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "description": "Short"}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError, match="description"):
            SeedValidator().load_and_validate(p)

    def test_minimum_description_ok(self, tmp_path: Path) -> None:
        data = {**_MINIMAL_VALID, "description": "1234567890"}  # exactly 10
        p = _write_seed(tmp_path / "s.yaml", data)
        m = SeedValidator().load_and_validate(p)
        assert m.description == "1234567890"


# ---------------------------------------------------------------------------
# SeedValidator — required fields
# ---------------------------------------------------------------------------


class TestValidatorRequiredFields:
    @pytest.mark.parametrize(
        "missing",
        [
            "schema_version",
            "id",
            "name",
            "version",
            "description",
            "tags",
            "composition",
        ],
    )
    def test_missing_required_field_raises(self, tmp_path: Path, missing: str) -> None:
        data = {k: v for k, v in _MINIMAL_VALID.items() if k != missing}
        p = _write_seed(tmp_path / "s.yaml", data)
        with pytest.raises(SeedSchemaError):
            SeedValidator().load_and_validate(p)


# ---------------------------------------------------------------------------
# SeedValidator — bad YAML
# ---------------------------------------------------------------------------


class TestValidatorBadYaml:
    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "s.yaml"
        p.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(SeedSchemaError, match="mapping"):
            SeedValidator().load_and_validate(p)

    def test_invalid_yaml_syntax_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "s.yaml"
        p.write_text("id: [unclosed bracket\n", encoding="utf-8")
        with pytest.raises(SeedSchemaError, match="Cannot parse"):
            SeedValidator().load_and_validate(p)


# ---------------------------------------------------------------------------
# SeedRegistry — missing directory
# ---------------------------------------------------------------------------


class TestRegistryMissingDir:
    def test_nonexistent_dir_logs_warning_not_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        missing = tmp_path / "no_such_dir"
        with caplog.at_level(logging.WARNING, logger="tta.seeds.registry"):
            from tta.seeds.registry import SeedRegistry

            reg = SeedRegistry(missing)
        assert reg.loaded_count() == 0
        # Should warn, but not crash
        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "seed_registry_dir_missing" in m or "missing" in m.lower()
            for m in warn_msgs
        )


# ---------------------------------------------------------------------------
# SeedRegistry — zero seeds → CRITICAL log
# ---------------------------------------------------------------------------


class TestRegistryEmpty:
    def test_empty_dir_logs_critical(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        empty = tmp_path / "empty"
        empty.mkdir()
        with caplog.at_level(logging.CRITICAL, logger="tta.seeds.registry"):
            from tta.seeds.registry import SeedRegistry

            reg = SeedRegistry(empty)
        assert reg.loaded_count() == 0
        crit_msgs = [r.message for r in caplog.records if r.levelno == logging.CRITICAL]
        assert crit_msgs, "Expected CRITICAL log for empty registry"


# ---------------------------------------------------------------------------
# Canonical seeds — spot checks
# ---------------------------------------------------------------------------


class TestCanonicalSeeds:
    def test_dirty_frodo_tags_portal_not_strange_mundane(self) -> None:
        from tta.seeds.registry import SeedRegistry

        reg = SeedRegistry(DATA_SEEDS)
        m = reg.get("dirty-frodo")
        assert m is not None
        assert "portal" in m.tags
        assert "strange-mundane" not in m.tags

    def test_all_seeds_have_immutable_tags(self) -> None:
        from tta.seeds.registry import SeedRegistry

        reg = SeedRegistry(DATA_SEEDS)
        for m in reg.list():
            assert isinstance(m.tags, tuple)
