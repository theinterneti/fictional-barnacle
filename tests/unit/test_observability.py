"""Tests for Langfuse observability integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tta import observability
from tta.config import Settings
from tta.observability import (
    _sanitize_input,
    get_langfuse,
    init_langfuse,
    shutdown_langfuse,
    trace_llm,
)

# -- helpers -----------------------------------------------------------


def _make_settings(**overrides: object) -> Settings:
    """Build a Settings with required fields filled in."""
    defaults: dict[str, object] = {
        "database_url": "postgresql://u:p@localhost/tta",
        "neo4j_password": "test-secret",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _fake_llm_response(
    text: str = "Hello!", model: str = "gpt-4o-mini"
) -> SimpleNamespace:
    """Simulate a LiteLLM ChatCompletion response."""
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    return SimpleNamespace(
        choices=[choice], model=model, usage=usage
    )


@pytest.fixture(autouse=True)
def _reset_client() -> Any:
    """Reset the module-level client before and after each test."""
    observability._langfuse_client = None
    yield
    observability._langfuse_client = None


# -- AC-1: conditional initialization ---------------------------------


class TestInitLangfuse:
    """init_langfuse conditionally creates a Langfuse client."""

    def test_no_host_stays_none(self) -> None:
        """When langfuse_host is None, client remains None."""
        settings = _make_settings(langfuse_host=None)
        init_langfuse(settings)
        assert get_langfuse() is None

    def test_empty_host_stays_none(self) -> None:
        """When langfuse_host is empty string, client remains None."""
        settings = _make_settings(langfuse_host="")
        init_langfuse(settings)
        assert get_langfuse() is None

    @patch("tta.observability.Langfuse", create=True)
    def test_with_host_creates_client(
        self, mock_cls: MagicMock
    ) -> None:
        """When langfuse_host is set, a Langfuse client is created."""
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        with patch(
            "tta.observability.init_langfuse",
            wraps=init_langfuse,
        ):
            # Patch the import inside init_langfuse
            with patch.dict(
                "sys.modules",
                {"langfuse": MagicMock(Langfuse=mock_cls)},
            ):
                settings = _make_settings(
                    langfuse_host="https://langfuse.example.com",
                    langfuse_public_key="pk-test",
                    langfuse_secret_key="sk-test",
                )
                init_langfuse(settings)

        assert get_langfuse() is mock_instance
        mock_cls.assert_called_once_with(
            host="https://langfuse.example.com",
            public_key="pk-test",
            secret_key="sk-test",
        )

    def test_no_error_when_disabled(self) -> None:
        """Disabling Langfuse never raises an exception."""
        settings = _make_settings()
        init_langfuse(settings)  # should not raise


# -- AC-2: trace_llm decorator ----------------------------------------


class TestTraceLlmNoOp:
    """trace_llm is transparent when Langfuse is disabled."""

    async def test_function_executes(self) -> None:
        """Decorated async function runs and returns its value."""

        @trace_llm(name="test_call")
        async def _dummy(prompt: str) -> str:
            return f"echo: {prompt}"

        result = await _dummy(prompt="hi")
        assert result == "echo: hi"

    async def test_exception_propagates(self) -> None:
        """Exceptions from the wrapped function propagate unchanged."""

        @trace_llm(name="fail")
        async def _boom() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await _boom()


class TestTraceLlmWithClient:
    """trace_llm records traces when Langfuse is active."""

    def _install_mock_client(self) -> MagicMock:
        mock = MagicMock()
        mock_trace = MagicMock()
        mock.trace.return_value = mock_trace
        observability._langfuse_client = mock
        return mock

    async def test_trace_created(self) -> None:
        """A trace is created with the decorator name."""
        mock = self._install_mock_client()

        @trace_llm(name="generate")
        async def _call() -> SimpleNamespace:
            return _fake_llm_response()

        await _call()

        mock.trace.assert_called_once_with(
            name="generate", tags=["user_input"]
        )

    async def test_generation_recorded(self) -> None:
        """A generation is recorded with model, usage, and output."""
        mock = self._install_mock_client()
        mock_trace = mock.trace.return_value

        @trace_llm(name="gen")
        async def _call() -> SimpleNamespace:
            return _fake_llm_response(
                text="world", model="gpt-4o"
            )

        await _call()

        mock_trace.generation.assert_called_once()
        gen_kw = mock_trace.generation.call_args.kwargs
        assert gen_kw["name"] == "gen"
        assert gen_kw["model"] == "gpt-4o"
        assert gen_kw["output"] == "world"
        assert gen_kw["usage"]["input"] == 10
        assert gen_kw["usage"]["output"] == 5
        assert gen_kw["usage"]["total"] == 15
        assert "latency_ms" in gen_kw["metadata"]

    async def test_error_updates_trace(self) -> None:
        """On exception, the trace is marked ERROR and exception re-raised."""
        mock = self._install_mock_client()
        mock_trace = mock.trace.return_value

        @trace_llm(name="bad")
        async def _call() -> None:
            raise RuntimeError("oops")

        with pytest.raises(RuntimeError, match="oops"):
            await _call()

        mock_trace.update.assert_called_once_with(
            level="ERROR", status_message="oops"
        )

    async def test_kwargs_passed_as_input(self) -> None:
        """Function kwargs are passed as generation input."""
        mock = self._install_mock_client()
        mock_trace = mock.trace.return_value

        @trace_llm(name="prompt")
        async def _call(
            messages: list[str] | None = None,
        ) -> SimpleNamespace:
            return _fake_llm_response()

        await _call(messages=["hello"])

        gen_kw = mock_trace.generation.call_args.kwargs
        assert gen_kw["input"] == {"messages": ["hello"]}


# -- AC-3: privacy compliance -----------------------------------------


class TestPrivacy:
    """Player input is tagged and PII is stripped."""

    async def test_trace_tagged_user_input(self) -> None:
        """Traces carry the ``user_input`` tag for filtering."""
        mock = MagicMock()
        mock.trace.return_value = MagicMock()
        observability._langfuse_client = mock

        @trace_llm(name="chat")
        async def _call() -> SimpleNamespace:
            return _fake_llm_response()

        await _call()

        mock.trace.assert_called_once_with(
            name="chat", tags=["user_input"]
        )

    def test_sanitize_removes_pii(self) -> None:
        """_sanitize_input strips known PII fields."""
        raw = {
            "messages": ["hi"],
            "email": "a@b.com",
            "name": "Alice",
            "model": "gpt-4o",
        }
        clean = _sanitize_input(raw)
        assert "messages" in clean
        assert "model" in clean
        assert "email" not in clean
        assert "name" not in clean

    def test_sanitize_keeps_non_pii(self) -> None:
        """_sanitize_input preserves non-PII fields."""
        raw = {"messages": ["hi"], "temperature": 0.7}
        clean = _sanitize_input(raw)
        assert clean == raw


# -- shutdown ----------------------------------------------------------


class TestShutdown:
    """shutdown_langfuse flushes the client."""

    def test_flush_called(self) -> None:
        mock = MagicMock()
        observability._langfuse_client = mock
        shutdown_langfuse()
        mock.flush.assert_called_once()

    def test_noop_when_disabled(self) -> None:
        """No error when shutting down without a client."""
        shutdown_langfuse()  # should not raise
