"""S45 — CLI entry point for the evaluation pipeline.

Usage:
    python -m tta.eval [options]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tta.eval.models import BatchConfig
from tta.eval.pipeline import EvaluationPipeline


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tta.eval",
        description="Run the TTA evaluation pipeline (S45)",
    )
    p.add_argument(
        "--mode",
        choices=["ci", "local", "full"],
        default="ci",
        help="Evaluation mode (default: ci)",
    )
    p.add_argument(
        "--api-base-url",
        default="",
        help="Base URL of the TTA API",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="TTA API key (optional)",
    )
    p.add_argument(
        "--baseline",
        default="data/eval_baseline.json",
        help="Path to baseline scores JSON",
    )
    p.add_argument(
        "--output-dir",
        default="data/eval_output",
        help="Directory for output reports",
    )
    p.add_argument(
        "--human-feedback-dir",
        default=None,
        help="Directory containing human feedback JSON files",
    )
    return p


async def _main(args: argparse.Namespace) -> int:
    config = BatchConfig(
        mode=args.mode,
        baseline_path=args.baseline,
        output_dir=args.output_dir,
        human_feedback_dir=args.human_feedback_dir,
    )
    pipeline = EvaluationPipeline(
        config=config,
        api_base_url=args.api_base_url,
        api_key=args.api_key,
    )
    _, exit_code = await pipeline.run()
    return exit_code


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    code = asyncio.run(_main(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
