"""005a: LiteLLM native response_format.

Tests two modes:
- json_object: broader support, older API
- json_schema: OpenAI-style strict schema, newer
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENAI_API_BASE", "http://localhost:3456/v1")

import litellm  # noqa: E402

# Load shared module from spike directory (numeric dir = not importable as package)
_shared_path = Path(__file__).parent / "shared.py"
_spec = importlib.util.spec_from_file_location("shared", _shared_path)
_shared = importlib.util.module_from_spec(_spec)
sys.modules["shared"] = _shared
_spec.loader.exec_module(_shared)
IntentOutput = _shared.IntentOutput
SYSTEM_PROMPT = _shared.SYSTEM_PROMPT
TEST_INPUTS = _shared.TEST_INPUTS


def call_json_object(user_input: str, model: str) -> dict[str, Any]:
    """LiteLLM with response_format={"type": "json_object"}."""
    start = time.monotonic()
    raw = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        temperature=0.1,
        max_tokens=256,
        response_format={"type": "json_object"},
    )
    elapsed = time.monotonic() - start
    content = raw.choices[0].message.content or ""
    usage = raw.usage
    return {
        "content": content,
        "latency_ms": elapsed * 1000,
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def call_json_schema(user_input: str, model: str) -> dict[str, Any]:
    """LiteLLM with response_format={"type": "json_schema", ...}."""
    start = time.monotonic()
    raw = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        temperature=0.1,
        max_tokens=256,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "intent_output",
                "strict": True,
                "schema": IntentOutput.model_json_schema(),
            },
        },
    )
    elapsed = time.monotonic() - start
    content = raw.choices[0].message.content or ""
    usage = raw.usage
    return {
        "content": content,
        "latency_ms": elapsed * 1000,
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def call_prompt_only(user_input: str, model: str) -> dict[str, Any]:
    """Baseline: no response_format, just prompt engineering for JSON."""
    prompt = (
        SYSTEM_PROMPT
        + "\n\nRespond ONLY with valid JSON, no other text. Format:\n"
        + json.dumps(
            {
                "intent": "explore",
                "confidence": 0.9,
                "entities": ["room"],
                "emotional_tone": "curious",
                "summary": "player wants to look around",
            }
        )
    )
    start = time.monotonic()
    raw = litellm.completion(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.1,
        max_tokens=256,
    )
    elapsed = time.monotonic() - start
    content = raw.choices[0].message.content or ""
    usage = raw.usage
    return {
        "content": content,
        "latency_ms": elapsed * 1000,
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
    }


def validate(content: str) -> tuple[bool, str]:
    """Try to parse and validate the JSON output."""
    if not content.strip():
        return False, "empty response"

    # Strip markdown code fences if present
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 2:
            text = "\n".join(lines[1:-1]).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"json_parse_error: {e}"

    try:
        IntentOutput.model_validate(data)
        return True, "valid"
    except Exception as e:
        return False, f"validation_error: {e}"


def run(mode: str, model: str, n: int = 100) -> dict[str, Any]:
    """Run N calls and return aggregate stats."""
    call_fn = {
        "json_object": call_json_object,
        "json_schema": call_json_schema,
        "prompt_only": call_prompt_only,
    }[mode]

    results = []
    errors = []
    latencies = []
    prompt_toks = []
    completion_toks = []

    for i, user_input in enumerate(TEST_INPUTS[:n]):
        try:
            result = call_fn(user_input, model)
            ok, msg = validate(result["content"])
            results.append(ok)
            if ok:
                latencies.append(result["latency_ms"])
                prompt_toks.append(result["prompt_tokens"])
                completion_toks.append(result["completion_tokens"])
            else:
                errors.append(f"[{i}] {msg}: {result['content'][:80]}...")
        except Exception as e:
            results.append(False)
            errors.append(f"[{i}] {type(e).__name__}: {e}")

    passed = sum(results)
    total = len(results)

    return {
        "mode": mode,
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
        "errors": errors[:10],  # first 10 errors only
    }


if __name__ == "__main__":
    import sys

    model = sys.argv[1] if len(sys.argv) > 1 else "openai/tta"
    print(f"005a LiteLLM Native — model={model}\n")

    for mode in ["prompt_only", "json_object", "json_schema"]:
        print(f"--- {mode} ---")
        stats = run(mode, model)
        print(
            f"  pass_rate: {stats['pass_rate']:.1%} ({stats['passed']}/{stats['total']})"
        )
        print(f"  avg_latency: {stats['avg_latency_ms']}ms")
        print(
            f"  avg_tokens: {stats['avg_prompt_tokens']}p + {stats['avg_completion_tokens']}c"
        )
        if stats["errors"]:
            for e in stats["errors"]:
                print(f"  FAIL: {e}")
        print()
