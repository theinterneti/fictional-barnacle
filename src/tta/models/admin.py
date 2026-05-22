"""Admin API request models (S26)."""

from typing import Any

from pydantic import BaseModel, Field


class SuspendRequest(BaseModel):
    reason: str = Field(..., min_length=10)


class TerminateRequest(BaseModel):
    reason: str = Field(..., min_length=10)


class ReviewRequest(BaseModel):
    action: str = Field(..., pattern=r"^(dismiss|warn|suspend_player)$")
    notes: str = Field(..., min_length=10)


class ReasonRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class LogLevelBody(BaseModel):
    level: str = Field(
        ...,
        pattern="^(DEBUG|INFO|WARNING|ERROR)$",
        description="Target log level.",
    )


class UniverseConfigPatchRequest(BaseModel):
    """Payload for ``PATCH /admin/universes/{universe_id}``."""

    config: dict = Field(default_factory=dict)


class ActivatePromptRequest(BaseModel):
    label: str = Field(
        default="production",
        pattern=r"^[a-z0-9_\-]{1,36}$",
        description="Langfuse label to apply (e.g. 'production', 'staging')",
    )


class PreviewPromptRequest(BaseModel):
    label: str = Field(
        default="production",
        pattern=r"^[a-z0-9_\-]{1,36}$",
        description="Label to preview (e.g. 'staging')",
    )
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Template variables for rendering",
    )
