#!/usr/bin/env python3
"""TTA Narrative Quality Experiment Runner.

Runs Langfuse dataset experiments against the TTA API for narrative
quality evaluation. Tests narrative coherence, world consistency,
choice quality, engagement, persona fidelity, and error handling.

Pattern from the article: dataset.run_experiment(task=fn, evaluators=[...])

Usage:
  LANGFUSE_PUBLIC_KEY=pk-lf-... LANGFUSE_SECRET_KEY=sk-lf-... \\
  TTA_URL=http://localhost:8010 \\
  python3 scripts/run_tta_experiment.py

  # Dry run (no Langfuse, no TTA — just print what would happen):
  python3 scripts/run_tta_experiment.py --dry-run
"""

from __future__ import annotations

import argparse, json, os, sys, time
from typing import Any

os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")

import httpx
from langfuse import Langfuse

DATASET_NAME = "tta-narrative-quality"
TTA_URL = os.environ.get("TTA_URL", "http://localhost:8010")


# ── Task function ─────────────────────────────────────────────────────────


def tta_task(*, item: Any, **kwargs: Any) -> str:
    """Send a player input to TTA and return the narrative response."""
    player_input = item.input.get("player_input", "") if isinstance(item.input, dict) else str(item.input)
    dimension = item.metadata.get("dimension", "unknown") if item.metadata else "unknown"

    try:
        start = time.monotonic()
        resp = httpx.post(
            f"{TTA_URL}/api/v1/turns",
            json={"player_input": player_input},
            timeout=60.0,
        )
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code != 200:
            kwargs["metadata"] = {
                "error": f"HTTP {resp.status_code}",
                "dimension": dimension,
                "latency_ms": round(elapsed, 1),
            }
            return f"ERROR: HTTP {resp.status_code}"

        data = resp.json()
        narrative = data.get("narrative", "") or data.get("content", "")
        kwargs["metadata"] = {
            "dimension": dimension,
            "latency_ms": round(elapsed, 1),
            "turn_id": data.get("turn_id", ""),
            "model_used": data.get("model", ""),
            "tokens": data.get("token_count", {}),
        }
        return narrative

    except Exception as exc:
        kwargs["metadata"] = {"error": str(exc)[:200], "dimension": dimension}
        return f"ERROR: {exc}"


# ── Evaluators ────────────────────────────────────────────────────────────


def narrative_length(*, output: str, **kwargs: Any) -> float:
    """Narrative should be substantive (100-2000 chars)."""
    if not output or output.startswith("ERROR"):
        return 0.0
    length = len(output)
    if 100 <= length <= 2000:
        return 1.0
    if length < 50:
        return 0.2
    if length < 100:
        return 0.5 + (length - 50) / 100
    return max(0.3, 1.0 - (length - 2000) / 3000)


def narrative_coherence(*, output: str, **kwargs: Any) -> float:
    """Check for basic coherence markers in narrative text."""
    if not output or output.startswith("ERROR"):
        return 0.0
    output_lower = output.lower()
    # Coherence heuristics: has sentences, no excessive repetition, logical connectors
    sentences = [s.strip() for s in output.replace("\n", ". ").split(".") if s.strip()]
    if len(sentences) < 1:
        return 0.1
    if len(sentences) < 2:
        return 0.4
    # Check for variety
    unique_sentences = len(set(s[:30] for s in sentences))
    variety = min(1.0, unique_sentences / len(sentences))
    return 0.5 + variety * 0.5


def dimension_match(*, output: str, metadata: dict | None = None, expected_output: Any = None, **kwargs: Any) -> float:
    """Check if output addresses the evaluation dimension."""
    if not output or not metadata:
        return 0.0
    dimension = metadata.get("dimension", "")
    criteria = (
        expected_output.get("criteria", "")
        if isinstance(expected_output, dict)
        else str(expected_output or "")
    )

    # Dimension-specific checks
    if dimension == "error_handling":
        # Error handling: response should NOT be an error/empty
        return 1.0 if len(output) > 20 and "error" not in output.lower() else 0.3

    if dimension == "persona_curious":
        return 0.8 if any(w in output.lower() for w in ["examine", "curious", "study", "observe", "careful"]) else 0.4

    if dimension == "persona_warrior":
        return 0.8 if any(w in output.lower() for w in ["attack", "strike", "charge", "slash", "blade", "axe", "weapon"]) else 0.4

    if dimension == "choice_quality":
        # Choice quality: response should present options
        return 0.8 if "?" in output or "choice" in output.lower() or "decide" in output.lower() else 0.4

    # Default: check criteria keywords
    keywords = criteria.lower().split(",") if criteria else []
    if not keywords:
        return 0.5
    hits = sum(1 for kw in keywords if kw.strip() in output.lower())
    return min(1.0, hits / max(len(keywords) * 0.5, 1))


def latency_quality(*, metadata: dict | None = None, **kwargs: Any) -> float:
    """Score latency (faster = better, but not too fast)."""
    if not metadata or "latency_ms" not in metadata:
        return 0.0
    ms = metadata["latency_ms"]
    if ms < 100:
        return 0.4  # Suspiciously fast — likely error
    if ms < 500:
        return 1.0
    if ms < 5000:
        return 1.0 - (ms - 500) / 4500
    return 0.0


def composite_score(*, item_results: list, **kwargs: Any) -> float:
    """Aggregate evaluator — averages all per-item scores across the run."""
    if not item_results:
        return 0.0
    all_scores: list[float] = []
    for result in item_results:
        evals = getattr(result, "evaluations", []) or []
        for e in evals:
            val = getattr(e, "value", None)
            if isinstance(val, (int, float)):
                all_scores.append(float(val))
    return round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0


# ── Main ──────────────────────────────────────────────────────────────────


def run(args: argparse.Namespace) -> None:
    if args.dry_run:
        print("DRY RUN — no Langfuse, no TTA calls\n")
        _dry_run()
        return

    pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not pk:
        print("ERROR: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY required")
        sys.exit(1)

    client = Langfuse(public_key=pk, secret_key=sk, base_url="http://localhost:3001")
    dataset = client.get_dataset(DATASET_NAME)
    items = dataset.items if hasattr(dataset, "items") else []
    print(f"Dataset: {DATASET_NAME} ({len(items)} items)")
    if not items:
        print("No items — seed first: scripts/seed_tta_dataset.py")
        sys.exit(1)

    # Dimension distribution
    dims: dict[str, int] = {}
    for it in items:
        d = (it.metadata or {}).get("dimension", "unknown")
        dims[d] = dims.get(d, 0) + 1
    print(f"Dimensions: {json.dumps(dims)}")
    print(f"TTA URL: {TTA_URL}")

    result = dataset.run_experiment(
        name=args.name or "tta-narrative-baseline",
        description="Baseline TTA narrative quality evaluation",
        task=tta_task,
        evaluators=[narrative_length, narrative_coherence, dimension_match, latency_quality],
        run_evaluators=[composite_score],
        max_concurrency=1,
        include_item_results=True,
    )
    print(result.format())


def _dry_run() -> None:
    samples = [
        ("narrative_coherence", "You enter a misty forest clearing. What do you do?"),
        ("world_consistency", "I draw my sword and charge the shadow."),
        ("error_handling", "asdfghjkl"),
    ]
    for dimension, player_input in samples:
        print(f"  [{dimension}] {player_input}")
    print("\n  12 items would be sent to TTA at", TTA_URL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--name", default="tta-narrative-baseline")
    args = parser.parse_args()
    run(args)
