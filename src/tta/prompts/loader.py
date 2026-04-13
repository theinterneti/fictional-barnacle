"""File-based Jinja2 prompt template registry.

Loads ``.prompt.md`` files from disk, parses YAML front matter,
and renders templates with variable injection (plans/prompts.md §2).

Enhancements (Wave 28 / S09):
- Safety preamble auto-prepend for generation/classification roles (AC-09.8)
- Startup validation of required templates (AC-09.1)
- AST-based circular reference detection (AC-09.4)
- Fragment version tracking in rendered output (AC-09.4)
- Prompt injection logging (AC-09.8) — observe-only, no mutation
- Prompt hash for trace linkage (AC-09.7)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import structlog
import yaml
from jinja2 import (
    FileSystemLoader,
    StrictUndefined,
    TemplateSyntaxError,
    UndefinedError,
)
from jinja2.sandbox import SandboxedEnvironment

from tta.prompts.registry import PromptTemplate, RenderedPrompt

log = structlog.get_logger(__name__)

# Regex to split YAML front matter from body.
# Matches: ---\n<yaml>\n---\n<body>
_FRONT_MATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)

# Token estimation: ~1.3 tokens per word (rough English average).
_TOKENS_PER_WORD = 1.3

# Templates that must exist at startup (AC-09.1).
REQUIRED_TEMPLATES = frozenset(
    {
        "narrative.generate",
        "classification.intent",
        "extraction.world-changes",
    }
)

# Roles that receive the safety preamble (AC-09.8).
_PREAMBLE_ROLES = frozenset({"generation", "classification"})

# Patterns that suggest prompt injection attempts (AC-09.8, observe-only).
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("jinja_variable", re.compile(r"\{\{", re.IGNORECASE)),
    ("jinja_block", re.compile(r"\{%", re.IGNORECASE)),
    ("system_prefix", re.compile(r"(?:^|\n)\s*SYSTEM\s*:", re.IGNORECASE)),
    (
        "ignore_directive",
        re.compile(r"IGNORE\s+(?:ALL\s+)?PREVIOUS", re.IGNORECASE),
    ),
]


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
    """Split a ``.prompt.md`` file into YAML metadata dict and body string.

    Raises ``ValueError`` if the file has no valid front matter.
    """
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        raise ValueError(
            "Template file must start with YAML front matter delimited by --- markers"
        )
    yaml_text, body = match.group(1), match.group(2)
    metadata: dict[str, Any] = yaml.safe_load(yaml_text) or {}
    return metadata, body


def _hash_prompt(text: str) -> str:
    """Return a short SHA-256 hex digest of rendered prompt text."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def log_injection_signals(text: str, *, context: str = "") -> None:
    """Log a warning if *text* contains prompt-injection-like patterns.

    This is observe-only (AC-09.8): the text is never mutated.
    """
    for name, pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            log.warning(
                "prompt_injection_signal",
                pattern=name,
                context=context,
                snippet=text[:120],
            )


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
        self._fragment_versions: dict[str, str] = {}
        self._safety_preamble: str = ""
        self._jinja_env = self._create_jinja_env()
        self._load_fragments()
        self._load_templates()
        self._detect_circular_refs()

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
                f"Unknown template '{template_id}'. Available: {available}"
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
        missing = [v for v in template.required_variables if v not in variables]
        if missing:
            raise ValueError(f"Template '{template_id}' requires variables: {missing}")

        # Default optional variables to None so StrictUndefined doesn't
        # blow up on {% if optional_var %} checks.
        render_vars: dict[str, Any] = dict.fromkeys(template.optional_variables)
        render_vars.update(variables)

        try:
            jinja_tpl = self._jinja_env.from_string(template.body)
            text = jinja_tpl.render(**render_vars)
        except UndefinedError as exc:
            raise ValueError(str(exc)) from exc

        # Auto-prepend safety preamble for player-facing roles (AC-09.8).
        if self._safety_preamble and template.role in _PREAMBLE_ROLES:
            text = self._safety_preamble + "\n\n" + text

        text = text.strip()

        return RenderedPrompt(
            text=text,
            template_id=template.id,
            template_version=template.version,
            token_estimate=_estimate_tokens(text),
            fragment_versions=dict(self._fragment_versions),
            prompt_hash=_hash_prompt(text),
        )

    def list_templates(self) -> list[str]:
        """Return sorted list of all registered template IDs."""
        return sorted(self._templates)

    def has(self, template_id: str) -> bool:
        """Return ``True`` if *template_id* is registered."""
        return template_id in self._templates

    # ------------------------------------------------------------------
    # Startup validation (AC-09.1)
    # ------------------------------------------------------------------

    def validate_required_templates(
        self,
        required: frozenset[str] | None = None,
    ) -> None:
        """Verify all required templates are loaded and renderable.

        Raises ``RuntimeError`` on any failure so the app refuses to start.
        """
        required = required or REQUIRED_TEMPLATES
        missing = required - set(self._templates)
        if missing:
            raise RuntimeError(f"Missing required prompt templates: {sorted(missing)}")

        # Validate each required template can render with no variables
        # (since they are now system-instruction-only).
        errors: list[str] = []
        for tid in sorted(required):
            try:
                self.render(tid, {})
            except Exception as exc:
                errors.append(f"{tid}: {exc}")
        if errors:
            raise RuntimeError(
                "Required prompt templates failed validation:\n" + "\n".join(errors)
            )
        log.info(
            "prompt_templates_validated",
            count=len(required),
            ids=sorted(required),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_jinja_env(self) -> SandboxedEnvironment:
        """Build a sandboxed Jinja2 environment with fragment search path."""
        search_paths: list[str] = [str(self._templates_dir)]
        if self._fragments_dir and self._fragments_dir.is_dir():
            search_paths.append(str(self._fragments_dir))

        return SandboxedEnvironment(
            loader=FileSystemLoader(search_paths),
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )

    def _load_fragments(self) -> None:
        """Load fragment files and track their versions."""
        if not self._fragments_dir or not self._fragments_dir.is_dir():
            return

        for path in sorted(self._fragments_dir.rglob("*.fragment.md")):
            content = path.read_text(encoding="utf-8")
            fragment_name = path.stem.replace(".fragment", "")
            self._fragment_versions[fragment_name] = _hash_prompt(content)[:8]

            if fragment_name == "safety-preamble":
                self._safety_preamble = content.strip()
                log.debug("safety_preamble_loaded", chars=len(self._safety_preamble))

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
                f"Invalid front matter in template '{fallback_id}' ({path})"
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

    def _detect_circular_refs(self) -> None:
        """Use Jinja2 AST to detect circular ``{% include %}`` chains.

        Raises ``ValueError`` on the first cycle found (AC-09.4).
        """
        # Build reverse map: file path → template ID
        file_to_id: dict[str, str] = {}
        for tid in self._templates:
            # "narrative.generate" → "narrative/generate.prompt.md"
            file_path = tid.replace(".", "/") + ".prompt.md"
            file_to_id[file_path] = tid

        include_graph: dict[str, set[str]] = {}
        for tid, tpl in self._templates.items():
            raw_includes = self._extract_includes(tpl.body)
            # Normalize file paths to template IDs where possible
            includes = {file_to_id.get(inc, inc) for inc in raw_includes}
            include_graph[tid] = includes

        # DFS cycle detection
        visited: set[str] = set()
        path: list[str] = []

        def _dfs(node: str) -> None:
            if node in visited:
                return
            if node in path:
                cycle = " → ".join(path[path.index(node) :] + [node])
                raise ValueError(
                    f"Circular include detected in prompt templates: {cycle}"
                )
            path.append(node)
            for dep in include_graph.get(node, set()):
                _dfs(dep)
            path.pop()
            visited.add(node)

        for tid in include_graph:
            _dfs(tid)

    def _extract_includes(self, body: str) -> set[str]:
        """Parse Jinja2 AST to find ``{% include %}`` targets."""
        includes: set[str] = set()
        try:
            ast = self._jinja_env.parse(body)
        except TemplateSyntaxError:
            return includes

        from jinja2 import nodes as jinja_nodes

        for node in ast.find_all(jinja_nodes.Include):  # type: ignore[attr-defined]
            # node.template is a Const node with a string value
            # for literal includes.
            tmpl_node = getattr(node, "template", None)
            if tmpl_node and hasattr(tmpl_node, "value"):
                includes.add(str(tmpl_node.value))
        return includes
