"""Model role definitions and per-role configuration for LLM routing."""

from enum import StrEnum

from pydantic import BaseModel


class ModelRole(StrEnum):
    """Semantic role that determines which model to use."""

    GENERATION = "generation"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    SUMMARIZATION = "summarization"


class ModelRoleConfig(BaseModel):
    """Per-role model configuration with fallback chain."""

    primary: str
    fallback: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout_seconds: float = 30.0


# Default role configurations (plans/llm-and-pipeline.md §1.3)
DEFAULT_ROLE_CONFIGS: dict[ModelRole, ModelRoleConfig] = {
    ModelRole.GENERATION: ModelRoleConfig(
        primary="anthropic/claude-sonnet-4-20250514",
        fallback="anthropic/claude-haiku-4-20250514",
        temperature=0.85,
        max_tokens=1024,
        timeout_seconds=90.0,
    ),
    ModelRole.CLASSIFICATION: ModelRoleConfig(
        primary="anthropic/claude-haiku-4-20250514",
        temperature=0.1,
        max_tokens=256,
        timeout_seconds=10.0,
    ),
    ModelRole.EXTRACTION: ModelRoleConfig(
        primary="anthropic/claude-haiku-4-20250514",
        temperature=0.0,
        max_tokens=2048,
        timeout_seconds=30.0,
    ),
    ModelRole.SUMMARIZATION: ModelRoleConfig(
        primary="anthropic/claude-haiku-4-20250514",
        temperature=0.3,
        max_tokens=256,
        timeout_seconds=10.0,
    ),
}
