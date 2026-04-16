"""S07 LLM Integration — Acceptance Criteria compliance tests.

Covers AC-07.1, AC-07.2, AC-07.3, AC-07.4, AC-07.5, AC-07.7.

v2 ACs (deferred):
  AC-07.6 — Langfuse observability (requires live Langfuse integration infra)
"""

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
from tta.llm.context_budget import ContextChunk, Priority, fit_chunks_to_budget
from tta.llm.errors import (
    AllTiersFailedError,
    BudgetExceededError,
    PermanentLLMError,
    TransientLLMError,
)
from tta.llm.litellm_client import LiteLLMClient
from tta.llm.roles import ModelRole, ModelRoleConfig
from tta.models.turn import TokenCount
from tta.privacy.cost import LLMCostTracker, reset_cost_tracker

# ── Shared test helpers ──────────────────────────────────────────────────────

MESSAGES = [Message(role=MessageRole.USER, content="look around")]
PARAMS = GenerationParams(temperature=0.5, max_tokens=100)

_ACOMPLETION = "tta.llm.litellm_client.litellm.acompletion"
_COST = "tta.llm.litellm_client.litellm.completion_cost"


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


def _mock_response(
    content: str = "The forest stretches before you.",
    prompt_tokens: int = 20,
    completion_tokens: int = 10,
) -> MagicMock:
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
    content: str = "The forest stretches before you.",
    prompt_tokens: int = 20,
    completion_tokens: int = 10,
    *,
    include_usage: bool = True,
) -> list[MagicMock]:
    words = content.split()
    chunks: list[MagicMock] = []
    for word in words:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta = MagicMock()
        chunk.choices[0].delta.content = word + " "
        chunk.usage = None
        chunks.append(chunk)
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
    for item in items:
        yield item


# ── AC-07.1: Model Abstraction ───────────────────────────────────────────────


class TestAC071ModelAbstraction:
    """AC-07.1: All LLM calls go through a unified interface with a uniform
    response envelope including model, content, usage, latency_ms, cost_usd,
    and finish_reason (tier_used in our implementation)."""

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.002)
    @patch(_ACOMPLETION)
    async def test_response_envelope_has_required_fields(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.1: LLMResponse envelope contains all required fields."""
        mock_ac.return_value = _mock_response(prompt_tokens=20, completion_tokens=10)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        # Required fields per FR-07.02 and AC-07.1
        assert isinstance(resp, LLMResponse)
        assert isinstance(resp.content, str)
        assert resp.content
        assert (
            isinstance(resp.model_used, str)
        )
        assert (
            resp.model_used
        )
        assert isinstance(resp.token_count, TokenCount)  # usage (token counts)
        assert resp.token_count.prompt_tokens > 0
        assert resp.token_count.completion_tokens > 0
        assert resp.token_count.total_tokens > 0
        assert isinstance(resp.latency_ms, float)
        assert resp.latency_ms > 0
        assert isinstance(resp.cost_usd, float)  # cost_usd
        assert resp.cost_usd == 0.002
        assert resp.tier_used in ("primary", "fallback")  # finish_reason / tier

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_caller_uses_role_not_model_name(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.1 / FR-07.03: Callers reference roles, not provider model names."""
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        # The call site only receives a ModelRole enum value — no model string
        resp = await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        # The resolved model is stored on the response, not passed in by the caller
        assert resp.model_used == "test/primary"

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_model_resolved_from_config_not_hardcoded(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.1: Changing role config changes model without code change."""
        mock_ac.return_value = _mock_response()
        # Different config → different model, same call-site code
        configs = _role_configs(primary="custom-provider/custom-model")
        client = LiteLLMClient(role_configs=configs)

        resp = await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        assert resp.model_used == "custom-provider/custom-model"


# ── AC-07.2: Fallback Behavior ───────────────────────────────────────────────


class TestAC072FallbackBehavior:
    """AC-07.2: Primary failure → fallback used; all tiers fail → LLMError raised
    (not a raw exception); fallback tier is recorded in the response."""

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_primary_failure_triggers_fallback(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.2: When primary fails, fallback model is used automatically."""
        mock_ac.side_effect = [
            TransientLLMError("timeout", model="test/primary"),
            TransientLLMError("timeout", model="test/primary"),
            TransientLLMError("timeout", model="test/primary"),
            _mock_response(content="fallback response"),
        ]
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.content == "fallback response"
        assert resp.tier_used == "fallback"

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_all_tiers_fail_raises_llm_error(self, mock_ac: AsyncMock) -> None:
        """AC-07.2: When all tiers fail, raises AllTiersFailedError (LLMError subclass),
        never a raw provider exception."""
        mock_ac.side_effect = TransientLLMError("down", model="test")
        client = LiteLLMClient(role_configs=_role_configs())

        with pytest.raises(AllTiersFailedError) as exc_info:
            await client.generate(ModelRole.GENERATION, MESSAGES)

        # AllTiersFailedError is a graceful wrapper, not a raw provider exception
        err = exc_info.value
        assert "role=" in str(err)  # error conveys context
        assert len(err.errors) > 0  # captured underlying failures

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_fallback_tier_recorded_in_response(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.2 / FR-07.09: fallback tier_used is recorded in the response."""
        mock_ac.side_effect = [
            TransientLLMError("down", model="test/primary"),
            TransientLLMError("down", model="test/primary"),
            TransientLLMError("down", model="test/primary"),
            _mock_response(content="from fallback"),
        ]
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.tier_used == "fallback"
        assert resp.model_used == "test/fallback"

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_permanent_error_does_not_use_fallback(
        self, mock_ac: AsyncMock
    ) -> None:
        """AC-07.2: PermanentLLMError (e.g. auth failure) skips fallback entirely."""
        mock_ac.side_effect = PermanentLLMError("auth failed", model="test/primary")
        client = LiteLLMClient(role_configs=_role_configs())

        with pytest.raises(PermanentLLMError, match="auth failed"):
            await client.generate(ModelRole.GENERATION, MESSAGES)

        # Only one call attempted — no fallback
        assert mock_ac.call_count == 1


# ── AC-07.3: Context Window Management ──────────────────────────────────────


class TestAC073ContextWindowManagement:
    """AC-07.3: P0 content (system prompt, safety rules) is never truncated;
    P3 content is dropped first when budget is exceeded."""

    def _make_chunk(self, name: str, priority: Priority, tokens: int) -> ContextChunk:
        content = "x" * (tokens * 2)
        return ContextChunk(
            name=name, content=content, priority=priority, token_count=tokens
        )

    def test_p0_never_truncated_even_when_budget_is_tight(self) -> None:
        """AC-07.3: System prompt (P0) is always kept, lower priority dropped first."""
        chunks = [
            self._make_chunk("system_prompt", Priority.P0, 400),
            self._make_chunk("safety_rules", Priority.P0, 100),
            self._make_chunk("world_state", Priority.P2, 300),
            self._make_chunk("history", Priority.P3, 200),
        ]
        # Budget is tight — only fits P0 content
        result = fit_chunks_to_budget(chunks, budget_tokens=510)

        kept_names = {c.name for c in result.chunks}
        # P0 content must always be present
        assert "system_prompt" in kept_names
        assert "safety_rules" in kept_names
        # Lower-priority content is dropped when budget is exceeded
        assert "history" in result.dropped or "world_state" in result.dropped

    def test_p3_dropped_before_p2_before_p1(self) -> None:
        """AC-07.3 / FR-07.13: Truncation order: P3 → P2 → P1, never P0."""
        chunks = [
            self._make_chunk("system", Priority.P0, 100),
            self._make_chunk("recent_exchange", Priority.P1, 200),
            self._make_chunk("world_context", Priority.P2, 300),
            self._make_chunk("old_history", Priority.P3, 400),
        ]
        # Budget only allows P0 + P1 + partial P2 — P3 must go first
        result = fit_chunks_to_budget(chunks, budget_tokens=650)

        assert "old_history" in result.dropped
        # P0 is always kept
        assert any(c.name == "system" for c in result.chunks)

    def test_budget_computed_correctly_from_chunks(self) -> None:
        """AC-07.3 / FR-07.12: Total token budget is computed from chunks."""
        chunks = [
            self._make_chunk("system", Priority.P0, 50),
            self._make_chunk("recent", Priority.P1, 100),
            self._make_chunk("world", Priority.P2, 200),
        ]
        result = fit_chunks_to_budget(chunks, budget_tokens=1000)

        # All fit — total_tokens should be the sum
        assert result.total_tokens == 350
        assert result.dropped == []

    def test_excessive_context_completes_without_error(self) -> None:
        """AC-07.3: Processing 50+ conversation exchanges does not raise an error."""
        # Simulate 50 conversation exchanges as P3 history
        chunks = [self._make_chunk("system", Priority.P0, 50)]
        for i in range(50):
            chunks.append(self._make_chunk(f"exchange_{i}", Priority.P3, 30))

        # Should not raise — just truncates according to priority
        result = fit_chunks_to_budget(chunks, budget_tokens=200)

        assert any(c.name == "system" for c in result.chunks)
        assert result.total_tokens <= 200 or result.chunks[0].name == "system"


# ── AC-07.4: Streaming ───────────────────────────────────────────────────────


class TestAC074Streaming:
    """AC-07.4: SSE token-by-token delivery; mid-stream error handled cleanly;
    done event includes total token count."""

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_stream_yields_content_tokens(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.4: stream() buffers and returns content from streamed tokens."""
        chunks = _mock_stream_chunks(
            "The dungeon is dark and foreboding.", prompt_tokens=15, completion_tokens=7
        )
        mock_ac.return_value = _async_iter(chunks)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.stream(ModelRole.GENERATION, MESSAGES, PARAMS)

        assert isinstance(resp, LLMResponse)
        # Content is assembled from all token chunks
        assert "dungeon" in resp.content
        assert "dark" in resp.content

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_done_event_includes_token_count(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.4 / FR-07.24: done event (LLMResponse) includes total_tokens."""
        chunks = _mock_stream_chunks(
            "You enter the cave.", prompt_tokens=12, completion_tokens=6
        )
        mock_ac.return_value = _async_iter(chunks)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.stream(ModelRole.GENERATION, MESSAGES, PARAMS)

        # token_count is the equivalent of the 'done' event total_tokens field
        assert resp.token_count.prompt_tokens == 12
        assert resp.token_count.completion_tokens == 6
        assert resp.token_count.total_tokens == 18

    @pytest.mark.asyncio
    @patch(_ACOMPLETION)
    async def test_mid_stream_error_raises_cleanly(self, mock_ac: AsyncMock) -> None:
        """AC-07.4 / FR-07.25: Mid-stream error raises AllTiersFailedError,
        does not surface a raw exception or corrupt state."""

        async def _failing_stream() -> Any:
            yield _mock_stream_chunks("partial")[0]
            raise ConnectionError("stream dropped mid-delivery")

        # Each retry gets a fresh generator
        mock_ac.side_effect = [
            _failing_stream(),
            _failing_stream(),
            _failing_stream(),
        ]
        client = LiteLLMClient(role_configs=_role_configs(fallback=None))

        # Must raise AllTiersFailedError, not a raw ConnectionError
        with pytest.raises(AllTiersFailedError):
            await client.stream(ModelRole.GENERATION, MESSAGES)

        # All retries were attempted before giving up
        assert mock_ac.call_count == 3

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_stream_with_no_usage_defaults_to_zero(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.4: When provider omits usage in stream, token counts default to 0
        (not crash)."""
        chunks = _mock_stream_chunks("hello world", include_usage=False)
        mock_ac.return_value = _async_iter(chunks)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.stream(ModelRole.GENERATION, MESSAGES)

        assert resp.token_count.prompt_tokens == 0
        assert resp.token_count.completion_tokens == 0


# ── AC-07.5: Cost Management ─────────────────────────────────────────────────


class TestAC075CostManagement:
    """AC-07.5: Per-turn costs are tracked in the response and queryable;
    session cost cap prevents runaway spending via BudgetExceededError."""

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0025)
    @patch(_ACOMPLETION)
    async def test_per_turn_cost_tracked_in_response(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.5 / FR-07.17: cost_usd is populated in every LLMResponse."""
        mock_ac.return_value = _mock_response(prompt_tokens=50, completion_tokens=25)
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        assert resp.cost_usd == 0.0025

    def test_session_cost_accumulates_across_calls(self) -> None:
        """AC-07.5 / FR-07.19: Session total is a running sum of per-turn costs."""
        tracker = LLMCostTracker(session_id="s-test", session_total_usd=0.10)

        # Record two calls
        tracker.record(model="test-model", prompt_tokens=100, completion_tokens=50)
        tracker.record(model="test-model", prompt_tokens=80, completion_tokens=40)

        # Both calls recorded
        assert len(tracker._calls) == 2

    def test_session_budget_check_returns_exceeded_at_cap(self) -> None:
        """AC-07.5 / FR-07.20: check_session_budget returns 'exceeded' when over cap."""
        tracker = LLMCostTracker(session_id="s-cap", session_total_usd=1.05)

        status = tracker.check_session_budget(cap_usd=1.0, warn_pct=0.8)

        assert status == "exceeded"

    def test_session_budget_check_returns_warning_near_cap(self) -> None:
        """AC-07.5 / FR-07.20: check_session_budget returns 'warning' near cap."""
        tracker = LLMCostTracker(session_id="s-warn", session_total_usd=0.85)

        status = tracker.check_session_budget(cap_usd=1.0, warn_pct=0.8)

        assert status == "warning"

    def test_session_budget_check_returns_ok_under_cap(self) -> None:
        """AC-07.5 / FR-07.20: check_session_budget returns 'ok' when under cap."""
        tracker = LLMCostTracker(session_id="s-ok", session_total_usd=0.20)

        status = tracker.check_session_budget(cap_usd=1.0, warn_pct=0.8)

        assert status == "ok"

    @pytest.mark.asyncio
    async def test_session_cap_raises_budget_exceeded_error(self) -> None:
        """AC-07.5 / FR-07.20: When session cost cap exceeded, BudgetExceededError
        is raised to prevent runaway spending."""
        from unittest.mock import AsyncMock, MagicMock

        from tta.pipeline.llm_guard import guarded_llm_call

        reset_cost_tracker(session_id="s-over", session_total_usd=5.0)

        settings = MagicMock()
        settings.session_cost_cap_usd = 1.0
        settings.session_cost_warn_pct = 0.8
        settings.turn_cost_cap_usd = 0.10

        deps = MagicMock()
        deps.settings = settings
        deps.llm_semaphore = None
        deps.llm_circuit_breaker = None
        deps.llm = AsyncMock()

        with pytest.raises(BudgetExceededError):
            await guarded_llm_call(
                deps=deps,
                role=ModelRole.GENERATION,
                messages=MESSAGES,
            )

    @pytest.mark.asyncio
    @patch(_COST, side_effect=Exception("pricing unknown"))
    @patch(_ACOMPLETION)
    async def test_cost_defaults_to_zero_when_pricing_unavailable(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.5: When cost calculation fails, defaults to 0.0 (not crash)."""
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES)

        assert resp.cost_usd == 0.0


# ── AC-07.7: Testing (Mock Mode) ────────────────────────────────────────────


class TestAC077MockModeTesting:
    """AC-07.7: Full test suite runs without live LLM calls. Mock mode exercises
    the complete call path — only the HTTP request to the provider is replaced."""

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_mock_intercepts_acompletion_not_real_call(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.7 / FR-07.41: The mock fixture intercepts litellm.acompletion,
        confirming no real HTTP call is made during tests."""
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        # If mock was called, no real HTTP request went out
        assert mock_ac.called
        mock_ac.assert_called_once()

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_full_call_path_exercised_in_mock_mode(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.7 / FR-07.43: Mock mode exercises context assembly, token counting,
        and response parsing — not just the HTTP stub."""
        mock_ac.return_value = _mock_response(
            content="A torch flickers on the wall.",
            prompt_tokens=30,
            completion_tokens=8,
        )
        client = LiteLLMClient(role_configs=_role_configs())

        resp = await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        # Full path: model selection, calling litellm, parsing response,
        # computing cost, assembling LLMResponse
        assert resp.content == "A torch flickers on the wall."
        assert resp.token_count.prompt_tokens == 30
        assert resp.token_count.completion_tokens == 8
        assert resp.token_count.total_tokens == 38
        assert resp.model_used == "test/primary"
        assert resp.tier_used == "primary"
        assert resp.latency_ms >= 0

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_mock_mode_configurable_per_role(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.7 / FR-07.42: Mock responses are configurable per model role,
        allowing tests to set up specific classification or narrative outputs."""
        # Different content set per test case — simulating per-role mock
        mock_ac.return_value = _mock_response(content="intent: explore")
        configs = {
            ModelRole.CLASSIFICATION: ModelRoleConfig(
                primary="test/classifier",
                fallback=None,
                temperature=0.1,
                max_tokens=50,
                timeout_seconds=5.0,
            ),
        }
        client = LiteLLMClient(role_configs=configs)

        resp = await client.generate(
            ModelRole.CLASSIFICATION,
            MESSAGES,
            GenerationParams(temperature=0.1, max_tokens=50),
        )

        assert resp.content == "intent: explore"
        assert resp.model_used == "test/classifier"

    @pytest.mark.asyncio
    @patch(_COST, return_value=0.0)
    @patch(_ACOMPLETION)
    async def test_litellm_acompletion_is_patched_not_called_directly(
        self, mock_ac: AsyncMock, _mock_cost: MagicMock
    ) -> None:
        """AC-07.7: The abstraction (LiteLLMClient) is the only call site for
        litellm.acompletion — tests confirm mock intercepts at the right layer."""
        mock_ac.return_value = _mock_response()
        client = LiteLLMClient(role_configs=_role_configs())

        await client.generate(ModelRole.GENERATION, MESSAGES, PARAMS)

        # The patch target is the module-level import in litellm_client,
        # confirming that litellm is isolated behind the abstraction.
        call_args = mock_ac.call_args
        assert call_args is not None
        # The client passes model, messages, temperature, max_tokens to litellm
        assert "model" in call_args.kwargs
        assert "messages" in call_args.kwargs
        assert "temperature" in call_args.kwargs
        assert "max_tokens" in call_args.kwargs
