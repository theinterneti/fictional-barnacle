#!/usr/bin/env python3
"""AC Traceability Scanner — links @pytest.mark.spec ACs to specs/index.json.

Usage:
    uv run python specs/trace_acs.py --validate
    uv run python specs/trace_acs.py --json
    uv run python specs/trace_acs.py --html
    uv run python specs/trace_acs.py --validate --json --html
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
SPECS_DIR = REPO_ROOT / "specs"
TESTS_DIR = REPO_ROOT / "tests"
INDEX_PATH = SPECS_DIR / "index.json"
TRACE_JSON = SPECS_DIR / "trace.json"
TRACE_HTML = SPECS_DIR / "trace.html"

# ---------------------------------------------------------------------------
# AC ID normalization
# ---------------------------------------------------------------------------
_RAW_PATTERN = re.compile(r"AC-(\d+)\.(\d+)")


def normalize_ac_id(raw: str) -> str:
    """Normalize any AC-N.M variant to canonical AC-NN.MM (zero-padded)."""
    m = _RAW_PATTERN.fullmatch(raw.strip())
    if m:
        return f"AC-{int(m.group(1)):02d}.{int(m.group(2)):02d}"
    return raw  # return as-is; orphan detection will flag it


_CANONICAL = re.compile(r"^AC-\d{2}\.\d{2}$")


def is_canonical(ac_id: str) -> bool:
    return bool(_CANONICAL.match(ac_id))


# ---------------------------------------------------------------------------
# Load authoritative AC corpus — parse AC IDs from spec markdown files
# ---------------------------------------------------------------------------

# Matches AC ID definitions in:
#   - **AC-10.01**: description
#   - [x] **AC-10.01**: description   (checkbox style)
#   ### AC-07.1  (group heading)
#   Scenario: AC-10.01   (Gherkin)
_AC_DEF_RE = re.compile(
    r"^\s*-\s*\[[x ]\]\s*\*?\*?AC-(\d+)\.(\d+)"  # - [ ] **AC-N.M
    r"|^\s*-\s+\*?\*?AC-(\d+)\.(\d+)\*?\*?:"  # - **AC-N.M**:
    r"|^###\s+AC-(\d+)\.(\d+)\b"  # ### AC-N.M
    r"|\bScenario:\s+AC-(\d+)\.(\d+)",  # Scenario: AC-N.M
    re.MULTILINE | re.IGNORECASE,
)


def _extract_ac_ids_from_text(text: str) -> list[str]:
    """Extract unique canonical AC IDs defined in a spec file."""
    seen: dict[str, None] = {}
    for m in _AC_DEF_RE.finditer(text):
        groups = m.groups()
        # Find the first non-None pair
        for i in range(0, len(groups), 2):
            if groups[i] is not None:
                ac_id = f"AC-{int(groups[i]):02d}.{int(groups[i + 1]):02d}"
                seen.setdefault(ac_id, None)
                break
    return list(seen)


def _classify_status(raw: str) -> str:
    """Map a spec's Status frontmatter value to one of: approved | draft | stub.

    Anything containing 'stub' → stub (excluded entirely from the audit).
    Anything containing 'approved' or 'revised' → approved (counted in headline
    coverage).  'Revised' means updated after implementation feedback and is still
    a committed source of truth.
    Anything else (Draft / Review / Unknown) → draft (informational).
    """
    s = raw.lower()
    if "stub" in s:
        return "stub"
    if "approved" in s or "revised" in s:
        return "approved"
    return "draft"


def load_known_acs(index_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (ac_map, ac_status) where:

    - ac_map: {AC-ID: spec_title}
    - ac_status: {AC-ID: 'approved' | 'draft' | 'stub'}

    AC IDs are extracted directly from spec *.md files because specs/index.json
    stores only counts, not individual AC identifiers.
    """
    specs_dir = index_path.parent

    with index_path.open() as f:
        index = json.load(f)

    ac_map: dict[str, str] = {}
    ac_status: dict[str, str] = {}

    for spec in index.get("specs", []):
        if not spec.get("number"):
            continue  # skip template/non-spec files
        title = spec.get("title", "Unknown")
        status = _classify_status(spec.get("status", ""))
        spec_file = specs_dir / spec["file"]
        if not spec_file.exists():
            continue
        text = spec_file.read_text(encoding="utf-8", errors="replace")
        for ac_id in _extract_ac_ids_from_text(text):
            ac_map[ac_id] = title
            ac_status[ac_id] = status

    return ac_map, ac_status


# ---------------------------------------------------------------------------
# Scan tests/ for @pytest.mark.spec(...) markers
# ---------------------------------------------------------------------------
def scan_markers(tests_dir: Path) -> dict[str, list[str]]:
    """Return {normalized_AC_ID: [node_id, ...]} for all @pytest.mark.spec markers.

    Handles two forms:
    - @pytest.mark.spec(...) on a function/method → counted directly
    - @pytest.mark.spec(...) on a class → counted once per test method in the class
      (mirrors pytest's own marker inheritance behaviour)
    """
    matrix: dict[str, list[str]] = {}

    for py_file in sorted(tests_dir.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        rel = py_file.relative_to(REPO_ROOT)

        # Build a map of class → inherited AC IDs from class-level @pytest.mark.spec
        # Also handles the `pytestmark = [pytest.mark.spec(...)]` assignment pattern
        # that pytest itself supports for class-level marker inheritance.
        class_ac_ids: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Form 1: @pytest.mark.spec(...) decorator on the class
            for decorator in node.decorator_list:
                ids = _extract_spec_ids(decorator)
                if ids:
                    existing = class_ac_ids.setdefault(node.name, [])
                    existing.extend(ids)
            # Form 2: pytestmark = [pytest.mark.spec(...)] assignment in class body
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                if not any(
                    isinstance(t, ast.Name) and t.id == "pytestmark"
                    for t in stmt.targets
                ):
                    continue
                # Value may be a single call or a list of calls
                candidates: list[ast.expr] = []
                if isinstance(stmt.value, ast.List):
                    candidates.extend(stmt.value.elts)
                else:
                    candidates.append(stmt.value)
                for candidate in candidates:
                    ids = _extract_spec_ids(candidate)
                    if ids:
                        existing = class_ac_ids.setdefault(node.name, [])
                        existing.extend(ids)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Collect AC IDs from direct markers on the function
            direct_ids: list[str] = []
            for decorator in node.decorator_list:
                ids = _extract_spec_ids(decorator)
                if ids:
                    direct_ids.extend(ids)

            # Collect inherited IDs from parent class(es)
            for _cls_name, _ids in class_ac_ids.items():
                # Check if this function is a direct method of the class by looking
                # at the parent node — ast.walk doesn't give parent context, so we
                # check whether the function name appears as a method of any marked
                # class body.  We re-walk class bodies to match correctly.
                pass  # handled separately below

            all_ids = direct_ids
            if all_ids:
                node_id = f"{rel}::{node.name}"
                for raw_id in all_ids:
                    norm = normalize_ac_id(raw_id)
                    matrix.setdefault(norm, []).append(node_id)

        # Walk class bodies to pick up inherited markers
        for class_node in ast.walk(tree):
            if not isinstance(class_node, ast.ClassDef):
                continue
            inherited = class_ac_ids.get(class_node.name)
            if not inherited:
                continue
            for item in class_node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not item.name.startswith("test_"):
                    continue
                node_id = f"{rel}::{class_node.name}::{item.name}"
                for raw_id in inherited:
                    norm = normalize_ac_id(raw_id)
                    matrix.setdefault(norm, []).append(node_id)

    return matrix


def _extract_spec_ids(decorator: ast.expr) -> list[str] | None:
    """Return a list of AC ID strings if decorator is @pytest.mark.spec(...)."""
    # Handle: @pytest.mark.spec("AC-10.01", ...)
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    # Accept pytest.mark.spec or just mark.spec or spec (all forms agents might write)
    if not _is_spec_marker(func):
        return None
    ids: list[str] = []
    for arg in decorator.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            ids.append(arg.value)
    return ids if ids else None


def _is_spec_marker(func: ast.expr) -> bool:
    """True if the expression resolves to pytest.mark.spec / mark.spec / spec."""
    if isinstance(func, ast.Attribute):
        # mark.spec
        if func.attr == "spec":
            return True
    if isinstance(func, ast.Name) and func.id == "spec":
        return True
    return False


# ---------------------------------------------------------------------------
# Build report
# ---------------------------------------------------------------------------
def _bucket_report(
    bucket_ids: set[str],
    matrix: dict[str, list[str]],
) -> dict:
    """Build per-bucket coverage stats + matrix slice for a set of AC IDs."""
    cited = set(matrix.keys()) & bucket_ids
    covered = cited
    total = len(bucket_ids)
    coverage_pct = round(len(covered) / total * 100, 1) if total else 0.0
    return {
        "total_acs": total,
        "covered_acs": len(covered),
        "uncovered_acs": total - len(covered),
        "coverage_pct": coverage_pct,
        "matrix": {ac_id: matrix.get(ac_id, []) for ac_id in sorted(bucket_ids)},
    }


def build_report(
    ac_map: dict[str, str],
    ac_status: dict[str, str],
    matrix: dict[str, list[str]],
) -> dict:
    """Build a status-aware coverage report.

    Approved ACs drive the headline coverage_pct. Draft ACs are tracked
    informationally — uncovered drafts do NOT fail the gate. Stub ACs are
    excluded entirely.

    Output schema (written to specs/trace.json)::

        {
          "generated": "<ISO-8601 timestamp>",
          "approved": {
            "total_acs": int,
            "covered_acs": int,
            "coverage_pct": float,
            "uncovered_acs": int,
            "matrix": {"AC-ID": ["test_file::test_name", ...], ...}
          },
          "draft": { <same shape as "approved"> },
          "stub_acs": int,
          "orphan_citations": int,
          "orphans": ["AC-ID", ...]
        }

    Note: prior to wave-40 the top-level keys were flat (``total_acs``,
    ``matrix``, ``coverage_pct``, etc.).  The nested approved/draft buckets
    replaced that schema.
    """
    all_ids = set(ac_map.keys())
    approved_ids = {a for a, s in ac_status.items() if s == "approved"}
    draft_ids = {a for a, s in ac_status.items() if s == "draft"}
    stub_ids = {a for a, s in ac_status.items() if s == "stub"}

    cited_ids = set(matrix.keys())
    orphans = cited_ids - all_ids

    return {
        "generated": datetime.now(UTC).isoformat(),
        "approved": _bucket_report(approved_ids, matrix),
        "draft": _bucket_report(draft_ids, matrix),
        "stub_acs": len(stub_ids),
        "orphan_citations": len(orphans),
        "orphans": sorted(orphans),
    }


# ---------------------------------------------------------------------------
# Output modes
# ---------------------------------------------------------------------------
def print_summary(report: dict, ac_map: dict[str, str]) -> None:
    approved = report["approved"]
    draft = report["draft"]
    orphans = report["orphans"]

    print(f"\nAC Traceability Report  {report['generated'][:10]}")
    print("=" * 60)
    print(
        f"  ✅ Approved (headline):  {approved['covered_acs']}/{approved['total_acs']}  "
        f"→ {approved['coverage_pct']}%"
    )
    print(
        f"  📝 Draft (info only):    {draft['covered_acs']}/{draft['total_acs']}  "
        f"→ {draft['coverage_pct']}%"
    )
    print(f"  📝 Stub (excluded):      {report['stub_acs']}")
    print(f"  Orphan citations:        {report['orphan_citations']}")

    if orphans:
        print(f"\n⚠  Orphan citations ({len(orphans)}) — cited but not in index.json:")
        for oid in orphans:
            print(f"     {oid}")

    uncovered_approved = [ac for ac, tests in approved["matrix"].items() if not tests]
    if uncovered_approved:
        print(
            f"\n○  Uncovered Approved ACs ({len(uncovered_approved)}) — "
            "no test marker citation:"
        )
        for ac_id in sorted(uncovered_approved)[:40]:
            spec_title = ac_map.get(ac_id, "")
            print(f"     {ac_id}  [{spec_title}]")
        if len(uncovered_approved) > 40:
            print(f"     ... and {len(uncovered_approved) - 40} more")
    else:
        print("\n✓  All Approved ACs have test coverage!")

    print()


def write_json(report: dict, out_path: Path) -> None:
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out_path}")


def _render_rows(bucket: dict, ac_map: dict[str, str], spec_status: str) -> str:
    rows: list[str] = []
    for ac_id in sorted(bucket["matrix"].keys()):
        tests = bucket["matrix"][ac_id]
        spec_title = ac_map.get(ac_id, "")
        covered = bool(tests)
        bg = "#d4edda" if covered else "#f8d7da"
        cov_label = "covered" if covered else "uncovered"
        test_list = "<br>".join(f"<code>{t}</code>" for t in tests) if tests else "—"
        rows.append(
            f'<tr style="background:{bg}" data-status="{spec_status}">'
            f"<td>{ac_id}</td>"
            f'<td title="{spec_title}">{spec_title[:60]}</td>'
            f"<td>{spec_status}</td>"
            f"<td>{cov_label}</td>"
            f"<td>{test_list}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def write_html(
    report: dict,
    ac_map: dict[str, str],
    out_path: Path,
) -> None:
    approved = report["approved"]
    draft = report["draft"]
    approved_rows = _render_rows(approved, ac_map, "Approved")
    draft_rows = _render_rows(draft, ac_map, "Draft")

    coverage = approved["coverage_pct"]
    bar_color = (
        "#28a745" if coverage >= 80 else "#ffc107" if coverage >= 40 else "#dc3545"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TTA AC Traceability Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 2rem; color: #212529; background: #f8f9fa; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; margin-bottom: 0.5rem; }}
  .meta {{ color: #6c757d; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .summary {{ display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }}
  .card {{ background: #fff; border: 1px solid #dee2e6; border-radius: 6px;
           padding: 0.75rem 1.25rem; min-width: 140px; }}
  .card .label {{ font-size: 0.75rem; color: #6c757d; }}
  .card .value {{ font-size: 1.5rem; font-weight: 700; }}
  .bar-wrap {{ background: #e9ecef; border-radius: 4px; height: 10px;
               margin-bottom: 1.5rem; width: 100%; max-width: 600px; }}
  .bar-fill {{ height: 10px; border-radius: 4px; background: {bar_color};
               width: {coverage}%; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
           border: 1px solid #dee2e6; border-radius: 6px; overflow: hidden;
           margin-bottom: 1.5rem; }}
  th {{ background: #343a40; color: #fff; padding: 0.5rem 0.75rem;
        text-align: left; font-size: 0.8rem; }}
  td {{ padding: 0.4rem 0.75rem; font-size: 0.8rem; vertical-align: top;
       border-top: 1px solid #dee2e6; }}
  input {{ padding: 0.4rem 0.6rem; border: 1px solid #dee2e6; border-radius: 4px;
           font-size: 0.85rem; margin-bottom: 0.75rem; width: 100%; max-width: 400px; }}
  .note {{ font-size: 0.85rem; color: #6c757d; margin-bottom: 0.5rem; }}
</style>
</head>
<body>
<h1>TTA AC Traceability Report</h1>
<div class="meta">Generated: {report["generated"]}</div>

<div class="summary">
  <div class="card"><div class="label">Approved ACs</div><div class="value">{approved["total_acs"]}</div></div>
  <div class="card"><div class="label">Approved Covered</div><div class="value" style="color:#28a745">{approved["covered_acs"]}</div></div>
  <div class="card"><div class="label">Approved Uncovered</div><div class="value" style="color:#dc3545">{approved["uncovered_acs"]}</div></div>
  <div class="card"><div class="label">Approved Coverage</div><div class="value">{coverage}%</div></div>
  <div class="card"><div class="label">Draft ACs</div><div class="value">{draft["total_acs"]}</div></div>
  <div class="card"><div class="label">Draft Coverage</div><div class="value">{draft["coverage_pct"]}%</div></div>
  <div class="card"><div class="label">Stub ACs</div><div class="value">{report["stub_acs"]}</div></div>
  <div class="card"><div class="label">Orphans</div><div class="value" style="color:#fd7e14">{report["orphan_citations"]}</div></div>
</div>

<div class="bar-wrap"><div class="bar-fill"></div></div>

<input type="text" id="filter" placeholder="Filter by AC ID or spec title..." oninput="filterTable(this.value)">

<h2>✅ Approved ACs (headline)</h2>
<div class="note">These specs are being built or shipped. Uncovered approved ACs are real coverage debt.</div>
<table id="tbl-approved">
<thead><tr><th>AC ID</th><th>Spec</th><th>Spec Status</th><th>Coverage</th><th>Test(s)</th></tr></thead>
<tbody>
{approved_rows}
</tbody>
</table>

<h2>📝 Draft ACs (informational)</h2>
<div class="note">Future specs (v3+) not yet approved for work. Uncovered here is expected and does not gate CI.</div>
<table id="tbl-draft">
<thead><tr><th>AC ID</th><th>Spec</th><th>Spec Status</th><th>Coverage</th><th>Test(s)</th></tr></thead>
<tbody>
{draft_rows}
</tbody>
</table>

<script>
function filterTable(q) {{
  q = q.toLowerCase();
  document.querySelectorAll('#tbl-approved tbody tr, #tbl-draft tbody tr').forEach(r => {{
    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="AC traceability scanner for TTA specs."
    )
    parser.add_argument(
        "--validate", action="store_true", help="Print text summary; exit 1 on orphans"
    )
    parser.add_argument("--json", action="store_true", help="Write specs/trace.json")
    parser.add_argument("--html", action="store_true", help="Write specs/trace.html")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        metavar="N",
        help="Exit 1 if uncovered AC%% exceeds N",
    )
    parser.add_argument("--tests-dir", type=Path, default=TESTS_DIR)
    parser.add_argument("--specs-index", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    if not args.specs_index.exists():
        print(
            f"ERROR: {args.specs_index} not found. Run `make regen-indexes` first.",
            file=sys.stderr,
        )
        return 1

    ac_map, ac_status = load_known_acs(args.specs_index)
    matrix = scan_markers(args.tests_dir)
    report = build_report(ac_map, ac_status, matrix)

    if args.validate:
        print_summary(report, ac_map)

    if args.json:
        write_json(report, TRACE_JSON)

    if args.html:
        write_html(report, ac_map, TRACE_HTML)

    if not (args.validate or args.json or args.html):
        print_summary(report, ac_map)

    # Exit codes — gate on Approved coverage only
    if report["orphan_citations"] > 0:
        return 1
    if args.threshold is not None:
        uncovered_pct = 100.0 - report["approved"]["coverage_pct"]
        if uncovered_pct > args.threshold:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
