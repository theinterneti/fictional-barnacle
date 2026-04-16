"""Golden snapshot tests for prompt templates (AC-09.5).

Render each template with known inputs and verify structural properties
of the output. These tests catch regressions in template content,
front-matter metadata, and composition behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tta.prompts.loader import FilePromptRegistry

TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "prompts" / "templates"
FRAGMENTS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "fragments"


@pytest.fixture
def registry() -> FilePromptRegistry:
    return FilePromptRegistry(
        templates_dir=TEMPLATES_DIR,
        fragments_dir=FRAGMENTS_DIR if FRAGMENTS_DIR.is_dir() else None,
    )


class TestNarrativeGenerate:
    """Golden tests for narrative.generate template."""

    def test_renders_without_variables(self, registry: FilePromptRegistry) -> None:
        result = registry.render("narrative.generate", {})
        assert result.text
        assert result.template_version == "1.2.0"

    def test_contains_core_instructions(self, registry: FilePromptRegistry) -> None:
        result = registry.render("narrative.generate", {})
        text = result.text.lower()
        assert "second-person" in text
        assert "present-tense" in text or "present tense" in text
        assert "100" in result.text
        assert "200" in result.text

    def test_tone_variable_renders(self, registry: FilePromptRegistry) -> None:
        result = registry.render("narrative.generate", {"tone": "melancholic"})
        assert "melancholic" in result.text

    def test_word_range_overridable(self, registry: FilePromptRegistry) -> None:
        result = registry.render(
            "narrative.generate",
            {"word_min": "50", "word_max": "150"},
        )
        assert "50" in result.text
        assert "150" in result.text

    def test_metadata_correct(self, registry: FilePromptRegistry) -> None:
        tpl = registry.get("narrative.generate")
        assert tpl.role == "generation"
        assert tpl.required_variables == []
        assert "tone" in tpl.optional_variables

    def test_prompt_hash_stable(self, registry: FilePromptRegistry) -> None:
        r1 = registry.render("narrative.generate", {})
        r2 = registry.render("narrative.generate", {})
        assert r1.prompt_hash == r2.prompt_hash

    def test_prompt_hash_changes_with_variables(
        self, registry: FilePromptRegistry
    ) -> None:
        r1 = registry.render("narrative.generate", {})
        r2 = registry.render("narrative.generate", {"tone": "eerie"})
        assert r1.prompt_hash != r2.prompt_hash


class TestClassificationIntent:
    """Golden tests for classification.intent template."""

    def test_renders_without_variables(self, registry: FilePromptRegistry) -> None:
        result = registry.render("classification.intent", {})
        assert result.text
        assert result.template_version == "1.1.0"

    def test_contains_all_intent_categories(self, registry: FilePromptRegistry) -> None:
        result = registry.render("classification.intent", {})
        for category in ("move", "examine", "talk", "use", "meta", "other"):
            assert category in result.text.lower()

    def test_classification_role(self, registry: FilePromptRegistry) -> None:
        tpl = registry.get("classification.intent")
        assert tpl.role == "classification"

    def test_low_temperature(self, registry: FilePromptRegistry) -> None:
        tpl = registry.get("classification.intent")
        assert tpl.parameters.get("temperature", 1.0) <= 0.2


class TestExtractionWorldChanges:
    """Golden tests for extraction.world-changes template."""

    def test_renders_without_variables(self, registry: FilePromptRegistry) -> None:
        result = registry.render("extraction.world-changes", {})
        assert result.text
        assert result.template_version == "1.1.0"

    def test_specifies_json_format(self, registry: FilePromptRegistry) -> None:
        result = registry.render("extraction.world-changes", {})
        assert "world_changes" in result.text
        assert "suggested_actions" in result.text
        assert "JSON" in result.text

    def test_extraction_role(self, registry: FilePromptRegistry) -> None:
        tpl = registry.get("extraction.world-changes")
        assert tpl.role == "extraction"

    def test_low_temperature(self, registry: FilePromptRegistry) -> None:
        tpl = registry.get("extraction.world-changes")
        assert tpl.parameters.get("temperature", 1.0) <= 0.2


class TestCrossTemplate:
    """Cross-template structural checks."""

    def test_all_required_templates_registered(
        self, registry: FilePromptRegistry
    ) -> None:
        for tid in [
            "narrative.generate",
            "classification.intent",
            "extraction.world-changes",
        ]:
            assert registry.has(tid), f"Missing required template: {tid}"

    def test_all_templates_have_version(self, registry: FilePromptRegistry) -> None:
        for tid in registry.list_templates():
            tpl = registry.get(tid)
            assert tpl.version, f"{tid} has no version"

    def test_fragment_versions_populated(self, registry: FilePromptRegistry) -> None:
        result = registry.render("narrative.generate", {})
        assert isinstance(result.fragment_versions, dict)

    def test_token_estimates_reasonable(self, registry: FilePromptRegistry) -> None:
        for tid in registry.list_templates():
            result = registry.render(tid, {})
            assert 10 < result.token_estimate < 5000, (
                f"{tid} token estimate out of range: {result.token_estimate}"
            )
