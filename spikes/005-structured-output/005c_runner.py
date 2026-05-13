#!/usr/bin/env python3
"""005c: PydanticAI — direct runner (avoids subprocess overhead)."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import litellm  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.litellm import LiteLLMModel  # noqa: E402
from spikes.structured_output_005.shared import (  # noqa: E402
    IntentOutput,
    SYSTEM_PROMPT,
    TEST_INPUTS,
)

MODEL_NAME = sys.argv[1] if len(sys.argv) > 1 else "openai/tta"
N = 100

print(f"005c PydanticAI — model={MODEL_NAME}, n={N}\n", flush=True)

model = LiteLLMModel(MODEL_NAME)
agent = Agent(model, result_type=IntentOutput, system_prompt=SYSTEM_PROMPT)

results = []
errors = []
latencies = []
start_time = time.monotonic()

for i, inp in enumerate(TEST_INPUTS[:N]):
    call_start = time.monotonic()
    try:
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(agent.run(inp))
        elapsed = (time.monotonic() - call_start) * 1000
        results.append(True)
        latencies.append(elapsed)
    except Exception as e:
        results.append(False)
        errors.append(f"[{i}] {type(e).__name__}: {str(e)[:60]}")

    if (i + 1) % 20 == 0:
        passed = sum(results)
        elapsed_total = time.monotonic() - start_time
        print(
            f"  Progress: {i+1}/{N}, pass={passed}/{i+1} ({passed/(i+1):.1%}), elapsed={elapsed_total:.0f}s",
            flush=True,
        )

passed = sum(results)
total = len(results)
elapsed_total = time.monotonic() - start_time

stats = {
    "mode": "pydantic_ai",
    "passed": passed,
    "total": total,
    "pass_rate": passed / total,
    "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
    "min_latency_ms": round(min(latencies), 1) if latencies else 0,
    "max_latency_ms": round(max(latencies), 1) if latencies else 0,
    "errors": errors[:10],
    "elapsed_s": round(elapsed_total, 1),
}

print(f"\n  FINAL: {passed}/{total} = {passed/total:.1%}, avg_lat={stats['avg_latency_ms']}ms, elapsed={elapsed_total:.0f}s", flush=True)
if errors:
    print(f"  First errors: {errors[:3]}", flush=True)

with open("spikes/005-structured-output/results_005c.json", "w") as f:
    json.dump(stats, f, indent=2)
print("Saved to spikes/005-structured-output/results_005c.json")
