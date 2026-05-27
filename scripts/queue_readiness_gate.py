#!/usr/bin/env python3
"""Readiness gate for fictional-barnacle autonomous pipeline queues."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUEUE_DIR = ROOT / ".hermes" / "pipeline" / "queue"
IMPLEMENT_READY = "IMPLEMENT_READY_CANDIDATE"


@dataclass(frozen=True)
class QueueClassification:
    id: str
    title: str
    spec_ref: str | None
    spec_status: str
    plan_ref: str | None
    plan_exists: bool
    ac_ids: list[str]
    readiness: str
    readiness_reason: str
    recommended_lane: str
    human_gate_required: bool
    validation_command: str | None
    rationale: str


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def spec_index() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    data = load_json(ROOT / "specs" / "index.json", {"specs": []})
    by_file: dict[str, dict[str, Any]] = {}
    by_num: dict[str, list[dict[str, Any]]] = {}
    for spec in data.get("specs", []):
        file_name = spec.get("file")
        if file_name:
            by_file[file_name] = spec
        num = spec.get("number")
        if num:
            by_num.setdefault(str(num), []).append(spec)
    return by_file, by_num


def plan_exists(plan_ref: str | None) -> bool:
    return bool(plan_ref and (ROOT / plan_ref).exists())


def normalize_status(status: str | None) -> str:
    return (status or "UNKNOWN").strip()


def spec_number_from_file(spec_file: str) -> str:
    match = re.match(r"(\d+)-", spec_file)
    if not match:
        return ""
    return f"S{int(match.group(1)):02d}"


def classify_item(
    item: dict[str, Any],
    by_file: dict[str, dict[str, Any]],
    by_num: dict[str, list[dict[str, Any]]],
) -> QueueClassification:
    item_id = str(item.get("id", "UNKNOWN"))
    title = str(item.get("title", ""))
    spec_ref = item.get("spec_ref")
    spec_file = Path(spec_ref).name if spec_ref else ""
    spec = by_file.get(spec_file, {})
    spec_num_raw = item.get("spec_num") or spec_number_from_file(spec_file)
    spec_num = str(spec_num_raw) if spec_num_raw else ""
    normalized_num = f"S{int(spec_num):02d}" if spec_num.isdigit() else spec_num
    duplicate_num = bool(normalized_num and len(by_num.get(normalized_num, [])) > 1)
    status = normalize_status(spec.get("status") if spec else None)
    ac_ids = list(item.get("ac_ids") or [])
    plan_ref = item.get("plan_ref")
    has_plan = plan_exists(plan_ref)

    if duplicate_num:
        readiness = "INVALID_UNTIL_SPEC_ID_FIXED"
        reason = "DUPLICATE_SPEC_ID"
        lane = "INVALID_UNTIL_SPEC_ID_FIXED"
        human = True
        validation = "uv run python specs/index_specs.py --validate"
        rationale = (
            f"Spec number {normalized_num} is duplicated; queue routing and AC IDs "
            "are ambiguous."
        )
    elif "Draft" in status or "📝" in status:
        readiness = "SPEC_POLISH_REQUIRED"
        reason = "DRAFT_SPEC"
        lane = "SPEC_POLISH"
        human = True
        validation = "uv run python specs/index_specs.py --validate"
        rationale = "Draft specs must not enter the implementation lane."
    elif not has_plan:
        readiness = "PLAN_WRITE_REQUIRED"
        reason = "MISSING_PLAN"
        lane = "PLAN_WRITE"
        human = True
        validation = "uv run python plans/index_plans.py --validate"
        rationale = "Approved spec has no current implementation plan."
    elif any(ac.startswith("AC-12.11") for ac in ac_ids):
        readiness = "TRACE_OR_OPS_DRILL_REQUIRED"
        reason = "OPERATIONAL_AC"
        lane = "TRACE_OR_OPS_DRILL"
        human = True
        validation = "Review docs/ops/sql-restore.md and run a staging restore drill."
        rationale = "AC-12.11 is restore drill evidence, not unit implementation."
    elif any(
        ac.startswith(("AC-10.04", "AC-10.05", "AC-01.01", "AC-01.04", "AC-01.09"))
        for ac in ac_ids
    ):
        readiness = "SUBSTRATE_REQUIRED"
        reason = "SSE_RECONNECT_OR_TIMING_SUBSTRATE"
        lane = "SUBSTRATE_REQUIRED"
        human = True
        validation = "Define SSE timing/reconnect integration harness first."
        rationale = "Streaming/reconnect ACs require missing integration substrate."
    elif any(
        ac.startswith(("AC-02.03", "AC-02.04", "AC-03.07", "AC-05.05")) for ac in ac_ids
    ):
        readiness = "EVAL_OR_LIVE_RUN_GATE_REQUIRED"
        reason = "QUALITY_OR_TIMING_GATE"
        lane = "EVAL_OR_LIVE_RUN_GATE"
        human = True
        validation = "Define eval/live-run gate before implementation claim."
        rationale = "AC requires empirical LLM quality, coherence, or timing evidence."
    elif any(ac.startswith(("AC-24.09", "AC-09.06")) for ac in ac_ids):
        readiness = "PLAN_REVIEW_REQUIRED"
        reason = "PLAN_SLICE_REQUIRED"
        lane = "PLAN_REVIEW"
        human = True
        validation = "Review plan slice and acceptance-test target first."
        rationale = "Approved AC exists, but task packet is too broad for execution."
    elif any(ac.startswith(("AC-06.02", "AC-06.10", "AC-28.08")) for ac in ac_ids):
        readiness = IMPLEMENT_READY
        reason = "BOUNDED_APPROVED_AC_GAP"
        lane = "IMPLEMENT"
        human = False
        validation = "make gate"
        rationale = "Approved spec, existing plan, and bounded implementation AC gap."
    else:
        readiness = "PLAN_REVIEW_REQUIRED"
        reason = "UNCLASSIFIED_APPROVED_AC"
        lane = "PLAN_REVIEW"
        human = True
        validation = "Review spec and plan; add exact validation command."
        rationale = "Conservative fallback: not safe to implement until sliced."

    return QueueClassification(
        id=item_id,
        title=title,
        spec_ref=spec_ref,
        spec_status=status,
        plan_ref=plan_ref,
        plan_exists=has_plan,
        ac_ids=ac_ids,
        readiness=readiness,
        readiness_reason=reason,
        recommended_lane=lane,
        human_gate_required=human,
        validation_command=validation,
        rationale=rationale,
    )


def load_queue(queue_dir: Path = QUEUE_DIR) -> list[dict[str, Any]]:
    if not queue_dir.exists():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(queue_dir.glob("FB-*.json"))
    ]


def build_report() -> dict[str, Any]:
    by_file, by_num = spec_index()
    items = [classify_item(item, by_file, by_num) for item in load_queue()]
    ready = [item for item in items if item.readiness == IMPLEMENT_READY]
    blockers = [
        item for item in items if item.readiness == "INVALID_UNTIL_SPEC_ID_FIXED"
    ]
    return {
        "queue_dir": str(QUEUE_DIR.relative_to(ROOT)),
        "queue_exists": QUEUE_DIR.exists(),
        "items": [asdict(item) for item in items],
        "item_count": len(items),
        "implement_ready_count": len(ready),
        "governance_blocker_count": len(blockers),
    }


def print_text(report: dict[str, Any]) -> None:
    print("Queue readiness gate")
    print(
        "queue_exists={queue_exists} items={item_count} implement_ready="
        "{implement_ready_count} governance_blockers={governance_blocker_count}".format(
            **report
        )
    )
    for item in report["items"]:
        acs = ",".join(item["ac_ids"])
        print(
            f"{item['id']}\t{item['recommended_lane']}\t{item['readiness']}\t"
            f"{acs}\t{item['rationale']}"
        )


def exit_code_for_report(
    report: dict[str, Any],
    *,
    require_implement_ready: bool,
    fail_on_governance_blockers: bool,
) -> int:
    if fail_on_governance_blockers and report["governance_blocker_count"]:
        return 3
    if require_implement_ready and report["implement_ready_count"] == 0:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument(
        "--require-implement-ready",
        action="store_true",
        help="Exit non-zero if no IMPLEMENT_READY_CANDIDATE items are present",
    )
    parser.add_argument(
        "--fail-on-governance-blockers",
        action="store_true",
        help="Exit non-zero when invalid governance blockers are present",
    )
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text(report)

    return exit_code_for_report(
        report,
        require_implement_ready=args.require_implement_ready,
        fail_on_governance_blockers=args.fail_on_governance_blockers,
    )


if __name__ == "__main__":
    raise SystemExit(main())
