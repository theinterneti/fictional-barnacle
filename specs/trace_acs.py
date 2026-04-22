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
    r"^\s*-\s*\[[x ]\]\s*\*?\*?AC-(\d+)\.(\d+)"   # - [ ] **AC-N.M
    r"|^\s*-\s+\*?\*?AC-(\d+)\.(\d+)\*?\*?:"       # - **AC-N.M**:
    r"|^###\s+AC-(\d+)\.(\d+)\b"                    # ### AC-N.M
    r"|\bScenario:\s+AC-(\d+)\.(\d+)",              # Scenario: AC-N.M
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


def load_known_acs(index_path: Path) -> tuple[dict[str, str], set[str]]:
    """Return (ac_map, stub_ac_ids) where ac_map is {AC-ID: spec_title} and
    stub_ac_ids is the set of ACs belonging to stub specs.

    AC IDs are extracted directly from spec *.md files because specs/index.json
    stores only counts, not individual AC identifiers.
    """
    specs_dir = index_path.parent

    with index_path.open() as f:
        index = json.load(f)

    ac_map: dict[str, str] = {}
    stub_ac_ids: set[str] = set()

    for spec in index.get("specs", []):
        if not spec.get("number"):
            continue  # skip template/non-spec files
        title = spec.get("title", "Unknown")
        is_stub = "stub" in spec.get("status", "").lower()
        spec_file = specs_dir / spec["file"]
        if not spec_file.exists():
            continue
        text = spec_file.read_text(encoding="utf-8", errors="replace")
        for ac_id in _extract_ac_ids_from_text(text):
            ac_map[ac_id] = title
            if is_stub:
                stub_ac_ids.add(ac_id)

    return ac_map, stub_ac_ids


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
        class_ac_ids: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for decorator in node.decorator_list:
                ids = _extract_spec_ids(decorator)
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
def build_report(
    ac_map: dict[str, str],
    stub_ac_ids: set[str],
    matrix: dict[str, list[str]],
) -> dict:
    all_ids = set(ac_map.keys())
    non_stub_ids = all_ids - stub_ac_ids
    cited_ids = set(matrix.keys())

    covered = cited_ids & non_stub_ids
    uncovered_ids = non_stub_ids - cited_ids
    orphans = cited_ids - all_ids

    total = len(non_stub_ids)
    coverage_pct = round(len(covered) / total * 100, 1) if total else 0.0

    # Full matrix: all non-stub ACs, whether covered or not
    full_matrix: dict[str, list[str]] = {
        ac_id: matrix.get(ac_id, []) for ac_id in sorted(non_stub_ids)
    }

    return {
        "generated": datetime.now(UTC).isoformat(),
        "total_acs": total,
        "stub_acs": len(stub_ac_ids),
        "covered_acs": len(covered),
        "uncovered_acs": len(uncovered_ids),
        "orphan_citations": len(orphans),
        "coverage_pct": coverage_pct,
        "matrix": full_matrix,
        "orphans": sorted(orphans),
    }


# ---------------------------------------------------------------------------
# Output modes
# ---------------------------------------------------------------------------
def print_summary(report: dict, ac_map: dict[str, str]) -> None:
    uncovered_ids = [ac for ac, tests in report["matrix"].items() if not tests]
    orphans = report["orphans"]

    print(f"\nAC Traceability Report  {report['generated'][:10]}")
    print("=" * 60)
    print(f"  Total ACs (excl. stubs): {report['total_acs']}")
    print(f"  Stub ACs (excluded):     {report['stub_acs']}")
    print(f"  Covered:                 {report['covered_acs']}")
    print(f"  Uncovered:               {report['uncovered_acs']}")
    print(f"  Orphan citations:        {report['orphan_citations']}")
    print(f"  Coverage:                {report['coverage_pct']}%")

    if orphans:
        print(f"\n⚠  Orphan citations ({len(orphans)}) — cited but not in index.json:")
        for oid in orphans:
            print(f"     {oid}")

    if uncovered_ids:
        print(f"\n○  Uncovered ACs ({len(uncovered_ids)}) — no test marker citation:")
        for ac_id in sorted(uncovered_ids)[:40]:  # cap display at 40
            spec_title = ac_map.get(ac_id, "")
            print(f"     {ac_id}  [{spec_title}]")
        if len(uncovered_ids) > 40:
            print(f"     ... and {len(uncovered_ids) - 40} more")
    else:
        print("\n✓  All ACs have test coverage!")

    print()


def write_json(report: dict, out_path: Path) -> None:
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out_path}")


def write_html(report: dict, ac_map: dict[str, str], out_path: Path) -> None:
    rows: list[str] = []
    for ac_id in sorted(report["matrix"].keys()):
        tests = report["matrix"][ac_id]
        spec_title = ac_map.get(ac_id, "")
        count = len(tests)
        status = "covered" if count else "uncovered"
        bg = "#d4edda" if count else "#f8d7da"
        test_list = "<br>".join(f"<code>{t}</code>" for t in tests) if tests else "—"
        rows.append(
            f'<tr style="background:{bg}">'
            f"<td>{ac_id}</td>"
            f'<td title="{spec_title}">{spec_title[:60]}</td>'
            f"<td>{status}</td>"
            f"<td>{test_list}</td>"
            f"</tr>"
        )

    rows_html = "\n".join(rows)
    coverage = report["coverage_pct"]
    bar_color = "#28a745" if coverage >= 80 else "#ffc107" if coverage >= 40 else "#dc3545"

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
           border: 1px solid #dee2e6; border-radius: 6px; overflow: hidden; }}
  th {{ background: #343a40; color: #fff; padding: 0.5rem 0.75rem;
        text-align: left; font-size: 0.8rem; }}
  td {{ padding: 0.4rem 0.75rem; font-size: 0.8rem; vertical-align: top;
       border-top: 1px solid #dee2e6; }}
  input {{ padding: 0.4rem 0.6rem; border: 1px solid #dee2e6; border-radius: 4px;
           font-size: 0.85rem; margin-bottom: 0.75rem; width: 100%; max-width: 400px; }}
</style>
</head>
<body>
<h1>TTA AC Traceability Report</h1>
<div class="meta">Generated: {report['generated']}</div>

<div class="summary">
  <div class="card"><div class="label">Total ACs</div><div class="value">{report['total_acs']}</div></div>
  <div class="card"><div class="label">Covered</div><div class="value" style="color:#28a745">{report['covered_acs']}</div></div>
  <div class="card"><div class="label">Uncovered</div><div class="value" style="color:#dc3545">{report['uncovered_acs']}</div></div>
  <div class="card"><div class="label">Orphans</div><div class="value" style="color:#fd7e14">{report['orphan_citations']}</div></div>
  <div class="card"><div class="label">Coverage</div><div class="value">{coverage}%</div></div>
</div>

<div class="bar-wrap"><div class="bar-fill"></div></div>

<input type="text" id="filter" placeholder="Filter by AC ID or spec title..." oninput="filterTable(this.value)">

<table id="tbl">
<thead><tr><th>AC ID</th><th>Spec</th><th>Status</th><th>Test(s)</th></tr></thead>
<tbody>
{rows_html}
</tbody>
</table>

<script>
function filterTable(q) {{
  q = q.toLowerCase();
  document.querySelectorAll('#tbl tbody tr').forEach(r => {{
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
    parser = argparse.ArgumentParser(description="AC traceability scanner for TTA specs.")
    parser.add_argument("--validate", action="store_true", help="Print text summary; exit 1 on orphans")
    parser.add_argument("--json", action="store_true", help="Write specs/trace.json")
    parser.add_argument("--html", action="store_true", help="Write specs/trace.html")
    parser.add_argument("--threshold", type=float, default=None, metavar="N",
                        help="Exit 1 if uncovered AC%% exceeds N")
    parser.add_argument("--tests-dir", type=Path, default=TESTS_DIR)
    parser.add_argument("--specs-index", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    if not args.specs_index.exists():
        print(f"ERROR: {args.specs_index} not found. Run `make regen-indexes` first.", file=sys.stderr)
        return 1

    ac_map, stub_ac_ids = load_known_acs(args.specs_index)
    matrix = scan_markers(args.tests_dir)
    report = build_report(ac_map, stub_ac_ids, matrix)

    if args.validate:
        print_summary(report, ac_map)

    if args.json:
        write_json(report, TRACE_JSON)

    if args.html:
        write_html(report, ac_map, TRACE_HTML)

    if not (args.validate or args.json or args.html):
        print_summary(report, ac_map)

    # Exit codes
    if report["orphan_citations"] > 0:
        return 1
    if args.threshold is not None:
        uncovered_pct = 100.0 - report["coverage_pct"]
        if uncovered_pct > args.threshold:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
