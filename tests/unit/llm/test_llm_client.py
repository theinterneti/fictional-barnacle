"""Tests for LLM client protocol, types, and mock."""

import pytest

from tta.llm.client import (
    GenerationParams,
    LLMResponse,
    Message,
    MessageRole,
)
from tta.llm.roles import ModelRole
from tta.llm.testing import MockLLMClient
from tta.models.turn import TokenCount


class TestModelRole:
    def test_enum_values(self) -> None:
        assert ModelRole.GENERATION == "generation"
        assert ModelRole.CLASSIFICATION == "classification"
        assert ModelRole.EXTRACTION == "extraction"

    def test_all_members(self) -> None:
        assert set(ModelRole) == {
            ModelRole.GENERATION,
            ModelRole.CLASSIFICATION,
            ModelRole.EXTRACTION,
        }


class TestMessage:
    @pytest.mark.parametrize(
        "role",
        [MessageRole.SYSTEM, MessageRole.USER, MessageRole.ASSISTANT],
    )
    def test_creation_with_each_role(self, role: MessageRole) -> None:
        msg = Message(role=role, content="hello")
        assert msg.role == role
        assert msg.content == "hello"


class TestGenerationParams:
    def test_defaults(self) -> None:
        params = GenerationParams()
        assert params.temperature == 0.7
        assert params.max_tokens == 1024
        assert params.stop == []

    def test_custom_values(self) -> None:
        params = GenerationParams(temperature=0.3, max_tokens=512, stop=["END"])
        assert params.temperature == 0.3
        assert params.max_tokens == 512
        assert params.stop == ["END"]


class TestLLMResponse:
    def test_with_token_count(self) -> None:
        tc = TokenCount(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
        resp = LLMResponse(
            content="hello",
            model_used="gpt-4",
            token_count=tc,
            latency_ms=150.0,
        )
        assert resp.content == "hello"
        assert resp.model_used == "gpt-4"
        assert resp.token_count.total_tokens == 30
        assert resp.latency_ms == 150.0


class TestMockLLMClient:
    @pytest.mark.asyncio
    async def test_generate_returns_valid_response(self) -> None:
        client = MockLLMClient()
        messages = [Message(role=MessageRole.USER, content="look around")]
        resp = await client.generate(role=ModelRole.GENERATION, messages=messages)

        assert isinstance(resp, LLMResponse)
        assert resp.model_used == "mock"
        assert resp.content == "You enter a dimly lit chamber."
        assert resp.token_count.prompt_tokens > 0
        assert resp.token_count.completion_tokens > 0
        assert (
            resp.token_count.total_tokens
            == resp.token_count.prompt_tokens + resp.token_count.completion_tokens
        )
        assert resp.latency_ms == 0.0

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self) -> None:
        client = MockLLMClient()
        messages = [Message(role=MessageRole.USER, content="look around")]
        tokens: list[str] = []
        async for token in client.stream(role=ModelRole.GENERATION, messages=messages):
            tokens.append(token)

        expected = "You enter a dimly lit chamber.".split()
        assert tokens == expected

    async def test_satisfies_llm_client_protocol(self) -> None:
        """Structural typing: MockLLMClient has generate & stream."""
        client = MockLLMClient()
        assert hasattr(client, "generate")
        assert hasattr(client, "stream")
        assert callable(client.generate)
        assert callable(client.stream)

        # Verify signatures accept the right args
        messages = [Message(role=MessageRole.USER, content="test")]
        resp = await client.generate(
            role=ModelRole.GENERATION,
            messages=messages,
            params=GenerationParams(),
        )
        assert isinstance(resp, LLMResponse)
