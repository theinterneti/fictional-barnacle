"""Tests for LiteLLMClient — mocks litellm, no real API calls."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tta.llm.client import (
    GenerationParams,
    LLMResponse,
    Message,
    MessageRole,
)
from tta.llm.errors import (
    AllTiersFailedError,
    PermanentLLMError,
    TransientLLMError,
)
from tta.llm.litellm_client import LiteLLMClient
from tta.llm.roles import ModelRole, ModelRoleConfig

# ── helpers ──────────────────────────────────────────────────────────

MESSAGES = [Message(role=MessageRole.USER, content="look around")]
PARAMS = GenerationParams(temperature=0.5, max_tokens=100)


def _role_configs(
    primary: str = "test/primary",
    fallback: str | None = "test/fallback",
) -> dict[ModelRole, ModelRoleConfig]:
    return {
        ModelRole.GENERATION: ModelRoleConfig(
            primary=primary,
            fallback=fallback,
            temperature=0.7,
            max_tokens=100,
            timeout_seconds=5.0,
        ),
    }


def _no_fallback_configs() -> dict[ModelRole, ModelRoleConfig]:
    """Role config with no fallback model."""
    return _role_configs(fallback=None)


def _mock_response(
    content: str = "Hello world",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> MagicMock:
    """Build a mock that looks like litellm.ModelResponse."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    resp.usage = usage
    return resp


def _mock_stream_chunks(
    content: str = "Hello world",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    *,
    include_usage: bool = True,
) -> list[MagicMock]:
    """Build mock streaming chunks."""
    words = content.split()
    chunks: list[MagicMock] = []
    for word in words:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = word + " "
        chunk.usage = None
        chunks.append(chunk)
    # Final chunk: no content, optionally has usage
    final = MagicMock()
    final.choices = [MagicMock()]
    final.choices[0].delta = MagicMock()
    final.choices[0].delta.content = None
    if include_usage:
        usage = MagicMock()
        usage.prompt_tokens = prompt_tokens
        usage.completion_tokens = completion_tokens
        usage.total_tokens = prompt_tokens + completion_tokens
        final.usage = usage
    else:
        final.usage = None
    chunks.append(final)
    return chunks


async def _async_iter(items: list[Any]) -> Any:
    """Turn a list into an async iterator."""
    for item in items:
        yield item


# Patch targets
_ACOMPLETION = "tta.llm.litellm_client.litellm.acompletion"
_COST = "tta.llm.litellm_client.litellm.completion_cost"


# ── generate() tests ────────────────────────────────────────────────


class TestGenerate:
    @pytest.mark.asyncio
    @patch(_COST, return_value=0.001)
    @patch(_ACOMPLETION)
    async def test_happy_path(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(
            ModelRole.GENERATION, MESSAGES, PARAMS
        )

        assert isinstance(resp, LLMResponse)
        assert resp.content == "Hello world"
        assert resp.model_used == "test/primary"
        assert resp.tier_used == "primary"
        assert resp.token_count.prompt_tokens == 10
        assert resp.token_count.completion_tokens == 5
        assert resp.token_count.total_tokens == 15
        assert resp.latency_ms > 0
        assert resp.cost_usd == 0.001

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_default_params_from_role_config(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        """When params=None, role config temperature/max_tokens used."""
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        await client.generate(ModelRole.GENERATION, MESSAGES, None)

        call_kwargs = mock_ac.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 100


# ── stream() tests ──────────────────────────────────────────────────


class TestStream:
    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_happy_path(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        chunks = _mock_stream_chunks("Hello world")
        mock_ac.return_value = _async_iter(chunks)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.stream(
            ModelRole.GENERATION, MESSAGES, PARAMS
        )

        assert isinstance(resp, LLMResponse)
        assert "Hello" in resp.content
        assert "world" in resp.content
        assert resp.token_count.prompt_tokens == 10
        assert resp.token_count.completion_tokens == 5

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_stream_no_usage_defaults_to_zero(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        chunks = _mock_stream_chunks(
            "hi", include_usage=False
        )
        mock_ac.return_value = _async_iter(chunks)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.stream(ModelRole.GENERATION, MESSAGES)

        assert resp.token_count.prompt_tokens == 0
        assert resp.token_count.completion_tokens == 0

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_stream_error_during_iteration(
        self, mock_ac: AsyncMock
    ) -> None:
        """Error mid-stream is classified and raised."""

        async def _exploding_stream() -> Any:
            yield _mock_stream_chunks("partial")[0]
            raise ConnectionError("stream dropped")

        mock_ac.return_value = _exploding_stream()
        client = LiteLLMClient(
            role_configs=_role_configs(fallback=None)
        )

        with pytest.raises(TransientLLMError, match="stream dropped"):
            await client.stream(ModelRole.GENERATION, MESSAGES)


# ── fallback tests ──────────────────────────────────────────────────


class TestFallback:
    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_fallback_on_transient_error(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        """Primary fails 3× (retries exhausted), fallback succeeds."""
        mock_ac.side_effect = [
            TransientLLMError("down", model="test/primary"),
            TransientLLMError("down", model="test/primary"),
            TransientLLMError("down", model="test/primary"),
            _mock_response(content="from fallback"),
        ]
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.content == "from fallback"
        assert resp.tier_used == "fallback"
        assert mock_ac.call_count == 4

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_all_tiers_failed(
        self, mock_ac: AsyncMock
    ) -> None:
        """Both tiers exhaust retries → AllTiersFailedError."""
        mock_ac.side_effect = TransientLLMError(
            "down", model="test"
        )
        client = LiteLLMClient(role_configs=_role_configs())

        with pytest.raises(AllTiersFailedError):
            await client.generate(ModelRole.GENERATION, MESSAGES)

        # 3 retries × 2 tiers = 6
        assert mock_ac.call_count == 6

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_no_fallback_role_only_three_calls(
        self, mock_ac: AsyncMock
    ) -> None:
        """Role with no fallback exhausts retries in 3 calls."""
        mock_ac.side_effect = TransientLLMError(
            "down", model="test/primary"
        )
        client = LiteLLMClient(role_configs=_no_fallback_configs())

        with pytest.raises(AllTiersFailedError):
            await client.generate(ModelRole.GENERATION, MESSAGES)

        assert mock_ac.call_count == 3

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_permanent_error_no_fallback(
        self, mock_ac: AsyncMock
    ) -> None:
        """PermanentLLMError stops immediately, no fallback attempted."""
        mock_ac.side_effect = PermanentLLMError(
            "auth failed", model="test/primary"
        )
        client = LiteLLMClient(role_configs=_role_configs())

        with pytest.raises(PermanentLLMError, match="auth failed"):
            await client.generate(ModelRole.GENERATION, MESSAGES)

        assert mock_ac.call_count == 1


# ── retry tests ─────────────────────────────────────────────────────


class TestRetries:
    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_transient_then_success(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        """One transient failure then success → 2 calls, primary tier."""
        mock_ac.side_effect = [
            TransientLLMError("timeout", model="test/primary"),
            _mock_response(),
        ]
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.tier_used == "primary"
        assert mock_ac.call_count == 2


# ── error classification tests ──────────────────────────────────────


class TestErrorClassification:
    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_transient_litellm_exception_retried(
        self, mock_ac: AsyncMock
    ) -> None:
        """Exception classified as transient is retried."""
        RateLimitError = type("RateLimitError", (Exception,), {})
        mock_ac.side_effect = RateLimitError("rate limited")
        client = LiteLLMClient(
            role_configs=_no_fallback_configs()
        )

        with pytest.raises(TransientLLMError):
            await client.generate(ModelRole.GENERATION, MESSAGES)

        assert mock_ac.call_count == 3

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_permanent_litellm_exception_not_retried(
        self, mock_ac: AsyncMock
    ) -> None:
        """Exception classified as permanent is not retried."""
        AuthError = type("AuthenticationError", (Exception,), {})
        mock_ac.side_effect = AuthError("bad key")
        client = LiteLLMClient(
            role_configs=_no_fallback_configs()
        )

        with pytest.raises(PermanentLLMError):
            await client.generate(ModelRole.GENERATION, MESSAGES)

        assert mock_ac.call_count == 1


# ── cost tracking tests ─────────────────────────────────────────────


class TestCostTracking:
    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0015)
    @patch(_ACOMPLETION)
    async def test_cost_populated(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.cost_usd == 0.0015

    @pytest.mark.asyncio
    @patch(_COST, side_effect=Exception("unknown model"))
    @patch(_ACOMPLETION)
    async def test_cost_defaults_to_zero_on_error(
        self, mock_ac: AsyncMock, mock_cost: MagicMock
    ) -> None:
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.cost_usd == 0.0
