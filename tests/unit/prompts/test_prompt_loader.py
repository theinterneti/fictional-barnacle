"""Unit tests for the file-based prompt template registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from tta.prompts.loader import FilePromptRegistry, _estimate_tokens


# ---------------------------------------------------------------------------
# Helpers — create template / fragment files inside tmp_path
# ---------------------------------------------------------------------------

_MINIMAL_TEMPLATE = """\
---
id: test.minimal
version: "1.0.0"
role: generation
description: A minimal test template
required_variables:
  - name
optional_variables:
  - greeting
---
Hello, {{ name }}!
{% if greeting %}{{ greeting }}{% endif %}
"""

_NO_OPTIONALS_TEMPLATE = """\
---
id: test.required-only
version: "2.0.0"
role: classification
description: Template with only required vars
required_variables:
  - query
---
Classify: {{ query }}
"""


def _write_template(
    templates_dir: Path,
    rel_path: str,
    content: str,
) -> Path:
    """Write a template file under *templates_dir*."""
    path = templates_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_fragment(
    fragments_dir: Path,
    filename: str,
    content: str,
) -> Path:
    """Write a fragment file under *fragments_dir*."""
    fragments_dir.mkdir(parents=True, exist_ok=True)
    path = fragments_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def template_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Return (templates_dir, fragments_dir) under tmp_path."""
    templates = tmp_path / "templates"
    fragments = tmp_path / "fragments"
    templates.mkdir()
    fragments.mkdir()
    return templates, fragments


# ---------------------------------------------------------------------------
# Loading & parsing
# ---------------------------------------------------------------------------


class TestTemplateLoading:
    """Test loading templates from disk."""

    def test_load_single_template(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "greet/hello.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        tpl = registry.get("test.minimal")
        assert tpl.id == "test.minimal"
        assert tpl.version == "1.0.0"
        assert tpl.role == "generation"
        assert tpl.description == "A minimal test template"

    def test_load_multiple_templates(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "a/one.prompt.md", _MINIMAL_TEMPLATE
        )
        _write_template(
            templates_dir, "b/two.prompt.md", _NO_OPTIONALS_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        assert len(registry.list_templates()) == 2

    def test_path_derived_id_used_when_no_explicit_id(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        """When ``id`` is missing from front matter, derive from path."""
        templates_dir, fragments_dir = template_dirs
        content = """\
---
version: "1.0.0"
role: generation
description: No explicit id
required_variables: []
---
Body text.
"""
        _write_template(
            templates_dir, "narrative/generate.prompt.md", content
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)
        assert registry.has("narrative.generate")

    def test_empty_templates_dir(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        registry = FilePromptRegistry(templates_dir, fragments_dir)
        assert registry.list_templates() == []


class TestYamlFrontMatter:
    """Test YAML front matter parsing."""

    def test_required_variables_parsed(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        tpl = registry.get("test.minimal")
        assert tpl.required_variables == ["name"]

    def test_optional_variables_parsed(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        tpl = registry.get("test.minimal")
        assert tpl.optional_variables == ["greeting"]

    def test_parameters_parsed(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        content = """\
---
id: test.params
version: "1.0.0"
role: generation
description: Has parameters
parameters:
  temperature: 0.85
  max_tokens: 512
required_variables: []
---
Body.
"""
        _write_template(templates_dir, "p/t.prompt.md", content)
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        tpl = registry.get("test.params")
        assert tpl.parameters["temperature"] == 0.85
        assert tpl.parameters["max_tokens"] == 512

    def test_invalid_front_matter_raises(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir,
            "bad/template.prompt.md",
            "No front matter here\nJust body.",
        )
        with pytest.raises(ValueError, match="front matter"):
            FilePromptRegistry(templates_dir, fragments_dir)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRendering:
    """Test Jinja2 rendering with variables."""

    def test_render_with_required_variables(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        result = registry.render("test.minimal", {"name": "Alice"})
        assert "Hello, Alice!" in result.text
        assert result.template_id == "test.minimal"
        assert result.template_version == "1.0.0"

    def test_render_with_optional_variables(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        result = registry.render(
            "test.minimal",
            {"name": "Bob", "greeting": "Welcome!"},
        )
        assert "Hello, Bob!" in result.text
        assert "Welcome!" in result.text

    def test_render_optional_absent_is_ok(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        """Optional variables not provided → conditional block skipped."""
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        result = registry.render("test.minimal", {"name": "Eve"})
        assert "Hello, Eve!" in result.text

    def test_missing_required_variable_raises(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        with pytest.raises(ValueError, match="requires variables"):
            registry.render("test.minimal", {})


# ---------------------------------------------------------------------------
# get / has / list_templates / KeyError
# ---------------------------------------------------------------------------


class TestRegistryLookup:
    """Test get, has, and list_templates."""

    def test_get_unknown_template_raises(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        with pytest.raises(KeyError, match="Unknown template"):
            registry.get("nonexistent.template")

    def test_render_unknown_template_raises(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        with pytest.raises(KeyError, match="Unknown template"):
            registry.render("nope", {})

    def test_has_returns_true_for_loaded(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        assert registry.has("test.minimal") is True

    def test_has_returns_false_for_missing(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        assert registry.has("nope") is False

    def test_list_templates_returns_sorted_ids(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "b/z.prompt.md", _NO_OPTIONALS_TEMPLATE
        )
        _write_template(
            templates_dir, "a/y.prompt.md", _MINIMAL_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        ids = registry.list_templates()
        assert ids == sorted(ids)
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


class TestTokenEstimation:
    """Test token estimation on rendered prompts."""

    def test_token_estimate_set_on_rendered(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs
        _write_template(
            templates_dir, "x/y.prompt.md", _NO_OPTIONALS_TEMPLATE
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        result = registry.render(
            "test.required-only", {"query": "hello world"}
        )
        assert result.token_estimate > 0

    def test_estimate_tokens_formula(self) -> None:
        """Word count * 1.3 rounded down."""
        assert _estimate_tokens("one two three") == 3  # 3 * 1.3 = 3.9 → 3
        assert _estimate_tokens("word") == 1  # 1 * 1.3 = 1.3 → 1

    def test_empty_string_zero_tokens(self) -> None:
        assert _estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# Fragment inclusion
# ---------------------------------------------------------------------------


class TestFragmentInclusion:
    """Test Jinja2 fragment includes."""

    def test_include_fragment(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        templates_dir, fragments_dir = template_dirs

        _write_fragment(
            fragments_dir,
            "test-preamble.fragment.md",
            "SAFETY: Be safe.\n",
        )

        template_with_include = """\
---
id: test.with-include
version: "1.0.0"
role: generation
description: Uses a fragment
required_variables:
  - name
---
{% include "test-preamble.fragment.md" %}
Hello, {{ name }}.
"""
        _write_template(
            templates_dir,
            "inc/t.prompt.md",
            template_with_include,
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        result = registry.render("test.with-include", {"name": "Zara"})
        assert "SAFETY: Be safe." in result.text
        assert "Hello, Zara." in result.text

    def test_missing_fragment_raises(
        self, template_dirs: tuple[Path, Path]
    ) -> None:
        """Including a nonexistent fragment raises at render time."""
        templates_dir, fragments_dir = template_dirs

        template_bad_include = """\
---
id: test.bad-include
version: "1.0.0"
role: generation
description: Broken include
required_variables: []
---
{% include "nonexistent.fragment.md" %}
Body.
"""
        _write_template(
            templates_dir,
            "bad/inc.prompt.md",
            template_bad_include,
        )
        registry = FilePromptRegistry(templates_dir, fragments_dir)

        with pytest.raises(Exception):  # noqa: B017
            registry.render("test.bad-include", {})


# ---------------------------------------------------------------------------
# Real templates (integration-ish, still unit since no external deps)
# ---------------------------------------------------------------------------


class TestRealTemplates:
    """Smoke-test the actual prompt template files shipped with TTA."""

    @pytest.fixture()
    def real_registry(self) -> FilePromptRegistry:
        repo_root = Path(__file__).resolve().parents[3]
        templates_dir = repo_root / "prompts" / "templates"
        fragments_dir = repo_root / "prompts" / "fragments"
        return FilePromptRegistry(templates_dir, fragments_dir)

    def test_v1_required_templates_loaded(
        self, real_registry: FilePromptRegistry
    ) -> None:
        assert real_registry.has("narrative.generate")
        assert real_registry.has("classification.intent")
        assert real_registry.has("extraction.world-changes")

    def test_render_narrative_generate(
        self, real_registry: FilePromptRegistry
    ) -> None:
        result = real_registry.render(
            "narrative.generate",
            {
                "player_input": "look around",
                "world_context": "A dark forest clearing.",
            },
        )
        assert "dark forest clearing" in result.text
        assert "look around" in result.text
        assert result.token_estimate > 0
        assert result.template_version == "1.0.0"

    def test_render_classification_intent(
        self, real_registry: FilePromptRegistry
    ) -> None:
        result = real_registry.render(
            "classification.intent",
            {"player_input": "go north"},
        )
        assert "go north" in result.text

    def test_render_extraction_world_changes(
        self, real_registry: FilePromptRegistry
    ) -> None:
        result = real_registry.render(
            "extraction.world-changes",
            {
                "narrative_text": "The door creaks open.",
                "current_world_state": "Door is closed.",
            },
        )
        assert "door" in result.text.lower()
