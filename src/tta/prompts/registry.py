"""Prompt registry protocol and template types.

Defines the contract for prompt template loading, rendering,
and validation (plans/prompts.md §1).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """A loaded prompt template with metadata and body."""

    id: str
    version: str = "1.0.0"
    role: str = "generation"
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_variables: list[str] = Field(default_factory=list)
    optional_variables: list[str] = Field(default_factory=list)
    body: str = ""


class RenderedPrompt(BaseModel):
    """Result of rendering a template with variables."""

    text: str
    template_id: str
    template_version: str
    token_estimate: int = 0
    fragment_versions: dict[str, str] = Field(default_factory=dict)
    prompt_hash: str = ""


class PromptRegistry(Protocol):
    """Protocol for prompt template registry.

    Implementations load templates from disk and render them
    with variable injection.
    """

    def get(self, template_id: str) -> PromptTemplate:
        """Get a template by ID. Raises KeyError if not found."""
        ...

    def render(
        self,
        template_id: str,
        variables: dict[str, Any],
    ) -> RenderedPrompt:
        """Render a template with the given variables.

        Raises KeyError if template not found.
        Raises ValueError if required variables are missing.
        """
        ...

    def list_templates(self) -> list[str]:
        """Return all registered template IDs."""
        ...

    def has(self, template_id: str) -> bool:
        """Check if a template ID is registered."""
        ...
