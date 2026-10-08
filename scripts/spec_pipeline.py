#!/usr/bin/env python3
"""Spec pipeline management script — deterministic stage tracking and advancement.

Reads the canonical spec index (specs/index.json) and plan index (plans/index.json),
cross-references them against pipeline stage definitions, and provides
machine-readable status, readiness checks, and stage advancement.

Usage:
    python scripts/spec_pipeline.py status              # All specs grouped by stage
    python scripts/spec_pipeline.py status S68          # Single spec detail
    python scripts/spec_pipeline.py status --json       # Machine-readable output
    python scripts/spec_pipeline.py check S68           # Check if S68 can advance
    python scripts/spec_pipeline.py advance S68 REVIEW  # Advance to REVIEW (validates first)
    python scripts/spec_pipeline.py validate            # Pipeline consistency check

Exit codes:
    0 — success / ready to advance
    1 — not ready to advance (criteria not met)
    2 — error (missing files, corrupt data, invalid arguments)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ── Stage definitions ──────────────────────────────────────────

STAGE_ORDER: list[str] = [
    "STUB",
    "DRAFT",
    "REVIEW",
    "APPROVED",
    "PLANNED",
    "IMPLEMENTING",
    "DONE",
    "ARCHIVED",
]

STAGE_EMOJI: dict[str, str] = {
    "STUB": "📌",
    "DRAFT": "📝",
    "REVIEW": "🔍",
    "APPROVED": "✅",
    "PLANNED": "📋",
    "IMPLEMENTING": "🔨",
    "DONE": "🏁",
    "ARCHIVED": "📦",
}


@dataclass
class StageCriteria:
    """Deterministic checks for each stage transition."""

    stage: str
    checks: list[str]  # human-readable descriptions
    auto_advance: bool  # can an agent advance this without human approval?


STAGE_CRITERIA: dict[str, StageCriteria] = {
    "DRAFT": StageCriteria(
        stage="DRAFT",
        checks=[
            "Has ≥3 acceptance criteria",
            "Has user stories (As a / I want / so that)",
            "Has edge cases section",
            "Has out-of-scope section",
            "No index_specs.py warnings (or only pre-existing 'Stub' warnings)",
            "Word count ≥ 500",
        ],
        auto_advance=True,
    ),
    "REVIEW": StageCriteria(
        stage="REVIEW",
        checks=[
            "Passes index_specs.py --validate with ZERO warnings",
            "Has Gherkin Given/When/Then scenarios",
            "All dependencies reference existing specs",
            "Word count ≥ 800",
        ],
        auto_advance=True,
    ),
    "APPROVED": StageCriteria(
        stage="APPROVED",
        checks=[
            "Has passed independent review (documented in spec or review artifact)",
            "Vision Manager (paid model) confirms strategic alignment",
            "No unresolved open questions tagged 'Impact: high'",
        ],
        auto_advance=False,  # requires human or paid-model approval
    ),
    "PLANNED": StageCriteria(
        stage="PLANNED",
        checks=[
            "Implementation plan exists in plans/index.json referencing this spec",
            "Plan passes plans/index_plans.py --validate",
            "Plan has testing section",
            "Plan has code examples",
        ],
        auto_advance=True,
    ),
    "IMPLEMENTING": StageCriteria(
        stage="IMPLEMENTING",
        checks=[
            "At least one @pytest.mark.spec('AC-XX.YY') test exists for this spec",
            "At least one AC has a passing test",
        ],
        auto_advance=True,
    ),
    "DONE": StageCriteria(
        stage="DONE",
        checks=[
            "All ACs have passing @pytest.mark.spec tests",
            "make trace exit 0",
            "make gate green (ruff + pyright + trace + validate + test-unit)",
            "Code reviewed and PR merged",
        ],
        auto_advance=False,  # requires PR merge
    ),
    "ARCHIVED": StageCriteria(
        stage="ARCHIVED",
        checks=[
            "All ACs covered and verified",
            "Spec superseded by newer spec or release is complete",
        ],
        auto_advance=False,  # one-way, manual gate
    ),
}


# ── Pipeline state model ───────────────────────────────────────


@dataclass
class SpecPipelineState:
    """Pipeline state for a single spec."""

    spec_id: str  # e.g. "S68"
    title: str
    current_stage: str  # e.g. "DRAFT"
    file: str  # relative path from specs/
    word_count: int
    ac_count: int
    has_stories: bool
    has_edge_cases: bool
    has_out_of_scope: bool
    has_gherkin: bool
    warnings: list[str] = field(default_factory=list)
    has_plan: bool = False
    plan_file: str = ""
    ac_coverage_pct: float = 0.0  # 0-100, from trace_acs
    next_stage: str = ""
    ready_to_advance: bool = False
    blocking_criteria: list[str] = field(default_factory=list)


# ── Data loading ────────────────────────────────────────────────


def _repo_root() -> Path:
    """Find repo root from this script's location."""
    return Path(__file__).resolve().parent.parent


def load_spec_index() -> dict:
    """Load specs/index.json."""
    index_path = _repo_root() / "specs" / "index.json"
    if not index_path.exists():
        print(f"Error: {index_path} not found. Run 'make index' first.", file=sys.stderr)
        sys.exit(2)
    return json.loads(index_path.read_text())


def load_plan_index() -> dict:
    """Load plans/index.json (returns empty dict if missing)."""
    index_path = _repo_root() / "plans" / "index.json"
    if not index_path.exists():
        return {"plans": []}
    return json.loads(index_path.read_text())


def load_trace_data() -> dict[str, float]:
    """Run make trace and parse AC coverage percentages per spec.

    Returns dict of spec_id -> coverage_pct (0-100).
    """
    try:
        result = subprocess.run(
            ["make", "trace"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Parse trace_acs.py output for per-spec coverage
        # Format varies; attempt robust extraction
        coverage: dict[str, float] = {}
        for line in result.stdout.splitlines() + result.stderr.splitlines():
            # Look for patterns like "S68: 3/7 ACs covered (42.9%)"
            m = re.search(r"(S\d+):\s*(\d+)/(\d+)\s*ACs?\s*covered\s*\((\d+\.?\d*)%\)", line)
            if m:
                coverage[m.group(1)] = float(m.group(4))
        return coverage
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}


def find_spec_ac_markers(spec_id: str) -> int:
    """Count @pytest.mark.spec markers that match this spec's AC pattern.

    Returns count of marker references found in test files.
    """
    try:
        # AC markers for a spec look like "AC-68.01", "AC-68.02", etc.
        # Spec IDs are like "S68" → AC pattern is "AC-68."
        ac_prefix = f"AC-{spec_id[1:]}."  # "S68" → "AC-68."
        result = subprocess.run(
            ["grep", "-rl", f"@pytest.mark.spec", str(_repo_root() / "tests")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        test_files = result.stdout.strip().splitlines()
        if not test_files or test_files == [""]:
            return 0

        # Now grep those files for the AC prefix
        count = 0
        for tf in test_files:
            r = subprocess.run(
                ["grep", "-c", ac_prefix, tf],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                try:
                    count += int(r.stdout.strip())
                except ValueError:
                    pass
        return count
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0


# ── Stage inference ─────────────────────────────────────────────


def infer_stage(spec: dict, plan_index: dict, trace_coverage: dict[str, float]) -> str:
    """Infer a spec's pipeline stage from available data.

    Priority order:
    1. If spec is in future/ dir or marked Stub → STUB
    2. Boundary stubs: has Gherkin/ACs but no user stories AND no edge cases → STUB
    3. If status contains 'Approved' → check for plan/code coverage to refine
    4. If status contains 'Draft' → DRAFT (if clean) or STUB (if boundary)
    5. Otherwise → STUB
    """
    status = spec.get("status", "")
    file_path = spec.get("file", "")
    spec_id = spec.get("number", "")
    has_stories = spec.get("has_user_stories", False)
    has_edge_cases = spec.get("has_edge_cases", False)
    has_ac = spec.get("has_acceptance_criteria", False)
    warnings = spec.get("warnings", [])

    # Explicit stubs
    if "Stub" in status or "future/" in file_path:
        return "STUB"

    # Approved specs always stay at minimum APPROVED, never demoted to STUB
    if "Approved" in status:
        coverage = trace_coverage.get(spec_id, 0.0)
        if coverage >= 100.0:
            return "DONE"
        if coverage > 0:
            return "IMPLEMENTING"
        if _spec_has_plan(spec_id, plan_index):
            return "PLANNED"
        return "APPROVED"

    # Boundary stubs: Draft specs that have ACs but no user stories AND no edge cases
    # S50-S63 pattern: Gherkin scenarios exist, but no user stories, no edge cases
    if has_ac and not has_stories and not has_edge_cases:
        return "STUB"

    # Draft specs
    if "Draft" in status:
        has_plan = _spec_has_plan(spec_id, plan_index)
        if has_plan:
            return "PLANNED"
        return "DRAFT"

    return "STUB"


def _spec_has_plan(spec_id: str, plan_index: dict) -> bool:
    """Check if any plan references this spec.

    Handles range notation like "S01-S17" without false-positive substring matches.
    """
    spec_num = spec_id[1:]  # "S68" → "68"
    for plan in plan_index.get("plans", []):
        for ref in plan.get("spec_refs", []):
            # Exact match
            if ref == spec_id:
                return True
            # Range match: "S01-S17" or "S01-S17 (all v1 specs)"
            range_m = re.match(r"S(\d+)-S(\d+)", ref)
            if range_m:
                try:
                    lo, hi = int(range_m.group(1)), int(range_m.group(2))
                    sn = int(spec_num)
                    if lo <= sn <= hi:
                        return True
                except ValueError:
                    pass
    return False


def _find_plan_for_spec(spec_id: str, plan_index: dict) -> str:
    """Return the plan file that covers this spec, or empty string."""
    for plan in plan_index.get("plans", []):
        for ref in plan.get("spec_refs", []):
            if spec_id in ref:
                return plan.get("file", "")
    return ""


# ── Advancement checks ──────────────────────────────────────────


def check_advancement(
    spec: dict,
    current_stage: str,
    plan_index: dict,
    trace_coverage: dict[str, float],
) -> tuple[bool, list[str], str]:
    """Check if a spec can advance to the next stage.

    Returns (ready, blocking_reasons, next_stage).
    """
    spec_id = spec.get("number", "")
    if not spec_id:
        return False, ["No spec number"], ""

    # Find next stage
    try:
        current_idx = STAGE_ORDER.index(current_stage)
        next_idx = current_idx + 1
        if next_idx >= len(STAGE_ORDER):
            return False, ["Already at final stage (ARCHIVED)"], ""
        next_stage = STAGE_ORDER[next_idx]
    except ValueError:
        return False, [f"Unknown stage: {current_stage}"], ""

    criteria = STAGE_CRITERIA.get(next_stage)
    if not criteria:
        return False, [f"No criteria defined for stage: {next_stage}"], ""

    blockers: list[str] = []

    # ── DRAFT checks ──
    if next_stage == "DRAFT":
        if spec.get("acceptance_criteria_count", 0) < 3:
            blockers.append("Fewer than 3 acceptance criteria")
        if not spec.get("has_user_stories", False):
            blockers.append("No user stories found")
        if not spec.get("has_edge_cases", False):
            blockers.append("No edge cases section")
        if not spec.get("has_out_of_scope", False):
            blockers.append("No out-of-scope section")
        if spec.get("word_count", 0) < 500:
            blockers.append(f"Too short ({spec.get('word_count', 0)} words, need ≥500)")

    # ── REVIEW checks ──
    elif next_stage == "REVIEW":
        if spec.get("warnings", []):
            blockers.append(f"Has {len(spec['warnings'])} warnings: {', '.join(spec['warnings'])}")
        if not spec.get("has_gherkin_scenarios", False):
            blockers.append("No Gherkin Given/When/Then scenarios")
        if spec.get("word_count", 0) < 800:
            blockers.append(f"Too short ({spec.get('word_count', 0)} words, need ≥800)")

    # ── APPROVED checks ── (paid-model gate)
    elif next_stage == "APPROVED":
        if not criteria.auto_advance:
            blockers.append("APPROVED stage requires human or paid-model approval")
        # Still check basic quality
        if spec.get("warnings", []):
            blockers.append(f"Has {len(spec['warnings'])} warnings")

    # ── PLANNED checks ──
    elif next_stage == "PLANNED":
        if not _spec_has_plan(spec_id, plan_index):
            blockers.append("No implementation plan references this spec")
        else:
            plan_file = _find_plan_for_spec(spec_id, plan_index)
            if plan_file:
                # Check plan quality
                plan_data = _find_plan_data(plan_file, plan_index)
                if plan_data:
                    if not plan_data.get("has_testing", False):
                        blockers.append("Plan has no testing section")
                    if not plan_data.get("has_code_blocks", False):
                        blockers.append("Plan has no code examples")

    # ── IMPLEMENTING checks ──
    elif next_stage == "IMPLEMENTING":
        coverage = trace_coverage.get(spec_id, 0.0)
        if coverage <= 0:
            # Check for @pytest.mark.spec markers as fallback
            marker_count = find_spec_ac_markers(spec_id)
            if marker_count == 0:
                blockers.append("No @pytest.mark.spec tests found for this spec")

    # ── DONE checks ──
    elif next_stage == "DONE":
        coverage = trace_coverage.get(spec_id, 0.0)
        if coverage < 100.0:
            blockers.append(f"AC coverage at {coverage:.1f}% (need 100%)")
        if not criteria.auto_advance:
            blockers.append("DONE stage requires code review + PR merge confirmation")

    # ── ARCHIVED checks ──
    elif next_stage == "ARCHIVED":
        if not criteria.auto_advance:
            blockers.append("ARCHIVED is a manual one-way gate")

    ready = len(blockers) == 0
    return ready, blockers, next_stage


def _find_plan_data(plan_file: str, plan_index: dict) -> dict | None:
    """Find plan metadata by filename."""
    for plan in plan_index.get("plans", []):
        if plan.get("file") == plan_file:
            return plan
    return None


# ── Output formatting ───────────────────────────────────────────


def format_pipeline_state(
    specs: list[dict],
    plan_index: dict,
    trace_coverage: dict[str, float],
    json_output: bool = False,
    single_spec: str | None = None,
) -> str:
    """Build pipeline state report."""
    states: list[SpecPipelineState] = []

    for spec in specs:
        spec_id = spec.get("number", "")
        if not spec_id:
            continue  # skip templates

        current_stage = infer_stage(spec, plan_index, trace_coverage)
        ready, blockers, next_stage = check_advancement(
            spec, current_stage, plan_index, trace_coverage
        )

        states.append(
            SpecPipelineState(
                spec_id=spec_id,
                title=spec.get("title", ""),
                current_stage=current_stage,
                file=spec.get("file", ""),
                word_count=spec.get("word_count", 0),
                ac_count=spec.get("acceptance_criteria_count", 0),
                has_stories=spec.get("has_user_stories", False),
                has_edge_cases=spec.get("has_edge_cases", False),
                has_out_of_scope=spec.get("has_out_of_scope", False),
                has_gherkin=spec.get("has_gherkin_scenarios", False),
                warnings=spec.get("warnings", []),
                has_plan=_spec_has_plan(spec_id, plan_index),
                plan_file=_find_plan_for_spec(spec_id, plan_index),
                ac_coverage_pct=trace_coverage.get(spec_id, 0.0),
                next_stage=next_stage,
                ready_to_advance=ready,
                blocking_criteria=blockers,
            )
        )

    if single_spec:
        states = [s for s in states if s.spec_id == single_spec]
        if not states:
            return f"Error: spec {single_spec} not found in index"
        if json_output:
            import dataclasses

            return json.dumps(dataclasses.asdict(states[0]), indent=2, default=str)
        return _format_single_spec(states[0])

    if json_output:
        import dataclasses

        return json.dumps(
            [dataclasses.asdict(s) for s in states], indent=2, default=str
        )

    return _format_stage_table(states)


def _format_single_spec(s: SpecPipelineState) -> str:
    """Format detailed view for a single spec."""
    lines = [
        f"{'='*60}",
        f"  {s.spec_id}: {s.title}",
        f"  File: specs/{s.file}",
        f"  Stage: {STAGE_EMOJI.get(s.current_stage, '•')} {s.current_stage}",
        f"  Words: {s.word_count}  |  ACs: {s.ac_count}  |  Coverage: {s.ac_coverage_pct:.0f}%",
        f"{'='*60}",
        "",
        "  Quality:",
        f"    User stories:  {'✓' if s.has_stories else '✗'}",
        f"    Edge cases:    {'✓' if s.has_edge_cases else '✗'}",
        f"    Out of scope:  {'✓' if s.has_out_of_scope else '✗'}",
        f"    Gherkin:       {'✓' if s.has_gherkin else '✗'}",
        f"    Warnings:      {len(s.warnings)}",
    ]

    if s.warnings:
        for w in s.warnings:
            lines.append(f"      ⚠  {w}")

    lines.append("")
    lines.append(f"  Has plan: {'✓ (' + s.plan_file + ')' if s.has_plan else '✗'}")

    if s.next_stage:
        lines.append(f"  Next stage: {STAGE_EMOJI.get(s.next_stage, '→')} {s.next_stage}")
        if s.ready_to_advance:
            lines.append(f"  Status: READY to advance")
        else:
            lines.append(f"  Status: NOT READY — {len(s.blocking_criteria)} blocker(s)")
            for b in s.blocking_criteria:
                lines.append(f"    ✗ {b}")
    else:
        lines.append("  Next stage: (none — at final stage)")

    return "\n".join(lines)


def _format_stage_table(states: list[SpecPipelineState]) -> str:
    """Format grouped-by-stage table."""
    # Group by stage
    by_stage: dict[str, list[SpecPipelineState]] = {}
    for stage in STAGE_ORDER:
        by_stage[stage] = []

    for s in states:
        stage = s.current_stage
        if stage not in by_stage:
            stage = "STUB"
        by_stage[stage].append(s)

    lines = [
        "TTA Spec Pipeline",
        "=================",
        "",
    ]

    total = len(states)
    for stage in STAGE_ORDER:
        group = by_stage[stage]
        if not group:
            continue
        emoji = STAGE_EMOJI.get(stage, "•")
        ready_count = sum(1 for s in group if s.ready_to_advance)
        lines.append(f"### {emoji} {stage} ({len(group)} specs, {ready_count} ready)")
        lines.append("")

        for s in group:
            plan_tag = " 📋" if s.has_plan else ""
            cov_tag = f" [{s.ac_coverage_pct:.0f}%]" if s.ac_coverage_pct > 0 else ""
            warn_tag = f" ⚠{len(s.warnings)}" if s.warnings else ""
            ready_tag = " →READY" if s.ready_to_advance else ""
            lines.append(
                f"  {s.spec_id:5s} {s.title[:50]:50s} AC:{s.ac_count:<3d}{plan_tag}{cov_tag}{warn_tag}{ready_tag}"
            )
        lines.append("")

    # Summary
    lines.append("---")
    lines.append(f"Total: {total} specs")
    for stage in STAGE_ORDER:
        count = len(by_stage[stage])
        if count > 0:
            lines.append(f"  {STAGE_EMOJI.get(stage, '•')} {stage}: {count}")

    return "\n".join(lines)


# ── Stage advancement ───────────────────────────────────────────


def advance_spec(
    spec_id: str,
    target_stage: str,
    plan_index: dict,
    trace_coverage: dict[str, float],
    dry_run: bool = False,
) -> str:
    """Advance a spec to the target stage. Validates criteria first.

    Returns status message.
    """
    spec_index = load_spec_index()
    spec = None
    for s in spec_index.get("specs", []):
        if s.get("number") == spec_id:
            spec = s
            break

    if not spec:
        return f"Error: spec {spec_id} not found"

    current_stage = infer_stage(spec, plan_index, trace_coverage)

    # Validate target stage is next
    try:
        current_idx = STAGE_ORDER.index(current_stage)
        target_idx = STAGE_ORDER.index(target_stage)
    except ValueError:
        return f"Error: invalid stage '{target_stage}'. Valid: {', '.join(STAGE_ORDER)}"

    if target_idx <= current_idx:
        return f"Error: {spec_id} is at {current_stage}, cannot move backward to {target_stage}"

    if target_idx > current_idx + 1:
        return (
            f"Error: cannot skip stages. {spec_id} is at {current_stage}, "
            f"next is {STAGE_ORDER[current_idx + 1]}, not {target_stage}"
        )

    # Check criteria
    ready, blockers, _ = check_advancement(spec, current_stage, plan_index, trace_coverage)
    if not ready:
        return f"Cannot advance {spec_id} to {target_stage}:\n" + "\n".join(
            f"  ✗ {b}" for b in blockers
        )

    # Check if auto-advance is allowed
    criteria = STAGE_CRITERIA.get(target_stage)
    if criteria and not criteria.auto_advance:
        return (
            f"Stage {target_stage} requires human approval.\n"
            f"Criteria:\n" + "\n".join(f"  • {c}" for c in criteria.checks)
        )

    if dry_run:
        return f"[DRY RUN] Would advance {spec_id} from {current_stage} → {target_stage}"

    # ── Perform advancement ──
    spec_file = _repo_root() / "specs" / spec["file"]
    if not spec_file.exists():
        return f"Error: spec file not found: {spec_file}"

    content = spec_file.read_text()

    # Update status in the frontmatter
    if target_stage == "DRAFT":
        new_status = "📝 Draft"
    elif target_stage == "REVIEW":
        new_status = "🔍 In Review"
    elif target_stage == "APPROVED":
        new_status = "✅ Approved"
    elif target_stage == "PLANNED":
        new_status = "📋 Planned"
    elif target_stage == "IMPLEMENTING":
        new_status = "🔨 Implementing"
    elif target_stage == "DONE":
        new_status = "🏁 Done"
    elif target_stage == "ARCHIVED":
        new_status = "📦 Archived"
    else:
        return f"Error: unknown stage {target_stage}"

    # Replace status line
    old_status = spec.get("status", "")
    if old_status:
        content = content.replace(f"> **Status**: {old_status}", f"> **Status**: {new_status}")

    spec_file.write_text(content)

    # Regenerate index
    try:
        subprocess.run(
            ["uv", "run", "python", "specs/index_specs.py", "--out", "specs/index"],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return f"Advanced status but index regeneration failed: {e}"

    return f"Advanced {spec_id} from {current_stage} → {target_stage}\nUpdated: specs/{spec['file']}\nIndex regenerated."


# ── Validation ──────────────────────────────────────────────────


def validate_pipeline(
    specs: list[dict], plan_index: dict, trace_coverage: dict[str, float]
) -> str:
    """Check pipeline consistency — find specs in impossible states."""
    issues: list[str] = []

    for spec in specs:
        spec_id = spec.get("number", "")
        if not spec_id:
            continue

        stage = infer_stage(spec, plan_index, trace_coverage)
        status = spec.get("status", "")
        file_path = spec.get("file", "")

        # Check: Approved but no user stories? (S00 is intentional)
        if "Approved" in status and spec_id != "S00":
            if not spec.get("has_user_stories", False):
                issues.append(f"{spec_id}: Approved but no user stories")
            if not spec.get("has_edge_cases", False):
                issues.append(f"{spec_id}: Approved but no edge cases")

        # Check: Has plan but not at PLANNED+
        has_plan = _spec_has_plan(spec_id, plan_index)
        if has_plan and stage not in ("PLANNED", "IMPLEMENTING", "DONE", "ARCHIVED"):
            plan_file = _find_plan_for_spec(spec_id, plan_index)
            if spec.get("has_acceptance_criteria", False):
                # Has ACs + has plan + is Draft → should be at least PLANNED
                issues.append(
                    f"{spec_id}: Has plan ({plan_file}) but stage is {stage} — "
                    f"should be PLANNED or later"
                )

        # Check: Has coverage but not IMPLEMENTING+
        coverage = trace_coverage.get(spec_id, 0.0)
        if coverage > 0 and stage not in ("IMPLEMENTING", "DONE"):
            issues.append(
                f"{spec_id}: Has {coverage:.0f}% AC coverage but stage is {stage} — "
                f"should be IMPLEMENTING or DONE"
            )

    if not issues:
        return "Pipeline is consistent. No issues found."

    return "Pipeline consistency issues:\n" + "\n".join(f"  ⚠ {i}" for i in issues)


# ── CLI ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TTA Spec Pipeline Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/spec_pipeline.py status              # Full pipeline overview
  python scripts/spec_pipeline.py status S68          # Single spec detail
  python scripts/spec_pipeline.py status --json       # Machine-readable output
  python scripts/spec_pipeline.py check S68           # Check if S68 can advance
  python scripts/spec_pipeline.py advance S68 REVIEW  # Advance S68 to REVIEW
  python scripts/spec_pipeline.py advance --dry-run S68 REVIEW
  python scripts/spec_pipeline.py validate            # Pipeline consistency check
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # ── status ──
    status_p = sub.add_parser("status", help="Show pipeline state")
    status_p.add_argument("spec", nargs="?", help="Spec ID to show detail for (e.g. S68)")
    status_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # ── check ──
    check_p = sub.add_parser("check", help="Check if a spec can advance")
    check_p.add_argument("spec", help="Spec ID to check (e.g. S68)")
    check_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    # ── advance ──
    advance_p = sub.add_parser("advance", help="Advance a spec to next stage")
    advance_p.add_argument("spec", help="Spec ID to advance (e.g. S68)")
    advance_p.add_argument("stage", help="Target stage (e.g. REVIEW, APPROVED, PLANNED)")
    advance_p.add_argument(
        "--dry-run", action="store_true", help="Check criteria without modifying files"
    )
    advance_p.add_argument(
        "--force", action="store_true", help="Skip criteria check (dangerous)"
    )

    # ── validate ──
    sub.add_parser("validate", help="Check pipeline consistency across all specs")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Load data
    spec_index = load_spec_index()
    plan_index = load_plan_index()
    trace_coverage = load_trace_data()

    specs: list[dict] = spec_index.get("specs", [])

    if args.command == "status":
        output = format_pipeline_state(
            specs, plan_index, trace_coverage,
            json_output=args.json,
            single_spec=args.spec,
        )
        print(output)

    elif args.command == "check":
        spec_id = args.spec
        spec = None
        for s in specs:
            if s.get("number") == spec_id:
                spec = s
                break
        if not spec:
            print(f"Error: spec {spec_id} not found", file=sys.stderr)
            sys.exit(2)

        current_stage = infer_stage(spec, plan_index, trace_coverage)
        ready, blockers, next_stage = check_advancement(
            spec, current_stage, plan_index, trace_coverage
        )

        if args.json:
            result = {
                "spec_id": spec_id,
                "current_stage": current_stage,
                "next_stage": next_stage,
                "ready": ready,
                "blockers": blockers,
                "auto_advance": STAGE_CRITERIA.get(next_stage, StageCriteria("", [], False)).auto_advance,
            }
            print(json.dumps(result, indent=2))
        else:
            print(_format_single_spec(
                SpecPipelineState(
                    spec_id=spec_id,
                    title=spec.get("title", ""),
                    current_stage=current_stage,
                    file=spec.get("file", ""),
                    word_count=spec.get("word_count", 0),
                    ac_count=spec.get("acceptance_criteria_count", 0),
                    has_stories=spec.get("has_user_stories", False),
                    has_edge_cases=spec.get("has_edge_cases", False),
                    has_out_of_scope=spec.get("has_out_of_scope", False),
                    has_gherkin=spec.get("has_gherkin_scenarios", False),
                    warnings=spec.get("warnings", []),
                    has_plan=_spec_has_plan(spec_id, plan_index),
                    plan_file=_find_plan_for_spec(spec_id, plan_index),
                    ac_coverage_pct=trace_coverage.get(spec_id, 0.0),
                    next_stage=next_stage,
                    ready_to_advance=ready,
                    blocking_criteria=blockers,
                )
            ))

        if not ready:
            sys.exit(1)

    elif args.command == "advance":
        result = advance_spec(
            args.spec,
            args.stage,
            plan_index,
            trace_coverage,
            dry_run=args.dry_run,
        )
        print(result)
        if "Error" in result or "Cannot advance" in result:
            sys.exit(1)

    elif args.command == "validate":
        result = validate_pipeline(specs, plan_index, trace_coverage)
        print(result)
        if "issues" in result:
            sys.exit(1)


if __name__ == "__main__":
    main()
