from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from tta.llm.client import GenerationParams, Message, MessageRole
from tta.llm.errors import PermanentLLMError, TransientLLMError
from tta.llm.roles import ModelRole
from tta.llm.smart_router_client import SmartRouterLLMClient

MESSAGES = [Message(role=MessageRole.USER, content="look around")]
PARAMS = GenerationParams(temperature=0.5, max_tokens=100)


def _client_with_response(response: httpx.Response) -> SmartRouterLLMClient:
    client = SmartRouterLLMClient()
    request = httpx.Request("POST", "http://router.test/v1/chat/completions")
    response.request = request
    post = AsyncMock(return_value=response)
    health = AsyncMock(return_value=httpx.Response(200, json={"status": "ok"}))

    class DummyClient:
        def __init__(self) -> None:
            self.post = post
            self.get = health

        async def aclose(self) -> None:
            return None

    client._client = DummyClient()  # type: ignore[assignment]
    return client


@pytest.mark.asyncio
async def test_generation_uses_generation_task_hint() -> None:
    client = _client_with_response(
        httpx.Response(
            200,
            json={
                "model": "meta/llama-4-maverick-17b-128e-instruct",
                "choices": [{"message": {"content": "The plaza is quiet."}}],
            },
            headers={"X-Latency-Ms": "1234"},
        )
    )

    response = await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

    assert response.content == "The plaza is quiet."
    assert client.call_history[-1]["task"] == "generation"


@pytest.mark.asyncio
async def test_http_503_raises_transient_error() -> None:
    client = _client_with_response(
        httpx.Response(
            503,
            json={"error": {"message": "No providers available"}},
        )
    )

    with pytest.raises(TransientLLMError):
        await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)


@pytest.mark.asyncio
async def test_http_400_raises_permanent_error() -> None:
    client = _client_with_response(
        httpx.Response(
            400,
            json={"error": {"message": "bad request"}},
        )
    )

    with pytest.raises(PermanentLLMError):
        await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)


@pytest.mark.asyncio
async def test_transport_error_raises_transient_error() -> None:
    client = SmartRouterLLMClient()

    class DummyClient:
        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async def aclose(self) -> None:
            return None

    client._client = DummyClient()  # type: ignore[assignment]

    with pytest.raises(TransientLLMError):
        await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)
