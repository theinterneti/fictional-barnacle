"""File-based Jinja2 prompt template registry.

Loads `.prompt.md` files from disk, parses YAML front matter,
and renders templates with variable injection (plans/prompts.md §2).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateSyntaxError,
    UndefinedError,
)

from tta.prompts.registry import PromptTemplate, RenderedPrompt

# Regex to split YAML front matter from body.
# Matches: ---\n<yaml>\n---\n<body>
_FRONT_MATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)

# Token estimation: ~1.3 tokens per word (rough English average).
_TOKENS_PER_WORD = 1.3


def _estimate_tokens(text: str) -> int:
    """Estimate token count from word count."""
    word_count = len(text.split())
    return int(word_count * _TOKENS_PER_WORD)


def _path_to_template_id(path: Path, templates_dir: Path) -> str:
    """Derive template ID from file path relative to templates dir.

    ``templates/narrative/generate.prompt.md`` → ``narrative.generate``
    """
    relative = path.relative_to(templates_dir)
    stem = relative.with_suffix("").with_suffix("")  # strip .prompt.md
    return str(stem).replace("/", ".").replace("\\", ".")


def _parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    """Split a `.prompt.md` file into YAML metadata dict and body string.

    Raises ``ValueError`` if the file has no valid front matter.
    """
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        raise ValueError(
            "Template file must start with YAML front matter "
            "delimited by --- markers"
        )
    yaml_text, body = match.group(1), match.group(2)
    metadata: dict[str, Any] = yaml.safe_load(yaml_text) or {}
    return metadata, body


class FilePromptRegistry:
    """In-memory prompt registry loaded from ``prompts/`` on disk.

    Implements the :class:`~tta.prompts.registry.PromptRegistry` protocol.
    """

    def __init__(
        self,
        templates_dir: Path,
        fragments_dir: Path | None = None,
    ) -> None:
        self._templates_dir = templates_dir
        self._fragments_dir = fragments_dir
        self._templates: dict[str, PromptTemplate] = {}
        self._jinja_env = self._create_jinja_env()
        self._load_templates()

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def get(self, template_id: str) -> PromptTemplate:
        """Return the template for *template_id*. Raises ``KeyError``."""
        try:
            return self._templates[template_id]
        except KeyError:
            available = ", ".join(sorted(self._templates)) or "(none)"
            raise KeyError(
                f"Unknown template '{template_id}'. "
                f"Available: {available}"
            ) from None

    def render(
        self,
        template_id: str,
        variables: dict[str, Any],
    ) -> RenderedPrompt:
        """Render *template_id* with *variables*.

        Raises ``KeyError`` if the template is not found.
        Raises ``ValueError`` if required variables are missing.
        """
        template = self.get(template_id)

        # Validate required variables before rendering.
        missing = [
            v for v in template.required_variables if v not in variables
        ]
        if missing:
            raise ValueError(
                f"Template '{template_id}' requires variables: "
                f"{missing}"
            )

        try:
            jinja_tpl = self._jinja_env.from_string(template.body)
            text = jinja_tpl.render(**variables)
        except UndefinedError as exc:
            raise ValueError(str(exc)) from exc

        return RenderedPrompt(
            text=text.strip(),
            template_id=template.id,
            template_version=template.version,
            token_estimate=_estimate_tokens(text),
        )

    def list_templates(self) -> list[str]:
        """Return sorted list of all registered template IDs."""
        return sorted(self._templates)

    def has(self, template_id: str) -> bool:
        """Return ``True`` if *template_id* is registered."""
        return template_id in self._templates

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_jinja_env(self) -> Environment:
        """Build a Jinja2 environment with fragment search path."""
        search_paths: list[str] = [str(self._templates_dir)]
        if self._fragments_dir and self._fragments_dir.is_dir():
            search_paths.append(str(self._fragments_dir))

        return Environment(
            loader=FileSystemLoader(search_paths),
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )

    def _load_templates(self) -> None:
        """Walk *templates_dir* and load every ``.prompt.md`` file."""
        if not self._templates_dir.is_dir():
            return

        for path in sorted(self._templates_dir.rglob("*.prompt.md")):
            self._load_template_file(path)

    def _load_template_file(self, path: Path) -> None:
        """Parse a single template file and register it."""
        content = path.read_text(encoding="utf-8")
        try:
            metadata, body = _parse_front_matter(content)
        except ValueError:
            # Derive a fallback ID for the error message.
            fallback_id = _path_to_template_id(path, self._templates_dir)
            raise ValueError(
                f"Invalid front matter in template '{fallback_id}' "
                f"({path})"
            ) from None

        # Template ID: prefer explicit `id` in front matter, fall back
        # to path-derived ID.
        template_id = metadata.get(
            "id",
            _path_to_template_id(path, self._templates_dir),
        )

        # Validate Jinja2 syntax early.
        try:
            self._jinja_env.parse(body)
        except TemplateSyntaxError as exc:
            raise ValueError(
                f"Jinja2 syntax error in template '{template_id}': {exc}"
            ) from exc

        template = PromptTemplate(
            id=template_id,
            version=str(metadata.get("version", "1.0.0")),
            role=metadata.get("role", "generation"),
            description=metadata.get("description", ""),
            parameters=metadata.get("parameters", {}),
            required_variables=metadata.get("required_variables", []),
            optional_variables=metadata.get("optional_variables", []),
            body=body,
        )
        self._templates[template_id] = template
