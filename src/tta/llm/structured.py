"""Structured output helpers using Instructor + LiteLLM.

Provides type-safe LLM extraction that replaces manual json.loads()
with Pydantic model validation, automatic retries, and proper error
handling. Integrates with TTA's existing LLMClient abstraction.

Usage:
    from tta.llm.structured import generate_structured
    from pydantic import BaseModel

    class WorldTraits(BaseModel):
        atmosphere: str
        locations: list[str]
        notable_npcs: list[str]

    traits = await generate_structured(
        llm_client,
        messages=[...],
        response_model=WorldTraits,
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import structlog
from pydantic import BaseModel

from tta.llm.client import Message
from tta.llm.roles import ModelRole

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_instructor_client: object | None = None


def _get_instructor_client() -> object:
    """Lazily initialize the Instructor client to avoid import-time
    litellm import (which hangs when CWD is the project root)."""
    global _instructor_client
    if _instructor_client is None:
        import instructor
        from litellm import acompletion

        _instructor_client = instructor.from_litellm(acompletion)
    return _instructor_client


async def generate_structured[T: BaseModel](
    llm_client: object,
    messages: list[Message],
    response_model: type[T],
    *,
    role: ModelRole = ModelRole.EXTRACTION,
    max_retries: int = 2,
) -> T:
    """Extract structured data from an LLM response.

    Args:
        llm_client: A TTA LLMClient instance. Used to resolve the active
            model from role configs.
        messages: The prompt messages.
        response_model: A Pydantic BaseModel subclass defining the expected
            output schema.
        role: The ModelRole for model selection (default: EXTRACTION).
        max_retries: Number of retries on validation failure (default: 2).

    Returns:
        An instance of response_model with validated data.

    Raises:
        instructor.exceptions.InstructorRetryException: If all retries
            are exhausted without valid output.
    """
    client = _get_instructor_client()

    # Convert TTA Message objects to dicts for Instructor/LiteLLM
    message_dicts = [{"role": m.role.value, "content": m.content} for m in messages]

    # Resolve the active model from the LLM client's role configs
    model = _resolve_model(llm_client, role)

    try:
        result = await client.chat.completions.create(
            model=model,
            messages=message_dicts,
            response_model=response_model,
            max_retries=max_retries,
        )
    except Exception:
        log.warning(
            "structured_extraction_failed",
            response_model=response_model.__name__,
            role=role.value,
            exc_info=True,
        )
        raise

    return result


def _resolve_model(llm_client: object, role: ModelRole) -> str:
    """Resolve the model name from the LLM client's role configs."""
    try:
        configs = getattr(llm_client, "_role_configs", None)
        if configs and role in configs:
            return configs[role].primary
    except Exception:
        pass
    # Sensible default for extraction tasks on free models
    return "openai/tta"
