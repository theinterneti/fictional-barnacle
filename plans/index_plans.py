#!/usr/bin/env python3
"""Plan Index Generator for TTA.

Scans the plans/ directory, parses each technical plan file,
and generates a structured index (Markdown and/or JSON) summarizing
all plans, their spec coverage, cross-references, and completeness.

Usage:
    cd plans/
    python index_plans.py              # Print markdown index to stdout
    python index_plans.py --json       # Print JSON index to stdout
    python index_plans.py --out index  # Write both index.md and index.json
    python index_plans.py --validate   # Check plans for quality issues
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ── Plan metadata ──────────────────────────────────────────────

@dataclass
class PlanMeta:
    """Parsed metadata for a single plan file."""

    file: str
    title: str
    scope: str = ""           # e.g. "Cross-cutting", "S07+S08"
    wave: str = ""            # e.g. "Wave 2", "All"
    status: str = "Unknown"
    last_updated: str = ""
    specs_covered: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    subsections: list[str] = field(default_factory=list)
    word_count: int = 0
    line_count: int = 0

    # Quality signals
    has_tech_stack: bool = False
    has_architecture: bool = False
    has_data_models: bool = False
    has_interfaces: bool = False
    has_testing: bool = False
    has_code_blocks: bool = False
    code_block_count: int = 0
    has_normative_markers: bool = False
    normative_sections: list[str] = field(default_factory=list)

    # Cross-references
    spec_refs: list[str] = field(default_factory=list)   # S01, S02, etc.
    plan_refs: list[str] = field(default_factory=list)   # other plan files
    section_refs: list[str] = field(default_factory=list) # §3.2, §4.1, etc.

    warnings: list[str] = field(default_factory=list)


# ── Parsing ────────────────────────────────────────────────────

TITLE_RE = re.compile(r"^#\s+(.+)")
SECTION_RE = re.compile(r"^##\s+(.+)")
SUBSECTION_RE = re.compile(r"^###\s+(.+)")

FRONT_RE = {
    "status": re.compile(r">\s*\*\*Status\*\*:\s*(.+)", re.IGNORECASE),
    "scope": re.compile(r">\s*\*\*Scope\*\*:\s*(.+)", re.IGNORECASE),
    "wave": re.compile(
        r">\s*\*\*(?:Implementation [Ww]ave|Wave)\*\*:\s*(.+)",
        re.IGNORECASE,
    ),
    "specs": re.compile(
        r">\s*\*\*(?:Input [Ss]pecs?|Specs? [Cc]overed)\*\*:\s*(.+)",
        re.IGNORECASE,
    ),
    "updated": re.compile(
        r">\s*\*\*Last Updated\*\*:\s*(.+)", re.IGNORECASE
    ),
}

SPEC_REF_RE = re.compile(r"\bS(\d{2})\b")
PLAN_REF_RE = re.compile(r"`?plans/([a-z0-9-]+\.md)`?")
SECTION_REF_RE = re.compile(r"§(\d+(?:\.\d+)*)")
NORMATIVE_RE = re.compile(r"normative", re.IGNORECASE)
CODE_BLOCK_RE = re.compile(r"^```")

TECH_KEYWORDS = re.compile(
    r"technology|tech stack|framework|librar|dependenc",
    re.IGNORECASE,
)
ARCH_KEYWORDS = re.compile(
    r"architecture|component|boundar|structure|layout",
    re.IGNORECASE,
)
DATA_KEYWORDS = re.compile(
    r"data model|schema|table|entity|database|persist",
    re.IGNORECASE,
)
INTERFACE_KEYWORDS = re.compile(
    r"interface|contract|api|endpoint|protocol|sse|event",
    re.IGNORECASE,
)
TESTING_KEYWORDS = re.compile(
    r"test|coverage|fixture|mock|bdd|gherkin|pytest",
    re.IGNORECASE,
)


def parse_plan(path: Path) -> PlanMeta:
    """Parse a single plan file and extract metadata."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    meta = PlanMeta(
        file=path.name,
        title=path.stem.replace("-", " ").title(),
        word_count=len(text.split()),
        line_count=len(lines),
    )

    # Extract title from first H1
    for line in lines[:5]:
        m = TITLE_RE.match(line)
        if m:
            meta.title = m.group(1).strip()
            break

    # Extract frontmatter
    for line in lines[:20]:
        for key, regex in FRONT_RE.items():
            m = regex.match(line)
            if m:
                val = m.group(1).strip()
                if key == "status":
                    meta.status = val
                elif key == "scope":
                    meta.scope = val
                elif key == "wave":
                    meta.wave = val
                elif key == "specs":
                    meta.specs_covered = [
                        s.strip()
                        for s in re.split(r"[,;]", val)
                        if s.strip()
                    ]
                elif key == "updated":
                    meta.last_updated = val

    # Full-text analysis
    in_code_block = False
    all_spec_refs: set[str] = set()
    all_plan_refs: set[str] = set()
    all_section_refs: set[str] = set()
    all_sections: list[str] = []
    all_subsections: list[str] = []

    for line in lines:
        # Track code blocks
        if CODE_BLOCK_RE.match(line):
            in_code_block = not in_code_block
            if in_code_block:
                meta.code_block_count += 1
            continue

        if in_code_block:
            continue

        # Sections
        sm = SECTION_RE.match(line)
        if sm:
            sec = sm.group(1).strip()
            all_sections.append(sec)

            # Check section topics
            if TECH_KEYWORDS.search(sec):
                meta.has_tech_stack = True
            if ARCH_KEYWORDS.search(sec):
                meta.has_architecture = True
            if DATA_KEYWORDS.search(sec):
                meta.has_data_models = True
            if INTERFACE_KEYWORDS.search(sec):
                meta.has_interfaces = True
            if TESTING_KEYWORDS.search(sec):
                meta.has_testing = True

        ssm = SUBSECTION_RE.match(line)
        if ssm:
            subsec = ssm.group(1).strip()
            all_subsections.append(subsec)

            if TECH_KEYWORDS.search(subsec):
                meta.has_tech_stack = True
            if ARCH_KEYWORDS.search(subsec):
                meta.has_architecture = True
            if DATA_KEYWORDS.search(subsec):
                meta.has_data_models = True
            if INTERFACE_KEYWORDS.search(subsec):
                meta.has_interfaces = True
            if TESTING_KEYWORDS.search(subsec):
                meta.has_testing = True

        # Cross-references
        for m in SPEC_REF_RE.finditer(line):
            all_spec_refs.add(f"S{m.group(1)}")
        for m in PLAN_REF_RE.finditer(line):
            all_plan_refs.add(m.group(1))
        for m in SECTION_REF_RE.finditer(line):
            all_section_refs.add(f"§{m.group(1)}")

        # Normative markers
        if NORMATIVE_RE.search(line):
            meta.has_normative_markers = True
            # Try to find what section it's in
            if all_subsections:
                sec_name = all_subsections[-1]
            elif all_sections:
                sec_name = all_sections[-1]
            else:
                sec_name = "(top-level)"
            meta.normative_sections.append(sec_name)

    meta.has_code_blocks = meta.code_block_count > 0
    meta.sections = all_sections
    meta.subsections = all_subsections
    meta.spec_refs = sorted(all_spec_refs)
    meta.plan_refs = sorted(all_plan_refs)
    meta.section_refs = sorted(all_section_refs)

    # Deduplicate normative sections
    meta.normative_sections = sorted(set(meta.normative_sections))

    # Quality warnings
    if not meta.has_tech_stack and meta.file != "system.md":
        meta.warnings.append("No technology/framework section found")
    if not meta.has_testing:
        meta.warnings.append("No testing section found")
    if not meta.has_code_blocks:
        meta.warnings.append("No code examples found")
    if meta.word_count < 500:
        meta.warnings.append(
            f"Very short ({meta.word_count} words) — may lack detail"
        )
    if not meta.spec_refs:
        meta.warnings.append("No spec references found (S01, S02, etc.)")

    return meta


def discover_plans(plans_dir: Path) -> list[PlanMeta]:
    """Find and parse all plan files in the directory."""
    plans: list[PlanMeta] = []
    for md in sorted(plans_dir.glob("*.md")):
        if md.name in ("README.md", "index.md"):
            continue
        meta = parse_plan(md)
        plans.append(meta)

    # Sort: system.md first, then alphabetically
    plans.sort(key=lambda p: ("0" if p.file == "system.md" else "1") + p.file)
    return plans


# ── Validation ─────────────────────────────────────────────────

def validate_spec_coverage(
    plans: list[PlanMeta], specs_dir: Path | None = None
) -> list[str]:
    """Check which specs are referenced by plans."""
    all_refs: set[str] = set()
    for p in plans:
        all_refs.update(p.spec_refs)

    issues: list[str] = []

    # Check if we can discover specs
    if specs_dir and specs_dir.is_dir():
        known_specs: set[str] = set()
        for md in specs_dir.rglob("*.md"):
            fn_match = re.match(r"(\d+)-", md.name)
            if fn_match:
                known_specs.add(f"S{fn_match.group(1).zfill(2)}")

        # Find unreferenced specs (excluding future stubs S18-S22)
        unreferenced = sorted(
            s for s in known_specs - all_refs
            if s <= "S17"
        )
        if unreferenced:
            issues.append(
                f"Specs not referenced by any plan: {', '.join(unreferenced)}"
            )

        # Find references to nonexistent specs
        bad_refs = sorted(all_refs - known_specs)
        if bad_refs:
            issues.append(
                f"Plans reference nonexistent specs: {', '.join(bad_refs)}"
            )

    return issues


def validate_cross_refs(plans: list[PlanMeta]) -> list[str]:
    """Check that plan-to-plan references are valid."""
    known_files = {p.file for p in plans}
    issues: list[str] = []
    for p in plans:
        for ref in p.plan_refs:
            if ref not in known_files:
                issues.append(
                    f"{p.file}: references {ref} which does not exist"
                )
    return issues


# ── Output formatters ──────────────────────────────────────────

def format_markdown(plans: list[PlanMeta]) -> str:
    """Generate a Markdown index of all plans."""
    lines: list[str] = []
    lines.append("# TTA Technical Plans Index (Auto-Generated)")
    lines.append("")
    lines.append(
        f"**{len(plans)} plans** indexed"
        f" | Generated by `index_plans.py`"
    )
    lines.append("")

    # Overview table
    lines.append("## Plans Overview")
    lines.append("")
    lines.append(
        "| Plan | Wave | Lines | Words | Code Blocks"
        " | Specs Referenced | Normative | Warnings |"
    )
    lines.append(
        "|------|------|------:|------:|:-----------:"
        "|:----------------:|:---------:|----------|"
    )
    for p in plans:
        warns = str(len(p.warnings)) if p.warnings else "—"
        normative = "✅" if p.has_normative_markers else "—"
        specs = ", ".join(p.spec_refs[:5])
        if len(p.spec_refs) > 5:
            specs += f" +{len(p.spec_refs) - 5}"
        lines.append(
            f"| [{p.title}]({p.file})"
            f" | {p.wave or '—'}"
            f" | {p.line_count:,}"
            f" | {p.word_count:,}"
            f" | {p.code_block_count}"
            f" | {specs}"
            f" | {normative}"
            f" | {warns} |"
        )
    lines.append("")

    # Section coverage matrix
    lines.append("## Section Coverage")
    lines.append("")
    lines.append(
        "| Plan | Tech Stack | Architecture | Data Models"
        " | Interfaces | Testing |"
    )
    lines.append(
        "|------|:----------:|:------------:|:-----------:"
        "|:----------:|:-------:|"
    )
    for p in plans:
        lines.append(
            f"| {p.file}"
            f" | {'✅' if p.has_tech_stack else '❌'}"
            f" | {'✅' if p.has_architecture else '❌'}"
            f" | {'✅' if p.has_data_models else '❌'}"
            f" | {'✅' if p.has_interfaces else '❌'}"
            f" | {'✅' if p.has_testing else '❌'} |"
        )
    lines.append("")

    # Normative sections
    normative_plans = [p for p in plans if p.has_normative_markers]
    if normative_plans:
        lines.append("## Normative Sections")
        lines.append("")
        lines.append(
            "These sections are **locked** — component plans may extend"
            " but must not alter them."
        )
        lines.append("")
        for p in normative_plans:
            lines.append(f"### {p.file}")
            for sec in p.normative_sections:
                lines.append(f"- {sec}")
            lines.append("")

    # Cross-reference map
    lines.append("## Cross-Reference Map")
    lines.append("")
    lines.append("### Spec Coverage")
    all_refs: dict[str, list[str]] = {}
    for p in plans:
        for ref in p.spec_refs:
            all_refs.setdefault(ref, []).append(p.file)
    for spec in sorted(all_refs):
        files = ", ".join(all_refs[spec])
        lines.append(f"- **{spec}** → {files}")
    lines.append("")

    # Summary
    total_lines = sum(p.line_count for p in plans)
    total_words = sum(p.word_count for p in plans)
    total_code = sum(p.code_block_count for p in plans)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total plans**: {len(plans)}")
    lines.append(f"- **Total lines**: {total_lines:,}")
    lines.append(f"- **Total words**: {total_words:,}")
    lines.append(f"- **Total code blocks**: {total_code}")
    lines.append(
        f"- **Unique specs referenced**: {len(all_refs)}"
    )
    lines.append(
        f"- **Plans with warnings**: "
        f"{sum(1 for p in plans if p.warnings)}/{len(plans)}"
    )
    lines.append("")

    return "\n".join(lines)


def format_json(plans: list[PlanMeta]) -> str:
    """Generate a JSON index of all plans."""
    data = {
        "plan_count": len(plans),
        "total_lines": sum(p.line_count for p in plans),
        "total_words": sum(p.word_count for p in plans),
        "plans": [asdict(p) for p in plans],
    }
    return json.dumps(data, indent=2)


def format_validation(
    plans: list[PlanMeta], specs_dir: Path | None = None
) -> str:
    """Generate a validation report."""
    lines: list[str] = []
    lines.append("# Plan Validation Report")
    lines.append("")

    # Per-plan warnings
    has_issues = False
    for p in plans:
        if p.warnings:
            has_issues = True
            lines.append(f"### {p.title} ({p.file})")
            for w in p.warnings:
                lines.append(f"  ⚠️  {w}")
            lines.append("")

    if not has_issues:
        lines.append("✅ All plans pass quality checks!")
        lines.append("")

    # Cross-reference issues
    xref_issues = validate_cross_refs(plans)
    spec_issues = validate_spec_coverage(plans, specs_dir)

    if xref_issues or spec_issues:
        lines.append("### Reference Issues")
        for issue in xref_issues + spec_issues:
            lines.append(f"  ❌ {issue}")
        lines.append("")
    else:
        lines.append("✅ No cross-reference issues found.")
        lines.append("")

    # Quality scorecard
    total = len(plans)
    lines.append("### Quality Scorecard")
    lines.append("")
    lines.append("| Metric | Count | % |")
    lines.append("|--------|------:|---:|")
    for label, count in [
        ("Has tech stack section", sum(1 for p in plans if p.has_tech_stack)),
        ("Has architecture section", sum(1 for p in plans if p.has_architecture)),
        ("Has data models section", sum(1 for p in plans if p.has_data_models)),
        ("Has interfaces section", sum(1 for p in plans if p.has_interfaces)),
        ("Has testing section", sum(1 for p in plans if p.has_testing)),
        ("Has code examples", sum(1 for p in plans if p.has_code_blocks)),
        ("Has spec references", sum(1 for p in plans if p.spec_refs)),
        ("Has normative markers", sum(1 for p in plans if p.has_normative_markers)),
        ("No warnings", sum(1 for p in plans if not p.warnings)),
    ]:
        pct = (count / total * 100) if total else 0
        lines.append(f"| {label} | {count}/{total} | {pct:.0f}% |")
    lines.append("")

    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Index and validate TTA technical plan files."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of Markdown",
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
        help="Plans directory to scan (default: directory containing this script)",
    )
    parser.add_argument(
        "--specs-dir",
        default=None,
        help="Specs directory for cross-reference validation",
    )
    args = parser.parse_args()

    plans_dir = Path(args.dir).resolve() if args.dir else Path(__file__).resolve().parent
    if not plans_dir.is_dir():
        print(f"Error: {plans_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    specs_dir = Path(args.specs_dir).resolve() if args.specs_dir else None

    plans = discover_plans(plans_dir)

    if not plans:
        print("No plan files found.", file=sys.stderr)
        sys.exit(1)

    if args.validate:
        output = format_validation(plans, specs_dir)
    elif args.json:
        output = format_json(plans)
    else:
        output = format_markdown(plans)

    if args.out:
        if args.json:
            out_path = Path(f"{args.out}.json")
            out_path.write_text(output, encoding="utf-8")
            print(f"Wrote {out_path}")
        elif args.validate:
            out_path = Path(f"{args.out}-validation.md")
            out_path.write_text(output, encoding="utf-8")
            print(f"Wrote {out_path}")
        else:
            md_path = Path(f"{args.out}.md")
            md_path.write_text(output, encoding="utf-8")
            print(f"Wrote {md_path}")

            json_output = format_json(plans)
            json_path = Path(f"{args.out}.json")
            json_path.write_text(json_output, encoding="utf-8")
            print(f"Wrote {json_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()
