#!/usr/bin/env python3
"""005: Structured Output Spike — Master Runner.

Runs all three approaches (LiteLLM native, Instructor, PydanticAI) against
the same models with the same inputs, measuring pass rate, latency, and tokens.

Usage:
    op run --env-file=.env -- python spikes/005-structured-output/run_all.py [MODEL]

Default model: openai/tta (FMR auto-routing)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SPIKE_DIR, "..", ".."))


def run_module(name: str, model: str, api_key: str) -> dict[str, Any] | None:
    """Run a spike module as a subprocess and parse its JSON output."""
    script = os.path.join(SPIKE_DIR, name)
    if not os.path.exists(script):
        print(f"  SKIP: {name} not found")
        return None

    start = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, script, model],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": REPO_ROOT, "OPENAI_API_KEY": api_key},
        )
        elapsed = time.monotonic() - start
        if result.returncode != 0:
            print(f"  FAILED (exit={result.returncode}): {result.stderr[:200]}")
            return None

        # Parse the human-readable output — extract pass rates
        lines = result.stdout.split("\n")
        results = {
            "name": name.replace(".py", ""),
            "elapsed_s": round(elapsed, 1),
            "modes": {},
        }

        current_mode = None
        for line in lines:
            if line.startswith("--- ") and line.endswith(" ---"):
                current_mode = line.strip("- ")
            elif "pass_rate:" in line and current_mode:
                try:
                    rate_str = line.split("pass_rate:")[1].split("%")[0].strip()
                    # Format: "85.0% (85/100)" or "0.85 (85/100)"
                    if "/" in rate_str:
                        parts = rate_str.strip("()").split("/")
                        if len(parts) >= 2:
                            passed = int(parts[0].strip())
                            total = int(parts[1].strip().split(")")[0])
                        else:
                            continue
                    else:
                        rate = float(rate_str)
                        passed = int(rate * 100)
                        total = 100
                    results["modes"][current_mode] = {
                        "passed": passed,
                        "total": total,
                    }
                except (ValueError, IndexError):
                    pass

        return results
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 600s")
        return None


def print_table(rows: list[dict[str, Any]]) -> None:
    """Print head-to-head comparison table."""
    if not rows:
        print("No results to display.")
        return

    print("\n" + "=" * 80)
    print("HEAD-TO-HEAD: Structured Output Approaches")
    print("=" * 80)
    print(
        f"{'Approach':<25} {'Mode':<20} {'Pass Rate':<12} {'Status'}"
    )
    print("-" * 80)

    for row in rows:
        approach = row["approach"]
        for mode_name, mode_data in row.get("modes", {}).items():
            passed = mode_data["passed"]
            total = mode_data["total"]
            rate = passed / total if total else 0
            status = "✓" if rate >= 0.95 else ("⚠" if rate >= 0.80 else "✗")
            print(
                f"{approach:<25} {mode_name:<20} {rate:>8.1%} ({passed}/{total})   {status}"
            )

    print("-" * 80)
    print("Winner: TBD — see verdict section below.\n")


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "openai/tta"
    # FMR tenant token required for authentication
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set. Set it to the FMR tenant token.")
        print("  export OPENAI_API_KEY=$(op read 'op://Projects/agent-adam-service-account/credential')")
        sys.exit(1)
    print(f"005 Structured Output Spike — model={model}")
    print(f"Repo root: {REPO_ROOT}\n")

    all_results = []

    # --- 005a: LiteLLM Native ---
    print("=" * 60)
    print("005a: LiteLLM Native response_format")
    print("=" * 60)
    result = run_module("005a_litellm_native.py", model, api_key)
    if result:
        result["approach"] = "005a_litellm_native"
        all_results.append(result)

    # --- 005b: Instructor ---
    print("\n" + "=" * 60)
    print("005b: Instructor")
    print("=" * 60)
    result = run_module("005b_instructor.py", model, api_key)
    if result:
        result["approach"] = "005b_instructor"
        all_results.append(result)

    # --- 005c: PydanticAI ---
    print("\n" + "=" * 60)
    print("005c: PydanticAI")
    print("=" * 60)
    try:
        import pydantic_ai  # noqa: F401
        result = run_module("005c_pydantic_ai.py", model, api_key)
        if result:
            result["approach"] = "005c_pydantic_ai"
            all_results.append(result)
    except ImportError:
        print("  SKIP: pydantic-ai not installed. Run: uv add pydantic-ai")
        print("  (STRATEGY defers PydanticAI to v3+; installing only for spike comparison)")

    # --- Results ---
    print_table(all_results)

    # Save to JSON for reference
    out_path = os.path.join(SPIKE_DIR, "results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"Results saved to: {out_path}")


if __name__ == "__main__":
    main()
