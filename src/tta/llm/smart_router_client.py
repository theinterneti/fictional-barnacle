"""Smart Router adapter for TTA simulation harness.

Connects to the free-model-router HTTP server (POST /v1/chat/completions)
to implement the LLMClient protocol.  The server is started automatically
on first use when it is not already running.

Environment variables
---------------------
FREE_MODEL_ROUTER_URL
    Base URL of the running server (default: http://localhost:3000).
FREE_MODEL_ROUTER_BIN
    Path to the built Node.js server entry-point
    (default: ~/Repos/free-model-router/dist/src/server.js).
FREE_MODEL_ROUTER_STARTUP_TIMEOUT
    Seconds to wait for the server to become healthy after a managed
    start (default: 15).
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import structlog

from tta.llm.client import GenerationParams, LLMResponse, Message
from tta.llm.roles import ModelRole
from tta.models.turn import TokenCount

log = structlog.get_logger(__name__)

_ROUTER_BASE_URL = os.getenv("FREE_MODEL_ROUTER_URL", "http://localhost:3000")
_ROUTER_BIN = Path(
    os.getenv(
        "FREE_MODEL_ROUTER_BIN",
        str(Path.home() / "Repos" / "free-model-router" / "dist" / "src" / "server.js"),
    )
)
_STARTUP_TIMEOUT = float(os.getenv("FREE_MODEL_ROUTER_STARTUP_TIMEOUT", "15"))

_ROLE_TO_TASK: dict[ModelRole, str] = {
    ModelRole.GENERATION: "creative",
    ModelRole.CLASSIFICATION: "classification",
    ModelRole.EXTRACTION: "extraction",
    ModelRole.SUMMARIZATION: "summarization",
}


class SmartRouterLLMClient:
    """LLM client backed by the free-model-router HTTP server.

    Connects to the router at ``FREE_MODEL_ROUTER_URL``.  If the server is
    not already running it will be started automatically from
    ``FREE_MODEL_ROUTER_BIN`` on the first call, then stopped when
    :meth:`aclose` is called.

    Call history is recorded in :attr:`call_history` for inspection.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._server_proc: subprocess.Popen[str] | None = None
        self.call_history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # LLMClient protocol
    # ------------------------------------------------------------------

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Generate a response using free-model-router."""
        await self._ensure_ready()
        assert self._client is not None

        task_type = _ROLE_TO_TASK.get(role, "creative")
        payload = {
            "messages": [
                {"role": m.role.value, "content": m.content} for m in messages
            ],
            "task": task_type,
        }

        t0 = time.monotonic()
        try:
            resp = await self._client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "free_model_router.http_error",
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            return self._error_response(messages, str(exc))
        except httpx.TransportError as exc:
            log.warning("free_model_router.transport_error", error=str(exc))
            return self._error_response(messages, str(exc))

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        data = resp.json()

        content: str = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        model_used: str = data.get("model", "free-model-router")
        latency_ms = float(
            data.get("latency_ms") or resp.headers.get("X-Latency-Ms") or elapsed_ms
        )

        prompt_tokens = sum(len(m.content.split()) for m in messages)
        completion_tokens = len(content.split())

        self.call_history.append(
            {
                "method": "generate",
                "role": role,
                "task": task_type,
                "model": model_used,
                "messages_count": len(messages),
                "latency_ms": latency_ms,
            }
        )

        log.debug(
            "free_model_router.response",
            model=model_used,
            provider=data.get("provider"),
            latency_ms=latency_ms,
            task=task_type,
        )

        return LLMResponse(
            content=content,
            model_used=model_used,
            token_count=TokenCount(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
            latency_ms=latency_ms,
            tier_used="primary",
        )

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Buffer-then-stream: delegate to :meth:`generate`."""
        return await self.generate(role, messages, params)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the HTTP client and stop the managed server process (if any)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._server_proc is not None:
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
            self._server_proc = None

    async def __aenter__(self) -> "SmartRouterLLMClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_ready(self) -> None:
        """Initialise the HTTP client and start the server if needed."""
        if self._client is not None:
            return

        self._client = httpx.AsyncClient(base_url=_ROUTER_BASE_URL, timeout=90.0)

        if await self._is_healthy():
            log.info("free_model_router.connected", url=_ROUTER_BASE_URL)
            return

        if not _ROUTER_BIN.exists():
            raise RuntimeError(
                f"free-model-router binary not found: {_ROUTER_BIN}. "
                "Run `npm run build` inside free-model-router or set "
                "FREE_MODEL_ROUTER_BIN."
            )

        log.info("free_model_router.starting", bin=str(_ROUTER_BIN))
        self._server_proc = subprocess.Popen(
            ["node", str(_ROUTER_BIN)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        deadline = time.monotonic() + _STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            if await self._is_healthy():
                log.info("free_model_router.started", url=_ROUTER_BASE_URL)
                return

        raise RuntimeError(
            f"free-model-router did not become healthy within {_STARTUP_TIMEOUT}s. "
            f"Check that {_ROUTER_BIN} exists and API keys are configured."
        )

    async def _is_healthy(self) -> bool:
        assert self._client is not None
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.ConnectError:
            return False

    def _error_response(self, messages: list[Message], error: str) -> LLMResponse:
        prompt_tokens = sum(len(m.content.split()) for m in messages)
        return LLMResponse(
            content=f"[free-model-router unavailable: {error}]",
            model_used="free-model-router-error",
            token_count=TokenCount(
                prompt_tokens=prompt_tokens,
                completion_tokens=8,
                total_tokens=prompt_tokens + 8,
            ),
            latency_ms=1.0,
            tier_used="fallback",
        )


def create_smart_router_client() -> SmartRouterLLMClient:
    """Factory: create a :class:`SmartRouterLLMClient`."""
    return SmartRouterLLMClient()
