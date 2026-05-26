"""Type stubs for shared_langfuse.client."""

from typing import Any


def init_langfuse(
    host: str = "",
    public_key: str = "",
    secret_key: str = "",
) -> None: ...


def get_client() -> Any: ...


def is_configured() -> bool: ...


def get_last_trace_id() -> str | None: ...


def set_last_trace_id(trace_id: str) -> None: ...


def _to_langfuse_id(uuid_str: str) -> str: ...
