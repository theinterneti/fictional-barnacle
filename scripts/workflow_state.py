#!/usr/bin/env python3
"""Deterministic SDD work-item state machine."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORK_DIR = ROOT / ".barnacle" / "work" / "items"
TERMINAL_STAGES = {"RELEASED", "BLOCKED", "CANCELLED"}
STAGES = (
    "DISCOVERED",
    "DRAFT_SPEC",
    "SPEC_REVIEW",
    "APPROVED_SPEC",
    "PLAN_DRAFT",
    "PLAN_REVIEW",
    "PLAN_APPROVED",
    "IMPLEMENTING",
    "TESTING",
    "TRACE_DECORATED",
    "LOCAL_GATE_GREEN",
    "REVIEWED",
    "PR_OPEN",
    "CI_GREEN",
    "MERGED",
    "RELEASED",
    "BLOCKED",
    "CANCELLED",
)
ALLOWED_NEXT = {
    "DISCOVERED": {"DRAFT_SPEC", "BLOCKED", "CANCELLED"},
    "DRAFT_SPEC": {"SPEC_REVIEW", "BLOCKED", "CANCELLED"},
    "SPEC_REVIEW": {"APPROVED_SPEC", "DRAFT_SPEC", "BLOCKED", "CANCELLED"},
    "APPROVED_SPEC": {"PLAN_DRAFT", "BLOCKED", "CANCELLED"},
    "PLAN_DRAFT": {"PLAN_REVIEW", "BLOCKED", "CANCELLED"},
    "PLAN_REVIEW": {"PLAN_APPROVED", "PLAN_DRAFT", "BLOCKED", "CANCELLED"},
    "PLAN_APPROVED": {"IMPLEMENTING", "BLOCKED", "CANCELLED"},
    "IMPLEMENTING": {"TESTING", "BLOCKED", "CANCELLED"},
    "TESTING": {"TRACE_DECORATED", "LOCAL_GATE_GREEN", "IMPLEMENTING", "BLOCKED"},
    "TRACE_DECORATED": {"LOCAL_GATE_GREEN", "IMPLEMENTING", "BLOCKED"},
    "LOCAL_GATE_GREEN": {"REVIEWED", "IMPLEMENTING", "BLOCKED"},
    "REVIEWED": {"PR_OPEN", "IMPLEMENTING", "BLOCKED"},
    "PR_OPEN": {"CI_GREEN", "IMPLEMENTING", "BLOCKED"},
    "CI_GREEN": {"MERGED", "IMPLEMENTING", "BLOCKED"},
    "MERGED": {"RELEASED"},
    "RELEASED": set(),
    "BLOCKED": {"DISCOVERED", "DRAFT_SPEC", "PLAN_DRAFT", "IMPLEMENTING", "CANCELLED"},
    "CANCELLED": set(),
}


@dataclass(frozen=True)
class WorkItem:
    id: str
    title: str
    stage: str
    spec_ref: str = ""
    plan_ref: str = ""
    ac_ids: list[str] = field(default_factory=list)
    branch: str = ""
    validation_commands: list[str] = field(default_factory=list)
    evidence_files: list[str] = field(default_factory=list)
    last_gate_result: str = ""
    review_status: str = ""
    pr_number: int | None = None
    release_note_required: bool = False
    changelog_entry: str = ""
    blocked_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkItem:
        allowed = {field.name for field in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass(frozen=True)
class TransitionDecision:
    allowed: bool
    reason: str


def load_items(work_dir: Path = WORK_DIR) -> list[WorkItem]:
    if not work_dir.exists():
        return []
    items: list[WorkItem] = []
    for path in sorted(work_dir.glob("FB-*.json")):
        items.append(WorkItem.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return items


def item_path(item_id: str, work_dir: Path = WORK_DIR) -> Path:
    return work_dir / f"{item_id}.json"


def save_item(item: WorkItem, work_dir: Path = WORK_DIR) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    item_path(item.id, work_dir).write_text(
        json.dumps(asdict(item), indent=2) + "\n",
        encoding="utf-8",
    )


def can_advance(item: WorkItem, target_stage: str) -> TransitionDecision:
    if item.stage not in STAGES:
        return TransitionDecision(False, f"unknown current stage: {item.stage}")
    if target_stage not in STAGES:
        return TransitionDecision(False, f"unknown target stage: {target_stage}")
    if target_stage not in ALLOWED_NEXT[item.stage]:
        return TransitionDecision(
            False, f"transition {item.stage}->{target_stage} is not allowed"
        )
    if target_stage in {"PLAN_DRAFT", "PLAN_REVIEW", "PLAN_APPROVED", "IMPLEMENTING"}:
        spec_check = _existing_ref(item.spec_ref, "spec_ref")
        if spec_check:
            return TransitionDecision(False, spec_check)
    if target_stage in {"PLAN_APPROVED", "IMPLEMENTING"}:
        plan_check = _existing_ref(item.plan_ref, "plan_ref")
        if plan_check:
            return TransitionDecision(False, plan_check)
    if target_stage == "LOCAL_GATE_GREEN" and item.last_gate_result != "pass":
        return TransitionDecision(
            False, "LOCAL_GATE_GREEN requires last_gate_result=pass"
        )
    if target_stage == "REVIEWED" and item.review_status != "pass":
        return TransitionDecision(False, "REVIEWED requires review_status=pass")
    if (
        target_stage == "RELEASED"
        and item.release_note_required
        and not item.changelog_entry
    ):
        return TransitionDecision(
            False, "RELEASED requires changelog_entry when release_note_required"
        )
    return TransitionDecision(True, "ok")


def _existing_ref(ref: str, name: str) -> str:
    if not ref:
        return f"{name} is required"
    if not (ROOT / ref).exists():
        return f"{name} does not exist: {ref}"
    return ""


def next_item(items: list[WorkItem]) -> WorkItem | None:
    for item in items:
        if item.stage not in TERMINAL_STAGES:
            return item
    return None


def render_status(items: list[WorkItem]) -> str:
    counts = Counter(item.stage for item in items)
    lines = ["SDD work status", "===============", f"items: {len(items)}"]
    for stage in STAGES:
        if counts[stage]:
            lines.append(f"{stage}: {counts[stage]}")
    return "\n".join(lines)


def render_next(item: WorkItem | None) -> str:
    if item is None:
        return "No non-terminal work items."
    return f"{item.id}\t{item.stage}\t{item.title}"


def advance_item(
    item_id: str, target_stage: str, work_dir: Path = WORK_DIR
) -> TransitionDecision:
    path = item_path(item_id, work_dir)
    if not path.exists():
        return TransitionDecision(False, f"work item not found: {item_id}")
    item = WorkItem.from_dict(json.loads(path.read_text(encoding="utf-8")))
    decision = can_advance(item, target_stage)
    if not decision.allowed:
        return decision
    save_item(WorkItem.from_dict(asdict(item) | {"stage": target_stage}), work_dir)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage deterministic SDD work-item state."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("next")
    adv = sub.add_parser("advance")
    adv.add_argument("item_id")
    adv.add_argument("stage")
    args = parser.parse_args()

    if args.command == "status":
        print(render_status(load_items()))
        return 0
    if args.command == "next":
        print(render_next(next_item(load_items())))
        return 0
    if args.command == "advance":
        decision = advance_item(args.item_id, args.stage)
        print(decision.reason)
        return 0 if decision.allowed else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
