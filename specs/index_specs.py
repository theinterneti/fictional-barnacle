#!/usr/bin/env python3
"""Spec Index Generator for TTA.

Scans the specs/ directory, parses frontmatter from each spec file,
and generates a structured index (Markdown and/or JSON) summarizing
all specifications, their status, dependencies, and completeness.

Usage:
    cd specs/
    python index_specs.py              # Print markdown index to stdout
    python index_specs.py --json       # Print JSON index to stdout
    python index_specs.py --out index  # Write both index.md and index.json
    python index_specs.py --validate   # Check specs for quality issues
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── Spec metadata ──────────────────────────────────────────────


@dataclass
class SpecMeta:
    """Parsed metadata for a single spec file."""

    file: str
    number: str  # e.g. "S00", "S14"
    title: str
    status: str  # e.g. "📝 Draft", "✅ Approved"
    level: str  # e.g. "0 — Foundation"
    dependencies: list[str] = field(default_factory=list)
    last_updated: str = ""
    sections: list[str] = field(default_factory=list)
    word_count: int = 0
    has_acceptance_criteria: bool = False
    acceptance_criteria_count: int = 0
    has_user_stories: bool = False
    has_edge_cases: bool = False
    has_out_of_scope: bool = False
    has_open_questions: bool = False
    has_given_when_then: bool = False
    has_gherkin_scenarios: bool = False
    gherkin_scenario_count: int = 0
    warnings: list[str] = field(default_factory=list)


# ── Parsing ────────────────────────────────────────────────────

# Matches lines like: > **Status**: 📝 Draft
FRONT_RE = {
    "status": re.compile(r">\s*\*\*Status\*\*:\s*(.+)", re.IGNORECASE),
    "level": re.compile(r">\s*\*\*Level\*\*:\s*(.+)", re.IGNORECASE),
    "deps": re.compile(r">\s*\*\*Dependencies?\*\*:\s*(.+)", re.IGNORECASE),
    "updated": re.compile(r">\s*\*\*Last Updated\*\*:\s*(.+)", re.IGNORECASE),
}

TITLE_RE = re.compile(r"^#\s+S(\d+)\s*[—–-]\s*(.+)", re.IGNORECASE)
SECTION_RE = re.compile(r"^##\s+\d*\.?\s*(.+)")
AC_ITEM_RE = re.compile(
    r"^-\s*\[[ x]\]\s*\*\*AC-\d+"  # - [ ] **AC-XX**: (S00, S23-S28)
    r"|^-\s+\*\*AC-\d+",  # - **AC-XX.YY**: (S01-S13)
    re.IGNORECASE,
)
# Group headings like ### AC-07.1 — deferred counting (may have sub-items)
AC_GROUP_RE = re.compile(r"^###\s*AC-\d+", re.IGNORECASE)
AC_SECTION_RE = re.compile(r"^#{2,3}\s+.*(?:Acceptance\s+Criteria)", re.IGNORECASE)
AC_CHECKBOX_RE = re.compile(r"^-\s*\[[ x]\]")
STORY_RE = re.compile(
    r"\*\*As a\*\*|>\s*As a\s+\*\*|As a \*\*"
    r"|US-\d+.*:\s*As a",
    re.IGNORECASE,
)
GWT_RE = re.compile(r"(given|when|then)\s", re.IGNORECASE)
GHERKIN_RE = re.compile(
    r"^\s*(Feature|Scenario|Given|When|Then|And|But)[\s:]",
    re.IGNORECASE,
)
EDGE_CASE_RE = re.compile(r"edge case", re.IGNORECASE)


def parse_spec(path: Path) -> SpecMeta | None:
    """Parse a single spec file and extract metadata."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Extract title
    title_match = None
    number = ""
    title = path.stem
    for line in lines[:10]:
        m = TITLE_RE.match(line)
        if m:
            number = f"S{m.group(1).zfill(2)}"
            title = m.group(2).strip()
            title_match = m
            break

    if not title_match:
        # Try to get number from filename
        fn_match = re.match(r"(\d+)-(.+)\.md", path.name)
        if fn_match:
            number = f"S{fn_match.group(1).zfill(2)}"
            title = fn_match.group(2).replace("-", " ").title()

    meta = SpecMeta(
        file=str(path),
        number=number,
        title=title,
        status="Unknown",
        level="Unknown",
        word_count=len(text.split()),
    )

    # Extract frontmatter fields
    for line in lines[:20]:
        for key, regex in FRONT_RE.items():
            m = regex.match(line)
            if m:
                val = m.group(1).strip()
                if key == "status":
                    meta.status = val
                elif key == "level":
                    meta.level = val
                elif key == "deps":
                    meta.dependencies = [
                        d.strip()
                        for d in re.split(r"[,;]", val)
                        if d.strip() and d.strip().lower() not in ("none", "n/a", "-")
                    ]
                elif key == "updated":
                    meta.last_updated = val

    # Extract sections and quality signals
    in_ac_section = False
    pending_ac_group = False  # Deferred count for ### AC- group headings
    for line in lines:
        sm = SECTION_RE.match(line)
        if sm:
            meta.sections.append(sm.group(1).strip())

        # Track AC sections (both ## and ### level)
        if AC_SECTION_RE.match(line):
            in_ac_section = True
        elif re.match(r"^#{2,3}\s+", line) and not AC_SECTION_RE.match(line):
            if not AC_GROUP_RE.match(line):
                # Leaving AC area — flush any pending group heading
                if pending_ac_group:
                    meta.has_acceptance_criteria = True
                    meta.acceptance_criteria_count += 1
                    pending_ac_group = False
                in_ac_section = False

        if AC_GROUP_RE.match(line):
            # Flush previous group if it had no sub-items (S08 case)
            if pending_ac_group:
                meta.has_acceptance_criteria = True
                meta.acceptance_criteria_count += 1
            pending_ac_group = True
            in_ac_section = True
        elif AC_ITEM_RE.match(line):
            pending_ac_group = False
            meta.has_acceptance_criteria = True
            meta.acceptance_criteria_count += 1
            in_ac_section = True
        elif in_ac_section and AC_CHECKBOX_RE.match(line):
            pending_ac_group = False
            meta.has_acceptance_criteria = True
            meta.acceptance_criteria_count += 1

        if STORY_RE.search(line):
            meta.has_user_stories = True

        if GWT_RE.search(line):
            meta.has_given_when_then = True

        if GHERKIN_RE.match(line):
            meta.has_gherkin_scenarios = True
            if re.match(r"\s*Scenario", line, re.IGNORECASE):
                meta.gherkin_scenario_count += 1
                # v2+ specs embed Gherkin inside an Acceptance Criteria section;
                # count each Scenario as an AC item (Scenario: AC-NN.NN format).
                pattern = r"\s*Scenario:\s*AC-\d+"
                if in_ac_section and re.match(pattern, line, re.IGNORECASE):
                    meta.has_acceptance_criteria = True
                    meta.acceptance_criteria_count += 1

    # Flush any pending AC group at end of file
    if pending_ac_group:
        meta.has_acceptance_criteria = True
        meta.acceptance_criteria_count += 1

    # Check section presence (also check subsection headers in body)
    section_lower = [s.lower() for s in meta.sections]
    meta.has_edge_cases = any("edge" in s for s in section_lower) or bool(
        re.search(r"^#{2,3}\s+.*edge\s+case", text, re.IGNORECASE | re.MULTILINE)
    )
    meta.has_out_of_scope = any("out of scope" in s for s in section_lower) or bool(
        re.search(r"^#{2,3}\s+.*out\s+of\s+scope", text, re.IGNORECASE | re.MULTILINE)
    )
    meta.has_open_questions = any("open question" in s for s in section_lower)

    # Quality warnings
    if not meta.has_acceptance_criteria:
        meta.warnings.append("Missing acceptance criteria")
    elif meta.acceptance_criteria_count < 3:
        meta.warnings.append(
            f"Only {meta.acceptance_criteria_count} acceptance criteria (aim for ≥5)"
        )
    if not meta.has_user_stories:
        meta.warnings.append("No user stories found")
    if not meta.has_edge_cases:
        meta.warnings.append("No edge cases section")
    if not meta.has_out_of_scope:
        meta.warnings.append("No 'Out of Scope' section")
    if meta.word_count < 200:
        meta.warnings.append(f"Very short ({meta.word_count} words) — may lack detail")
    if (
        not meta.has_gherkin_scenarios
        and "stub" not in meta.status.lower()
        and "future" not in meta.level.lower()
    ):
        meta.warnings.append("No Gherkin scenarios — ACs should use Given/When/Then")

    return meta


def discover_specs(specs_dir: Path) -> list[SpecMeta]:
    """Find and parse all spec files in the directory tree."""
    specs: list[SpecMeta] = []
    for md in sorted(specs_dir.rglob("*.md")):
        # Skip non-spec files
        if md.name in (
            "README.md",
            "TEMPLATE.md",
            "index.md",
        ):
            continue
        meta = parse_spec(md)
        if meta:
            # Store path relative to specs_dir
            meta.file = str(md.relative_to(specs_dir))
            specs.append(meta)

    # Sort by spec number
    specs.sort(key=lambda s: s.number)
    return specs


# ── Dependency validation ──────────────────────────────────────


def validate_dependencies(specs: list[SpecMeta]) -> list[str]:
    """Check that all declared dependencies reference existing specs."""
    known = {s.number for s in specs}
    issues: list[str] = []
    for spec in specs:
        for dep in spec.dependencies:
            # Normalize: "S00", "S00 (Charter)", "S00, S04"
            dep_num = re.match(r"(S\d+)", dep)
            if dep_num and dep_num.group(1) not in known:
                issues.append(
                    f"{spec.number}: depends on {dep_num.group(1)} which does not exist"
                )
    return issues


def check_circular_deps(specs: list[SpecMeta]) -> list[str]:
    """Detect circular dependencies in the spec graph."""
    graph: dict[str, set[str]] = {}
    for s in specs:
        deps = set()
        for d in s.dependencies:
            m = re.match(r"(S\d+)", d)
            if m:
                deps.add(m.group(1))
        graph[s.number] = deps

    issues: list[str] = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, WHITE)
    path: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in graph.get(node, set()):
            if color.get(dep, WHITE) == GRAY:
                cycle = path[path.index(dep) :] + [dep]
                issues.append(f"Circular dependency: {' → '.join(cycle)}")
            elif color.get(dep, WHITE) == WHITE:
                dfs(dep)
        path.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    return issues


# ── Output formatters ──────────────────────────────────────────


def format_markdown(specs: list[SpecMeta]) -> str:
    """Generate a Markdown index of all specs."""
    lines: list[str] = []
    lines.append("# TTA Spec Index (Auto-Generated)")
    lines.append("")
    lines.append(f"**{len(specs)} specs** indexed | Generated by `index_specs.py`")
    lines.append("")

    # Group by level
    levels: dict[str, list[SpecMeta]] = {}
    for s in specs:
        level_key = s.level if s.level != "Unknown" else "Ungrouped"
        levels.setdefault(level_key, []).append(s)

    for level, group in levels.items():
        lines.append(f"## {level}")
        lines.append("")
        lines.append(
            "| # | Title | Status | Words | ACs"
            " | Gherkin | Stories | Edge Cases | Warnings |"
        )
        lines.append(
            "|---|-------|--------|------:|----:"
            "|-------:|:-------:|:----------:|----------|"
        )
        for s in group:
            warns = ", ".join(s.warnings) if s.warnings else "—"
            lines.append(
                f"| {s.number}"
                f" | [{s.title}]({s.file})"
                f" | {s.status}"
                f" | {s.word_count}"
                f" | {s.acceptance_criteria_count}"
                f" | {s.gherkin_scenario_count}"
                f" | {'✅' if s.has_user_stories else '❌'}"
                f" | {'✅' if s.has_edge_cases else '❌'}"
                f" | {warns} |"
            )
        lines.append("")

    # Summary statistics
    total_words = sum(s.word_count for s in specs)
    total_acs = sum(s.acceptance_criteria_count for s in specs)
    specs_with_warnings = sum(1 for s in specs if s.warnings)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total specs**: {len(specs)}")
    lines.append(f"- **Total words**: {total_words:,}")
    lines.append(f"- **Total acceptance criteria**: {total_acs}")
    lines.append(f"- **Specs with warnings**: {specs_with_warnings}/{len(specs)}")
    lines.append(
        f"- **Specs with Gherkin scenarios**: "
        f"{sum(1 for s in specs if s.has_gherkin_scenarios)}/{len(specs)}"
    )
    lines.append(
        f"- **Total Gherkin scenarios**: {sum(s.gherkin_scenario_count for s in specs)}"
    )
    lines.append(
        f"- **Specs with Given/When/Then**: "
        f"{sum(1 for s in specs if s.has_given_when_then)}/{len(specs)}"
    )
    lines.append("")

    return "\n".join(lines)


def _spec_score(s: SpecMeta) -> int:
    """Return 0–100 completeness score based on weighted quality signals.

    Signal weights (totalling 100):
      has_acceptance_criteria   25 pts — core quality requirement
      has_gherkin_scenarios     25 pts — behavioural test coverage
      has_edge_cases/scope      20 pts — boundary and scope thinking
      has_user_stories          15 pts — stakeholder perspective
      word_count >= 1000        15 pts — sufficient depth
    """
    pts = 0
    if s.has_acceptance_criteria:
        pts += 25
    if s.has_gherkin_scenarios:
        pts += 25
    if s.has_edge_cases or s.has_out_of_scope:
        pts += 20
    if s.has_user_stories:
        pts += 15
    if s.word_count >= 1000:
        pts += 15
    return pts


def _score_color(score: int) -> str:
    if score >= 85:
        return "#22c55e"
    if score >= 60:
        return "#f59e0b"
    if score >= 30:
        return "#f97316"
    return "#ef4444"


def format_html(specs: list[SpecMeta]) -> str:
    """Generate a self-contained HTML completeness dashboard."""
    from datetime import UTC, datetime

    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    # Exclude template pseudo-spec from stats
    real_specs = [s for s in specs if s.number]
    total_words = sum(s.word_count for s in real_specs)
    has_ac_count = sum(1 for s in real_specs if s.has_acceptance_criteria)
    clean_count = sum(1 for s in real_specs if not s.warnings)
    ac_pct = round(has_ac_count / len(real_specs) * 100) if real_specs else 0

    # Group by level
    levels: dict[str, list[SpecMeta]] = {}
    for s in specs:
        key = s.level if s.level != "Unknown" else "Ungrouped"
        levels.setdefault(key, []).append(s)

    def make_group_html(level: str, group: list[SpecMeta]) -> str:
        real = [s for s in group if s.number]
        if not real:
            real = group
        grp_clean = sum(1 for s in real if not s.warnings)
        grp_pct = round(grp_clean / len(real) * 100) if real else 0
        rows = []
        for s in real:
            score = _spec_score(s)
            color = _score_color(score)
            bar_w = score
            warns_html = ""
            if s.warnings:
                chips = "".join(f'<span class="chip">{w}</span>' for w in s.warnings)
                warns_html = chips
            else:
                warns_html = '<span class="badge-clean">✓ clean</span>'
            stub_cls = " stub" if "Stub" in s.status else ""
            row = (
                f'<tr class="spec-row{stub_cls}">'
                f'<td class="num">{s.number}</td>'
                f'<td class="title"><a href="{s.file}">{s.title}</a></td>'
                f'<td class="bar-cell">'
                f'  <div class="bar-wrap">'
                f'    <div class="bar-fill" style="width:{bar_w}%;background:{color}"></div>'
                f"  </div>"
                f'  <span class="score-label">{score}</span>'
                f"</td>"
                f'<td class="num-cell">{s.word_count:,}</td>'
                f'<td class="num-cell">{s.acceptance_criteria_count}</td>'
                f'<td class="num-cell">{s.gherkin_scenario_count}</td>'
                f'<td class="warns">{warns_html}</td>'
                f"</tr>"
            )
            rows.append(row)
        rows_html = "\n".join(rows)
        slug = level.lower().replace(" ", "-").replace("—", "").replace("–", "")
        return (
            f'<div class="group" id="grp-{slug}">'
            f'<div class="group-header">'
            f"  <h2>{level}</h2>"
            f'  <div class="grp-meta">'
            f'    <span class="grp-count">{len(real)} specs</span>'
            f'    <span class="grp-clean-pct">{grp_pct}% clean</span>'
            f'    <div class="grp-bar-wrap">'
            f'      <div class="grp-bar-fill" style="width:{grp_pct}%"></div>'
            f"    </div>"
            f"  </div>"
            f"</div>"
            f"<table>"
            f"<thead><tr>"
            f"  <th>#</th><th>Title</th>"
            f'  <th class="th-score">Score</th>'
            f'  <th class="num-cell">Words</th>'
            f'  <th class="num-cell">ACs</th>'
            f'  <th class="num-cell">Gherkin</th>'
            f"  <th>Warnings</th>"
            f"</tr></thead>"
            f"<tbody>{rows_html}</tbody>"
            f"</table>"
            f"</div>"
        )

    groups_html = "\n".join(make_group_html(lvl, grp) for lvl, grp in levels.items())

    css = """
:root {
  --bg: #f8fafc; --surface: #ffffff; --border: #e2e8f0;
  --text: #0f172a; --muted: #64748b;
  --green: #22c55e; --amber: #f59e0b; --red: #ef4444;
  --accent: #6366f1;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg);
       color: var(--text); font-size: 14px; line-height: 1.5; }
header { background: var(--accent); color: #fff; padding: 24px 32px; }
header h1 { font-size: 1.5rem; font-weight: 700; letter-spacing: -.02em; }
header p { opacity: .75; font-size: .85rem; margin-top: 4px; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
         padding: 24px 32px; }
.stat-card { background: var(--surface); border: 1px solid var(--border);
             border-radius: 10px; padding: 20px; text-align: center; }
.stat-card .val { font-size: 2rem; font-weight: 800; color: var(--accent);
                  line-height: 1; }
.stat-card .lbl { color: var(--muted); font-size: .8rem; margin-top: 6px;
                  text-transform: uppercase; letter-spacing: .04em; }
.groups { padding: 0 32px 48px; display: flex; flex-direction: column; gap: 28px; }
.group { background: var(--surface); border: 1px solid var(--border);
         border-radius: 10px; overflow: hidden; }
.group-header { display: flex; align-items: center; gap: 16px;
                padding: 14px 20px; background: #f1f5f9; border-bottom: 1px solid var(--border); }
.group-header h2 { font-size: .95rem; font-weight: 700; flex: 1; }
.grp-meta { display: flex; align-items: center; gap: 10px; }
.grp-count, .grp-clean-pct { font-size: .8rem; color: var(--muted); white-space: nowrap; }
.grp-bar-wrap { width: 80px; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; }
.grp-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .3s; }
table { width: 100%; border-collapse: collapse; }
thead th { background: #f8fafc; font-size: .75rem; font-weight: 600;
           text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
           padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }
tbody tr { border-bottom: 1px solid #f1f5f9; transition: background .1s; }
tbody tr:last-child { border-bottom: none; }
tbody tr:hover { background: #f8fafc; }
tbody tr.stub { opacity: .6; }
td { padding: 9px 12px; vertical-align: middle; }
.num { font-weight: 700; font-size: .8rem; color: var(--muted); white-space: nowrap; width: 40px; }
.title a { color: var(--text); text-decoration: none; font-weight: 500; }
.title a:hover { color: var(--accent); text-decoration: underline; }
.bar-cell { display: flex; align-items: center; gap: 8px; min-width: 140px; }
.bar-wrap { flex: 1; height: 8px; background: #e2e8f0; border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; transition: width .3s; }
.score-label { font-size: .75rem; font-weight: 700; color: var(--muted); width: 26px; text-align: right; }
.num-cell { text-align: right; color: var(--muted); font-size: .82rem; white-space: nowrap; }
th.num-cell { text-align: right; }
.warns { max-width: 340px; }
.chip { display: inline-block; background: #fef3c7; color: #92400e;
        font-size: .72rem; padding: 2px 7px; border-radius: 12px;
        margin: 2px 2px 2px 0; white-space: nowrap; }
.badge-clean { display: inline-block; background: #dcfce7; color: #166534;
               font-size: .75rem; padding: 2px 8px; border-radius: 12px;
               font-weight: 600; }
footer { text-align: center; color: var(--muted); font-size: .78rem;
         padding: 24px; border-top: 1px solid var(--border); }
@media (max-width: 800px) {
  .stats { grid-template-columns: repeat(2, 1fr); }
  .groups, .stats { padding-left: 16px; padding-right: 16px; }
}
"""

    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>TTA Spec Completeness Dashboard</title>",
        f"<style>{css}</style>",
        "</head>",
        "<body>",
        "<header>",
        "  <h1>TTA Spec Completeness Dashboard</h1>",
        f"  <p>Generated {generated} &nbsp;·&nbsp; {len(real_specs)} specs &nbsp;·&nbsp;"
        f" <code>specs/index_specs.py --html</code></p>",
        "</header>",
        '<section class="stats">',
        f'  <div class="stat-card"><div class="val">{len(real_specs)}</div>'
        f'    <div class="lbl">Total Specs</div></div>',
        f'  <div class="stat-card"><div class="val">{total_words:,}</div>'
        f'    <div class="lbl">Total Words</div></div>',
        f'  <div class="stat-card"><div class="val">{ac_pct}%</div>'
        f'    <div class="lbl">AC Coverage</div></div>',
        f'  <div class="stat-card"><div class="val">{clean_count}</div>'
        f'    <div class="lbl">Clean Specs</div></div>',
        "</section>",
        '<section class="groups">',
        groups_html,
        "</section>",
        "<footer>",
        f"  Generated by <code>specs/index_specs.py</code> on {generated}."
        f" Scores: AC 25pt + Gherkin 25pt + Scope/Edge 20pt + Stories 15pt + Depth≥1k 15pt.",
        "</footer>",
        "</body>",
        "</html>",
    ]
    return "\n".join(html_parts)


def format_json(specs: list[SpecMeta]) -> str:
    """Generate a JSON index of all specs."""
    data = {
        "spec_count": len(specs),
        "total_words": sum(s.word_count for s in specs),
        "total_acceptance_criteria": sum(s.acceptance_criteria_count for s in specs),
        "specs": [asdict(s) for s in specs],
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def format_validation(specs: list[SpecMeta]) -> str:
    """Generate a validation report."""
    lines: list[str] = []
    lines.append("# Spec Validation Report")
    lines.append("")

    # Per-spec warnings
    has_issues = False
    for s in specs:
        if s.warnings:
            has_issues = True
            lines.append(f"### {s.number} — {s.title}")
            for w in s.warnings:
                lines.append(f"  ⚠️  {w}")
            lines.append("")

    if not has_issues:
        lines.append("✅ All specs pass quality checks!")
        lines.append("")

    # Dependency issues
    dep_issues = validate_dependencies(specs)
    cycle_issues = check_circular_deps(specs)

    if dep_issues or cycle_issues:
        lines.append("### Dependency Issues")
        for issue in dep_issues + cycle_issues:
            lines.append(f"  ❌ {issue}")
        lines.append("")
    else:
        lines.append("✅ No dependency issues found.")
        lines.append("")

    # Stats
    total = len(specs)
    lines.append("### Quality Scorecard")
    lines.append("")
    lines.append("| Metric | Count | % |")
    lines.append("|--------|------:|---:|")
    for label, count in [
        (
            "Has acceptance criteria",
            sum(1 for s in specs if s.has_acceptance_criteria),
        ),
        (
            "Has Gherkin scenarios",
            sum(1 for s in specs if s.has_gherkin_scenarios),
        ),
        (
            "Has user stories",
            sum(1 for s in specs if s.has_user_stories),
        ),
        (
            "Has edge cases",
            sum(1 for s in specs if s.has_edge_cases),
        ),
        (
            "Has out-of-scope",
            sum(1 for s in specs if s.has_out_of_scope),
        ),
        (
            "Has Given/When/Then",
            sum(1 for s in specs if s.has_given_when_then),
        ),
        ("No warnings", sum(1 for s in specs if not s.warnings)),
    ]:
        pct = (count / total * 100) if total else 0
        lines.append(f"| {label} | {count}/{total} | {pct:.0f}% |")
    lines.append("")

    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Index and validate TTA spec files.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of Markdown",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Output self-contained HTML dashboard",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run quality validation checks",
    )
    parser.add_argument(
        "--out",
        metavar="PREFIX",
        help="Write output to files (PREFIX.md and/or PREFIX.json)",
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="Specs directory to scan (default: directory containing this script)",
    )
    args = parser.parse_args()

    if args.dir:
        specs_dir = Path(args.dir).resolve()
    else:
        specs_dir = Path(__file__).resolve().parent
    if not specs_dir.is_dir():
        print(f"Error: {specs_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    specs = discover_specs(specs_dir)

    if not specs:
        print("No spec files found.", file=sys.stderr)
        sys.exit(1)

    if args.validate:
        output = format_validation(specs)
    elif args.json:
        output = format_json(specs)
    elif args.html:
        output = format_html(specs)
    else:
        output = format_markdown(specs)

    if args.out:
        if args.json:
            out_path = Path(f"{args.out}.json")
            out_path.write_text(output, encoding="utf-8")
            print(f"Wrote {out_path}")
        elif args.validate:
            out_path = Path(f"{args.out}-validation.md")
            out_path.write_text(output, encoding="utf-8")
            print(f"Wrote {out_path}")
        elif args.html:
            out_path = Path(f"{args.out}.html")
            out_path.write_text(output, encoding="utf-8")
            print(f"Wrote {out_path}")
        else:
            # Write both markdown and JSON
            md_path = Path(f"{args.out}.md")
            md_path.write_text(output, encoding="utf-8")
            print(f"Wrote {md_path}")

            json_output = format_json(specs)
            json_path = Path(f"{args.out}.json")
            json_path.write_text(json_output, encoding="utf-8")
            print(f"Wrote {json_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()
