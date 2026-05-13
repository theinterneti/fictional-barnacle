"""005c: PydanticAI — structured output via Agent with result_type.

PydanticAI is a full agent framework. For this spike we only test its
structured output capability, not its agent/planning features.

Requires: pip install pydantic-ai
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENAI_API_BASE", "http://localhost:3456/v1")

from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.litellm import LiteLLMModel  # noqa: E402

# Load shared module from spike directory
_shared_path = Path(__file__).parent / "shared.py"
_spec = importlib.util.spec_from_file_location("shared", _shared_path)
_shared = importlib.util.module_from_spec(_spec)
sys.modules["shared"] = _shared
_spec.loader.exec_module(_shared)
IntentOutput = _shared.IntentOutput
SYSTEM_PROMPT = _shared.SYSTEM_PROMPT
TEST_INPUTS = _shared.TEST_INPUTS


def create_agent(model_name: str) -> Agent:
    """Create a PydanticAI agent with structured output."""
    model = LiteLLMModel(model_name)
    return Agent(
        model,
        result_type=IntentOutput,
        system_prompt=SYSTEM_PROMPT,
    )


async def call_pydantic_ai(
    user_input: str,
    agent: Agent,
) -> dict[str, Any]:
    """Run a single classification through PydanticAI agent."""
    start = time.monotonic()
    try:
        result = await agent.run(user_input)
        elapsed = time.monotonic() - start
        usage = result.usage()
        return {
            "valid": True,
            "output": result.data,
            "latency_ms": elapsed * 1000,
            "prompt_tokens": usage.request_tokens if usage else 0,
            "completion_tokens": usage.response_tokens if usage else 0,
        }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "valid": False,
            "output": None,
            "latency_ms": elapsed * 1000,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "error": f"{type(e).__name__}: {e}",
        }


async def run_async(model: str, n: int = 100) -> dict[str, Any]:
    """Run N async calls through PydanticAI."""
    agent = create_agent(model)

    results = []
    errors = []
    latencies = []
    prompt_toks = []
    completion_toks = []

    for i, user_input in enumerate(TEST_INPUTS[:n]):
        result = await call_pydantic_ai(user_input, agent)
        results.append(result["valid"])
        if result["valid"]:
            latencies.append(result["latency_ms"])
            prompt_toks.append(result["prompt_tokens"])
            completion_toks.append(result["completion_tokens"])
        else:
            errors.append(f"[{i}] {result.get('error', 'unknown')}")

    passed = sum(results)
    total = len(results)

    return {
        "mode": "pydantic_ai",
        "model": model,
        "passed": passed,
        "total": total,
        "pass_rate": passed / total if total else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "avg_prompt_tokens": round(sum(prompt_toks) / len(prompt_toks), 1)
        if prompt_toks
        else 0,
        "avg_completion_tokens": round(sum(completion_toks) / len(completion_toks), 1)
        if completion_toks
        else 0,
        "errors": errors[:10],
    }


if __name__ == "__main__":
    import asyncio
    import sys

    model = sys.argv[1] if len(sys.argv) > 1 else "openai/tta"
    print(f"005c PydanticAI — model={model}\n")

    stats = asyncio.run(run_async(model))
    print(f"  pass_rate: {stats['pass_rate']:.1%} ({stats['passed']}/{stats['total']})")
    print(f"  avg_latency: {stats['avg_latency_ms']}ms")
    print(
        f"  avg_tokens: {stats['avg_prompt_tokens']}p + {stats['avg_completion_tokens']}c"
    )
    if stats["errors"]:
        for e in stats["errors"]:
            print(f"  FAIL: {e}")
