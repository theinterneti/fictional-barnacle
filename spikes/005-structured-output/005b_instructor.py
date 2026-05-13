"""005b: Instructor — Pydantic model → retry loop → validated output.

Instructor patches litellm with automatic retry and re-ask when the LLM
produces output that doesn't validate against the Pydantic model.

Key advantage: if the model produces almost-valid JSON, instructor asks
it to fix the specific validation error rather than starting over.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENAI_API_BASE", "http://localhost:3456/v1")

import instructor
import litellm  # noqa: E402

# Load shared module from spike directory
_shared_path = Path(__file__).parent / "shared.py"
_spec = importlib.util.spec_from_file_location("shared", _shared_path)
_shared = importlib.util.module_from_spec(_spec)
sys.modules["shared"] = _shared
_spec.loader.exec_module(_shared)
IntentOutput = _shared.IntentOutput
SYSTEM_PROMPT = _shared.SYSTEM_PROMPT
TEST_INPUTS = _shared.TEST_INPUTS


def create_client(model: str, mode: instructor.Mode = instructor.Mode.TOOLS):
    """Create an instructor-patched litellm client."""
    return instructor.from_litellm(
        litellm.completion,
        mode=mode,
    )


def call_instructor(
    user_input: str,
    model: str,
    client: Any,
) -> dict[str, Any]:
    """Call via instructor with Pydantic response_model."""
    start = time.monotonic()
    try:
        result, raw = client.chat.completions.create_with_completion(
            model=model,
            response_model=IntentOutput,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            max_retries=2,
            temperature=0.1,
            max_tokens=256,
        )
        elapsed = time.monotonic() - start
        usage = raw.usage if raw else None
        return {
            "valid": True,
            "output": result,
            "latency_ms": elapsed * 1000,
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        }
    except instructor.exceptions.InstructorRetryException:
        elapsed = time.monotonic() - start
        return {
            "valid": False,
            "output": None,
            "latency_ms": elapsed * 1000,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "error": "instructor_retry_exhausted",
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


def run(mode_str: str, model: str, n: int = 100) -> dict[str, Any]:
    """Run N calls and return aggregate stats."""
    inst_mode = {
        "tools": instructor.Mode.TOOLS,
        "json": instructor.Mode.JSON,
        "md_json": instructor.Mode.MD_JSON,
    }[mode_str]

    client = create_client(model, inst_mode)

    results = []
    errors = []
    latencies = []
    prompt_toks = []
    completion_toks = []

    for i, user_input in enumerate(TEST_INPUTS[:n]):
        result = call_instructor(user_input, model, client)
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
        "mode": f"instructor_{mode_str}",
        "model": model,
        "passed": passed,
        "total": total,
        "pass_rate": passed / total if total else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "avg_prompt_tokens": round(sum(prompt_toks) / len(prompt_toks), 1) if prompt_toks else 0,
        "avg_completion_tokens": round(sum(completion_toks) / len(completion_toks), 1) if completion_toks else 0,
        "errors": errors[:10],
    }


if __name__ == "__main__":
    import sys

    model = sys.argv[1] if len(sys.argv) > 1 else "openai/tta"
    print(f"005b Instructor — model={model}\n")

    for mode in ["tools", "json", "md_json"]:
        print(f"--- instructor_{mode} ---")
        try:
            stats = run(mode, model)
            print(
                f"  pass_rate: {stats['pass_rate']:.1%} ({stats['passed']}/{stats['total']})"
            )
            print(f"  avg_latency: {stats['avg_latency_ms']}ms")
            print(f"  avg_tokens: {stats['avg_prompt_tokens']}p + {stats['avg_completion_tokens']}c")
            if stats["errors"]:
                for e in stats["errors"]:
                    print(f"  FAIL: {e}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
        print()
