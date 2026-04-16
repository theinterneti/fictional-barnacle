"""LiteLLM client with 2-tier model fallback and retries.

Implements the LLMClient protocol using litellm for real LLM calls.
See plans/llm-and-pipeline.md §1 for design details.
"""

from __future__ import annotations

import time
from typing import Any, Literal

import litellm
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tta.llm.client import (
    GenerationParams,
    LLMResponse,
    Message,
)
from tta.llm.errors import (
    AllTiersFailedError,
    PermanentLLMError,
    TransientLLMError,
    classify_error,
)
from tta.llm.roles import (
    DEFAULT_ROLE_CONFIGS,
    ModelRole,
    ModelRoleConfig,
)
from tta.models.turn import TokenCount
from tta.observability.metrics import (
    TURN_LLM_CALLS,
    TURN_LLM_DURATION,
    TURN_LLM_TOKENS,
)

log = structlog.get_logger(__name__)

TierName = Literal["primary", "fallback"]


class LiteLLMClient:
    """LLM client backed by litellm with 2-tier fallback and retries.

    For each role, looks up ModelRoleConfig to determine primary and
    fallback models. On transient failure, retries up to 3 times per
    tier with exponential backoff, then falls through to the next tier.
    If all tiers fail, raises AllTiersFailedError.
    """

    def __init__(
        self,
        role_configs: dict[ModelRole, ModelRoleConfig] | None = None,
    ) -> None:
        self._role_configs = role_configs or DEFAULT_ROLE_CONFIGS

    async def generate(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Generate a complete response (non-streaming)."""
        return await self._call_with_fallback(role, messages, params, stream=False)

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
    ) -> LLMResponse:
        """Buffer-then-stream: streams internally, returns LLMResponse."""
        return await self._call_with_fallback(role, messages, params, stream=True)

    # ------------------------------------------------------------------
    # Internal: fallback chain
    # ------------------------------------------------------------------

    async def _call_with_fallback(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None,
        *,
        stream: bool,
    ) -> LLMResponse:
        config = self._role_configs.get(role)
        if config is None:
            msg = f"No model config for role={role}"
            raise PermanentLLMError(msg)

        effective_params = params or GenerationParams(
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        tiers: list[tuple[str, TierName]] = [
            (config.primary, "primary"),
        ]
        if config.fallback:
            tiers.append((config.fallback, "fallback"))

        errors: list[Exception] = []
        for model, tier_name in tiers:
            try:
                return await self._call_with_retries(
                    model=model,
                    messages=messages,
                    params=effective_params,
                    config=config,
                    stream=stream,
                    tier=tier_name,
                    role=role,
                )
            except PermanentLLMError:
                raise
            except TransientLLMError as exc:
                errors.append(exc)
                log.warning(
                    "tier_failed",
                    role=str(role),
                    model=model,
                    tier=tier_name,
                    error=str(exc),
                )

        raise AllTiersFailedError(role=str(role), errors=errors)

    # ------------------------------------------------------------------
    # Internal: per-tier retries (tenacity)
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(TransientLLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def _call_with_retries(
        self,
        *,
        model: str,
        messages: list[Message],
        params: GenerationParams,
        config: ModelRoleConfig,
        stream: bool,
        tier: TierName,
        role: ModelRole,
    ) -> LLMResponse:
        """Single-tier call wrapped with tenacity retries."""
        return await self._call_llm(
            model=model,
            messages=messages,
            params=params,
            config=config,
            stream=stream,
            tier=tier,
            role=role,
        )

    # ------------------------------------------------------------------
    # Internal: raw litellm call
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        *,
        model: str,
        messages: list[Message],
        params: GenerationParams,
        config: ModelRoleConfig,
        stream: bool,
        tier: TierName,
        role: ModelRole,
    ) -> LLMResponse:
        msg_dicts: list[dict[str, str]] = [
            {"role": m.role.value, "content": m.content} for m in messages
        ]
        stop = params.stop or None
        start = time.monotonic()

        try:
            if stream:
                content, usage = await self._stream_and_buffer(
                    model, msg_dicts, params, config, stop
                )
            else:
                raw = await litellm.acompletion(  # type: ignore[reportUnknownMemberType]
                    model=model,
                    messages=msg_dicts,  # type: ignore[reportArgumentType]
                    temperature=params.temperature,
                    max_tokens=params.max_tokens,
                    stop=stop,
                    timeout=config.timeout_seconds,
                )
                content = raw.choices[0].message.content or ""  # type: ignore[reportUnknownMemberType]
                usage = raw.usage  # type: ignore[reportUnknownMemberType]
        except (TransientLLMError, PermanentLLMError):
            raise
        except Exception as exc:
            error_cls = classify_error(exc)
            raise error_cls(str(exc), model=model) from exc

        elapsed_ms = (time.monotonic() - start) * 1000

        prompt_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tok = int(getattr(usage, "total_tokens", 0) or 0)
        token_count = TokenCount(
            prompt_tokens=prompt_tok,
            completion_tokens=completion_tok,
            total_tokens=total_tok or (prompt_tok + completion_tok),
        )

        cost_usd = self._calculate_cost(model, token_count)

        log.info(
            "llm_call_complete",
            role=str(role),
            model=model,
            tier=tier,
            stream=stream,
            latency_ms=round(elapsed_ms, 1),
            prompt_tokens=token_count.prompt_tokens,
            completion_tokens=token_count.completion_tokens,
            cost_usd=cost_usd,
        )

        # Prometheus instrumentation (S15 FR-15.6/7/8)
        provider = model.split("/", 1)[0] if "/" in model else "unknown"
        TURN_LLM_CALLS.labels(model=model, provider=provider).inc()
        TURN_LLM_DURATION.labels(model=model).observe(elapsed_ms / 1000)
        TURN_LLM_TOKENS.labels(model=model, direction="prompt").inc(prompt_tok)
        TURN_LLM_TOKENS.labels(model=model, direction="completion").inc(completion_tok)

        return LLMResponse(
            content=content,
            model_used=model,
            token_count=token_count,
            latency_ms=elapsed_ms,
            tier_used=tier,
            cost_usd=cost_usd,
        )

    async def _stream_and_buffer(
        self,
        model: str,
        msg_dicts: list[dict[str, str]],
        params: GenerationParams,
        config: ModelRoleConfig,
        stop: list[str] | None,
    ) -> tuple[str, Any]:
        """Stream from litellm and buffer all chunks.

        Returns (content, usage_or_None).
        """
        response = await litellm.acompletion(  # type: ignore[reportUnknownMemberType]
            model=model,
            messages=msg_dicts,  # type: ignore[reportArgumentType]
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            stop=stop,
            timeout=config.timeout_seconds,
            stream=True,
        )

        content_parts: list[str] = []
        usage: Any = None

        async for chunk in response:  # type: ignore[reportUnknownVariableType]
            choices = getattr(chunk, "choices", None)
            if choices:
                delta = getattr(choices[0], "delta", None)
                delta_content = getattr(delta, "content", None)
                if delta_content:
                    content_parts.append(str(delta_content))
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage = chunk_usage

        return "".join(content_parts), usage

    # ------------------------------------------------------------------
    # Internal: cost calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_cost(model: str, token_count: TokenCount) -> float:
        """Best-effort cost via litellm's cost tables."""
        try:
            return float(
                litellm.completion_cost(  # type: ignore[reportUnknownMemberType]
                    model=model,
                    prompt_tokens=token_count.prompt_tokens,
                    completion_tokens=token_count.completion_tokens,
                )
            )
        except Exception:
            return 0.0
