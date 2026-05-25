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
from tta.llm.serving_profiles import (
    GenerationPolicy,
    GenerationServingProfile,
    GenerationTrafficClass,
    resolve_generation_policy,
)
from tta.models.turn import TokenCount
from tta.observability.metrics import (
    TURN_LLM_CALLS,
    TURN_LLM_DURATION,
    TURN_LLM_TOKENS,
)

log = structlog.get_logger(__name__)

TierName = Literal["primary", "fallback"]


def _router_task_for_model(
    model: str,
    role: ModelRole,
    policy: GenerationPolicy | None = None,
) -> str | None:
    """Return FMR task hint for OpenAI-compatible router-backed models."""
    if not model.startswith("openai/"):
        return None
    if role == ModelRole.GENERATION and policy is not None:
        return policy.router_task
    return role.value


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
        *,
        generation_profile: GenerationServingProfile | None = None,
        traffic_class: GenerationTrafficClass | None = None,
    ) -> LLMResponse:
        """Generate a complete response (non-streaming)."""
        return await self._call_with_fallback(
            role,
            messages,
            params,
            stream=False,
            generation_profile=generation_profile,
            traffic_class=traffic_class,
        )

    async def stream(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None = None,
        *,
        generation_profile: GenerationServingProfile | None = None,
        traffic_class: GenerationTrafficClass | None = None,
    ) -> LLMResponse:
        """Buffer-then-stream: streams internally, returns LLMResponse."""
        return await self._call_with_fallback(
            role,
            messages,
            params,
            stream=True,
            generation_profile=generation_profile,
            traffic_class=traffic_class,
        )

    async def _call_with_fallback(
        self,
        role: ModelRole,
        messages: list[Message],
        params: GenerationParams | None,
        *,
        stream: bool,
        generation_profile: GenerationServingProfile | None,
        traffic_class: GenerationTrafficClass | None,
    ) -> LLMResponse:
        config = self._role_configs.get(role)
        if config is None:
            msg = f"No model config for role={role}"
            raise PermanentLLMError(msg)

        policy = (
            resolve_generation_policy(generation_profile, traffic_class)
            if role == ModelRole.GENERATION
            else None
        )

        effective_params = params or GenerationParams(
            temperature=config.temperature,
            max_tokens=(policy.max_tokens if policy is not None else config.max_tokens),
        )
        if (
            policy is not None
            and params is not None
            and params.max_tokens == GenerationParams().max_tokens
        ):
            effective_params = params.model_copy(
                update={"max_tokens": policy.max_tokens}
            )

        tiers: list[tuple[str, TierName]] = [
            (config.primary, "primary"),
        ]
        if config.fallback:
            tiers.append((config.fallback, "fallback"))

        errors: list[Exception] = []
        for model, tier_name in tiers:
            try:
                response = await self._call_with_retries(
                    model=model,
                    messages=messages,
                    params=effective_params,
                    config=config,
                    stream=stream,
                    tier=tier_name,
                    role=role,
                    policy=policy,
                )
                if policy is not None:
                    requested_profile = policy.profile.value
                    effective_profile = policy.profile.value
                    traffic_value = policy.traffic_class.value
                    degraded = tier_name != "primary"
                    degradation_reason = (
                        "router_primary_tier_unavailable" if degraded else ""
                    )
                    return response.model_copy(
                        update={
                            "requested_profile": requested_profile,
                            "effective_profile": effective_profile,
                            "traffic_class": traffic_value,
                            "degraded": degraded,
                            "degradation_reason": degradation_reason,
                        }
                    )
                return response
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
                    requested_profile=(policy.profile.value if policy else ""),
                    traffic_class=(policy.traffic_class.value if policy else ""),
                )

        if role == ModelRole.GENERATION and policy is not None:
            raise AllTiersFailedError(
                role=str(role),
                errors=errors,
            )
        raise AllTiersFailedError(role=str(role), errors=errors)

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
        policy: GenerationPolicy | None,
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
            policy=policy,
        )

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
        policy: GenerationPolicy | None,
    ) -> LLMResponse:
        msg_dicts: list[dict[str, str]] = [
            {"role": m.role.value, "content": m.content} for m in messages
        ]
        stop = params.stop if params.stop else None
        response_format = params.response_format
        start = time.monotonic()

        try:
            if stream:
                content, usage = await self._stream_and_buffer(
                    model,
                    msg_dicts,
                    params,
                    config,
                    stop,
                    response_format,
                    role,
                    policy,
                )
            else:
                call_kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": msg_dicts,
                    "temperature": params.temperature,
                    "max_tokens": params.max_tokens,
                    "stop": stop,
                    "timeout": (
                        policy.timeout_seconds
                        if policy is not None
                        else config.timeout_seconds
                    ),
                }
                router_task = _router_task_for_model(model, role, policy)
                if router_task is not None:
                    call_kwargs["task"] = router_task
                if policy is not None:
                    call_kwargs["metadata"] = {
                        "generation_profile": policy.profile.value,
                        "traffic_class": policy.traffic_class.value,
                        "router_task": policy.router_task,
                        "latency_class": policy.latency_class,
                        "dispatch_preference": policy.dispatch_preference,
                    }
                if response_format is not None:
                    call_kwargs["response_format"] = response_format
                raw = await litellm.acompletion(**call_kwargs)
                content = raw.choices[0].message.content or ""
                usage = raw.usage
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
            requested_profile=(policy.profile.value if policy else ""),
            effective_profile=(policy.profile.value if policy else ""),
            traffic_class=(policy.traffic_class.value if policy else ""),
            degraded=(tier != "primary" if policy else False),
            degradation_reason=(
                "router_primary_tier_unavailable"
                if policy and tier != "primary"
                else ""
            ),
        )

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
        response_format: dict[str, Any] | None,
        role: ModelRole,
        policy: GenerationPolicy | None,
    ) -> tuple[str, Any]:
        """Stream from litellm and buffer all chunks.

        Returns (content, usage_or_None).
        """
        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "stop": stop,
            "timeout": (
                policy.timeout_seconds if policy is not None else config.timeout_seconds
            ),
            "stream": True,
        }
        router_task = _router_task_for_model(model, role, policy)
        if router_task is not None:
            call_kwargs["task"] = router_task
        if policy is not None:
            call_kwargs["metadata"] = {
                "generation_profile": policy.profile.value,
                "traffic_class": policy.traffic_class.value,
                "router_task": policy.router_task,
                "latency_class": policy.latency_class,
                "dispatch_preference": policy.dispatch_preference,
            }
        if response_format is not None:
            call_kwargs["response_format"] = response_format
        response = await litellm.acompletion(**call_kwargs)

        content_parts: list[str] = []
        usage: Any = None

        async for chunk in response:
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

    @staticmethod
    def _calculate_cost(model: str, token_count: TokenCount) -> float:
        """Best-effort cost via litellm's cost tables."""
        try:
            return float(
                litellm.completion_cost(
                    model=model,
                    prompt_tokens=token_count.prompt_tokens,
                    completion_tokens=token_count.completion_tokens,
                )
            )
        except Exception:
            return 0.0
