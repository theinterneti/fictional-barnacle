"""S15 Observability tests — Wave 23.

Tests for:
- Langfuse record_llm_generation (AC-13, AC-27, privacy)
- OTel child spans from guarded_llm_call (AC-10)
- Pricing YAML loader with caching + fallbacks (AC-30)
- Daily cost summary accumulator + background task (AC-31)
- Langfuse–OTel trace ID linkage (AC-14)
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tta.observability.daily_cost import (
    get_daily_costs,
    get_daily_turns,
    record_daily_cost,
    record_daily_turn,
    reset_daily_costs,
)
from tta.privacy.cost import (
    _DEFAULT_PRICING,
    ModelPricing,
    clear_pricing_cache,
    load_pricing_yaml,
)


@pytest.fixture(autouse=True)
def _clear_pricing():
    """Reset pricing cache between tests."""
    clear_pricing_cache()
    yield
    clear_pricing_cache()


def test_load_pricing_yaml_none_returns_defaults():
    result = load_pricing_yaml(None)
    assert result is _DEFAULT_PRICING


def test_load_pricing_yaml_missing_file_returns_defaults(tmp_path: Path):
    result = load_pricing_yaml(str(tmp_path / "nonexistent.yml"))
    assert result is _DEFAULT_PRICING


def test_load_pricing_yaml_valid_file(tmp_path: Path):
    yml = tmp_path / "pricing.yml"
    yml.write_text(
        textwrap.dedent("""\
        llm_pricing:
          openai/gpt-4o:
            prompt_per_1k_tokens: 0.0025
            completion_per_1k_tokens: 0.01
          groq/llama3:
            prompt_per_1k_tokens: 0.0001
            completion_per_1k_tokens: 0.0002
    """)
    )
    result = load_pricing_yaml(str(yml))
    assert "openai/gpt-4o" in result
    # per_1k * 1000 = per_1M
    assert result["openai/gpt-4o"].prompt_cost_per_1m == 2.50
    assert result["groq/llama3"].completion_cost_per_1m == 0.20


def test_load_pricing_yaml_caches_result(tmp_path: Path):
    yml = tmp_path / "pricing.yml"
    yml.write_text(
        "llm_pricing:\n  openai/gpt-4o:\n"
        "    prompt_per_1k_tokens: 0.0025\n"
        "    completion_per_1k_tokens: 0.01\n"
    )
    r1 = load_pricing_yaml(str(yml))
    r2 = load_pricing_yaml(str(yml))
    assert r1 is r2  # same object — cached


def test_load_pricing_yaml_malformed_returns_defaults(tmp_path: Path):
    yml = tmp_path / "bad.yml"
    yml.write_text("- this is a list not a dict\n")
    result = load_pricing_yaml(str(yml))
    assert result is _DEFAULT_PRICING


def test_load_pricing_yaml_models_are_model_pricing(tmp_path: Path):
    yml = tmp_path / "p.yml"
    yml.write_text(
        "llm_pricing:\n  m1:\n"
        "    prompt_per_1k_tokens: 0.001\n"
        "    completion_per_1k_tokens: 0.002\n"
    )
    result = load_pricing_yaml(str(yml))
    assert isinstance(result["m1"], ModelPricing)
    assert result["m1"].model == "m1"


# ---------------------------------------------------------------------------
# Daily cost accumulator tests (AC-31)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_daily():
    reset_daily_costs()
    yield
    reset_daily_costs()


def test_record_daily_cost_accumulates():
    record_daily_cost("model-a", 0.05)
    record_daily_cost("model-a", 0.10)
    record_daily_cost("model-b", 0.02)
    costs = get_daily_costs()
    assert abs(costs["model-a"] - 0.15) < 1e-9
    assert abs(costs["model-b"] - 0.02) < 1e-9


def test_record_daily_cost_ignores_zero():
    record_daily_cost("model-a", 0.0)
    record_daily_cost("model-a", -1.0)
    assert get_daily_costs() == {}


def test_reset_daily_costs_clears():
    record_daily_cost("m", 1.0)
    record_daily_turn()
    reset_daily_costs()
    assert get_daily_costs() == {}
    assert get_daily_turns() == 0


def test_record_daily_turn_increments():
    record_daily_turn()
    record_daily_turn()
    record_daily_turn()
    assert get_daily_turns() == 3


@pytest.mark.asyncio
async def test_daily_cost_summary_loop_emits_log():
    """Verify the loop emits the log at midnight and resets."""
    from tta.observability.daily_cost import daily_cost_summary_loop

    record_daily_cost("openai/gpt-4o", 0.50)
    record_daily_turn()
    record_daily_turn()

    with patch(
        "tta.observability.daily_cost._seconds_until_midnight_utc",
        return_value=0.0,  # fire immediately
    ):
        task = asyncio.create_task(daily_cost_summary_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # After the loop fired, costs and turns should be reset
    assert get_daily_costs() == {}
    assert get_daily_turns() == 0


def test_record_llm_generation_no_output_truncation():
    """FR-15.17/FR-15.33: full content is sent to Langfuse, not truncated."""
    from tta.observability.langfuse import record_llm_generation

    mock_client = MagicMock()
    mock_trace = MagicMock()
    mock_client.trace.return_value = mock_trace

    long_content = "x" * 2000  # > 500 chars to verify no truncation

    with (
        patch("tta.observability.langfuse._langfuse_client", mock_client),
        patch(
            "tta.observability.langfuse._get_context_ids",
            return_value={
                "correlation_id": None,
                "session_id": None,
                "turn_id": None,
                "player_id": None,
            },
        ),
    ):
        record_llm_generation(
            name="test",
            role="gen",
            messages=[],
            result=_make_llm_response(content=long_content),
            latency_ms=10,
            cost_usd=0.0,
        )

    gen_kwargs = mock_trace.generation.call_args[1]
    assert gen_kwargs["output"] == long_content  # full, not truncated


# ---------------------------------------------------------------------------
# Langfuse record_llm_generation tests (AC-13, AC-27, privacy)
# ---------------------------------------------------------------------------


def _make_llm_response(
    model: str = "openai/gpt-4o",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    content: str = "output text",
    cost_usd: float = 0.001,
) -> SimpleNamespace:
    tc = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    return SimpleNamespace(
        model_used=model,
        token_count=tc,
        content=content,
        cost_usd=cost_usd,
    )


@patch("tta.observability.langfuse._langfuse_client", None)
def test_record_llm_generation_noop_when_disabled():
    """No error when Langfuse is not configured."""
    from tta.observability.langfuse import record_llm_generation

    record_llm_generation(
        name="test",
        role="generation",
        messages=[],
        result=_make_llm_response(),
        latency_ms=100,
        cost_usd=0.001,
    )  # should not raise


def test_record_llm_generation_calls_langfuse():
    """When Langfuse is configured, trace + generation are created."""
    from tta.observability.langfuse import record_llm_generation

    mock_client = MagicMock()
    mock_trace = MagicMock()
    mock_client.trace.return_value = mock_trace

    with (
        patch("tta.observability.langfuse._langfuse_client", mock_client),
        patch(
            "tta.observability.langfuse._get_context_ids",
            return_value={
                "correlation_id": "corr-1",
                "session_id": "sess-1",
                "turn_id": "turn-1",
                "player_id": None,
            },
        ),
    ):
        record_llm_generation(
            name="pipeline.generation",
            role="generation",
            messages=[{"role": "user", "content": "hello"}],
            result=_make_llm_response(),
            latency_ms=200,
            cost_usd=0.003,
            otel_trace_id="abc123",
        )

    mock_client.trace.assert_called_once()
    trace_kwargs = mock_client.trace.call_args[1]
    # FR-15.18: trace keyed by turn_id, name is "turn-<turn_id>"
    assert trace_kwargs["name"] == "turn-turn-1"
    assert trace_kwargs["id"] == "turn-1"
    assert trace_kwargs["metadata"]["otel_trace_id"] == "abc123"

    mock_trace.generation.assert_called_once()
    gen_kwargs = mock_trace.generation.call_args[1]
    assert gen_kwargs["model"] == "openai/gpt-4o"
    assert gen_kwargs["usage"]["input"] == 100


def test_record_llm_generation_strips_pii():
    """PII fields are excluded from Langfuse input."""
    from tta.observability.langfuse import record_llm_generation

    mock_client = MagicMock()
    mock_trace = MagicMock()
    mock_client.trace.return_value = mock_trace

    msgs: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": "hi",
            "name": "Alice",
            "email": "a@b.com",
        }
    ]
    with (
        patch("tta.observability.langfuse._langfuse_client", mock_client),
        patch(
            "tta.observability.langfuse._get_context_ids",
            return_value={
                "correlation_id": None,
                "session_id": None,
                "turn_id": None,
                "player_id": None,
            },
        ),
    ):
        record_llm_generation(
            name="test",
            role="gen",
            messages=msgs,
            result=_make_llm_response(),
            latency_ms=10,
            cost_usd=0.0,
        )

    gen_kwargs = mock_trace.generation.call_args[1]
    sent_input = gen_kwargs["input"]
    for msg in sent_input:
        assert "email" not in msg
        assert "name" not in msg


def test_record_llm_generation_pseudonymizes_player():
    """Player ID is hashed before sending to Langfuse."""
    from tta.observability.langfuse import record_llm_generation

    mock_client = MagicMock()
    mock_client.trace.return_value = MagicMock()

    with (
        patch("tta.observability.langfuse._langfuse_client", mock_client),
        patch(
            "tta.observability.langfuse._get_context_ids",
            return_value={
                "correlation_id": None,
                "session_id": "s1",
                "turn_id": None,
                "player_id": "player-123",
            },
        ),
    ):
        record_llm_generation(
            name="test",
            role="gen",
            messages=[],
            result=_make_llm_response(),
            latency_ms=10,
            cost_usd=0.0,
        )

    trace_kwargs = mock_client.trace.call_args[1]
    # user_id should be a hash, not the raw player ID
    assert trace_kwargs["user_id"] != "player-123"
    assert len(trace_kwargs["user_id"]) >= 16  # pseudonymized hash prefix


# ---------------------------------------------------------------------------
# OTel child spans (AC-10) — via guarded_llm_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guarded_llm_call_creates_otel_span():
    """guarded_llm_call creates an llm_call OTel span with attributes."""
    from tta.pipeline.llm_guard import guarded_llm_call

    response = _make_llm_response(
        model="openai/gpt-4o",
        prompt_tokens=200,
        completion_tokens=80,
        cost_usd=0.005,
    )

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=response)

    deps = SimpleNamespace(
        llm=mock_llm,
        llm_semaphore=None,
        llm_circuit_breaker=None,
        settings=SimpleNamespace(
            session_cost_cap_usd=100.0,
            session_cost_warn_pct=0.8,
            turn_cost_cap_usd=10.0,
        ),
    )

    # Mock the cost tracker
    mock_tracker = MagicMock()
    mock_tracker.check_session_budget.return_value = "ok"
    mock_tracker.turn_cost_usd = 0.0
    mock_tracker.session_id = "test"
    mock_tracker.session_total_usd = 0.0

    # Track span attributes
    recorded_attrs: dict[str, Any] = {}

    class FakeSpan:
        def set_attribute(self, key: str, value: Any) -> None:
            recorded_attrs[key] = value

        def __enter__(self):
            return self

        def __exit__(self, *args: Any):
            pass

    fake_span = FakeSpan()

    class FakeTracer:
        def start_as_current_span(self, name: str, **kwargs: Any):
            return fake_span

    with (
        patch("tta.pipeline.llm_guard.get_cost_tracker", return_value=mock_tracker),
        patch("tta.pipeline.llm_guard.trace") as mock_trace,
        patch("tta.pipeline.llm_guard.record_llm_generation"),
        patch("tta.pipeline.llm_guard.record_daily_cost"),
        patch("tta.pipeline.llm_guard.current_trace_id", return_value="trace-abc"),
    ):
        mock_trace.get_tracer.return_value = FakeTracer()

        from tta.llm.roles import ModelRole

        await guarded_llm_call(deps, ModelRole.GENERATION, [])  # type: ignore[arg-type]

    assert recorded_attrs["llm.model"] == "openai/gpt-4o"
    assert recorded_attrs["llm.tokens.prompt"] == 200
    assert recorded_attrs["llm.tokens.completion"] == 80
    assert recorded_attrs["llm.cost_usd"] == 0.005
    assert "llm.latency_ms" in recorded_attrs


# ---------------------------------------------------------------------------
# Langfuse–OTel linkage (AC-14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guarded_llm_call_passes_otel_trace_to_langfuse():
    """OTel trace_id is forwarded to record_llm_generation."""
    from tta.pipeline.llm_guard import guarded_llm_call

    response = _make_llm_response()
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value=response)

    deps = SimpleNamespace(
        llm=mock_llm,
        llm_semaphore=None,
        llm_circuit_breaker=None,
        settings=SimpleNamespace(
            session_cost_cap_usd=100.0,
            session_cost_warn_pct=0.8,
            turn_cost_cap_usd=10.0,
        ),
    )

    mock_tracker = MagicMock()
    mock_tracker.check_session_budget.return_value = "ok"
    mock_tracker.turn_cost_usd = 0.0

    class FakeSpan:
        def set_attribute(self, key: str, value: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args: Any):
            pass

    class FakeTracer:
        def start_as_current_span(self, name: str, **kwargs: Any):
            return FakeSpan()

    with (
        patch("tta.pipeline.llm_guard.get_cost_tracker", return_value=mock_tracker),
        patch("tta.pipeline.llm_guard.trace") as mock_trace,
        patch("tta.pipeline.llm_guard.record_llm_generation") as mock_record,
        patch("tta.pipeline.llm_guard.record_daily_cost"),
        patch("tta.pipeline.llm_guard.current_trace_id", return_value="otel-trace-xyz"),
    ):
        mock_trace.get_tracer.return_value = FakeTracer()

        from tta.llm.roles import ModelRole

        await guarded_llm_call(deps, ModelRole.GENERATION, [])  # type: ignore[arg-type]

    mock_record.assert_called_once()
    call_kwargs = mock_record.call_args[1]
    assert call_kwargs["otel_trace_id"] == "otel-trace-xyz"
