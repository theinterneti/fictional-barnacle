"""Type stubs for shared_langfuse — resolved locally, stubbed on CI.

On CI, shared-langfuse is not installed (it's a local-only dependency).
These stubs satisfy pyright while the code gracefully degrades via
``is_configured()`` returning False.
"""

from typing import Any


def init_langfuse(
    host: str = "",
    public_key: str = "",
    secret_key: str = "",
) -> None: ...


def get_client() -> Any: ...


def is_configured() -> bool: ...


def llm_chat(
    messages: list[dict[str, str]],
    *,
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int | None = None,
    name: str | None = None,
    langfuse_prompt: Any = None,
    mock: bool = False,
    tags: list[str] | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    base_url: str = "",
    api_key: str = "",
) -> str: ...


def score_trace(
    *,
    name: str,
    value: float | str | bool,
    trace_id: str | None = None,
    comment: str = "",
) -> None: ...
