---
title: Spec Completeness Visualization Dashboard
version: 1.0
date_created: 2026-04-21
owner: TTA Core Team
tags: [design, process, documentation, tooling]
---

# Introduction

This specification defines a self-contained HTML visualization dashboard generated
from the TTA spec corpus. The dashboard gives contributors an at-a-glance view of
specification completeness, quality signals, and outstanding work across all spec
levels and groups.

## 1. Purpose & Scope

The spec index tool (`specs/index_specs.py`) already parses all spec files and
produces structured data. This specification extends it to emit a third output
format—a self-contained HTML file—that renders that data as a visual dashboard
without any external dependencies.

**Intended audience**: TTA contributors, spec authors, reviewers.
**Scope**: `specs/index_specs.py` — add `format_html()` and `--html` CLI flag.

## 2. Definitions

| Term | Definition |
|------|-----------|
| Completeness Score | A 0–100 integer derived from weighted quality signals per spec |
| Quality Signal | A boolean property detected by the parser (e.g. has_acceptance_criteria) |
| Group | A set of specs sharing the same `level` frontmatter value |
| Clean Spec | A spec with zero validator warnings |
| Self-contained HTML | A single `.html` file with all CSS and JS inlined; no CDN or network requests |
| SpecMeta | The parsed dataclass produced by `parse_spec()` in `index_specs.py` |

## 3. Requirements, Constraints & Guidelines

- **REQ-001**: The HTML output MUST be a single file with all CSS/JS inlined; no external network requests.
- **REQ-002**: Each spec MUST display a completeness score (0–100) as a visual progress bar.
- **REQ-003**: Specs MUST be grouped by their `level` field, matching the Markdown index grouping.
- **REQ-004**: The dashboard MUST show aggregate statistics: total specs, total words, overall AC coverage %, and clean spec count.
- **REQ-005**: Each spec row MUST link to its source Markdown file (relative path from `specs/`).
- **REQ-006**: Warning chips MUST be rendered per spec; zero-warning specs MUST be visually distinct (green).
- **REQ-007**: The completeness score formula MUST be deterministic and documented in code.
- **REQ-008**: The `--html` flag MUST write `<PREFIX>.html` when `--out PREFIX` is also supplied.
- **REQ-009**: The `--html` flag without `--out` MUST print HTML to stdout.
- **CON-001**: No external CSS frameworks, fonts, or icon libraries. Pure CSS only.
- **CON-002**: The file MUST render correctly in a modern browser without a web server (file:// protocol).
- **CON-003**: No build step; the HTML is generated directly by the existing Python script.
- **GUD-001**: Use a light, professional color palette with sufficient contrast (WCAG AA).
- **GUD-002**: Keep the rendered file under 500 KB for repos with ≤200 specs.

## 4. Interfaces & Data Contracts

### 4.1 CLI Interface

```
python specs/index_specs.py --html              # print HTML to stdout
python specs/index_specs.py --html --out index  # write specs/index.html
```

The `--html` flag is mutually exclusive with `--json` and `--validate`.

### 4.2 Completeness Score Formula

```python
def _spec_score(s: SpecMeta) -> int:
    """Return 0–100 completeness score."""
    pts = 0
    if s.has_acceptance_criteria:   pts += 25   # core quality signal
    if s.has_gherkin_scenarios:     pts += 25   # behavioural test coverage
    if s.has_user_stories:          pts += 15   # stakeholder perspective
    if s.has_edge_cases or s.has_out_of_scope:  pts += 20  # boundary thinking
    if s.word_count >= 1000:        pts += 15   # sufficient depth
    return pts
```

### 4.3 Color Mapping

| Score Range | Bar Color | Meaning |
|-------------|-----------|---------|
| 85–100 | `#22c55e` (green) | Complete |
| 60–84 | `#f59e0b` (amber) | Mostly complete |
| 30–59 | `#f97316` (orange) | Partial |
| 0–29 | `#ef4444` (red) | Minimal |

Warning chip colors: `#fef3c7` background / `#92400e` text.

### 4.4 HTML Structure

```
<body>
  <header>          <!-- title, generated timestamp -->
  <section.stats>   <!-- 4 stat cards: specs, words, AC%, clean -->
  <section.groups>
    <div.group>*    <!-- one per level -->
      <h2>          <!-- level name + group progress bar -->
      <table>       <!-- spec rows: number | title | score bar | words | ACs | warnings -->
  <footer>
```

## 5. Acceptance Criteria

- **AC-001**: Given the script is run with `--html --out index`, When it completes, Then `index.html` exists in the working directory with `<!DOCTYPE html>` on line 1.
- **AC-002**: Given `index.html` is opened in a browser, When the page loads, Then no console errors appear and no network requests are made.
- **AC-003**: Given a spec has `has_acceptance_criteria=True` and `has_gherkin_scenarios=True` and `has_user_stories=True` and `has_out_of_scope=True` and `word_count >= 1000`, When the dashboard renders, Then that spec's progress bar shows 100% and is green.
- **AC-004**: Given a spec has zero quality signals and `word_count < 1000`, When the dashboard renders, Then that spec's progress bar shows 0% and is red.
- **AC-005**: Given a spec has warnings, When the dashboard renders, Then each warning appears as a chip label in that spec's row.
- **AC-006**: Given a spec has zero warnings, When the dashboard renders, Then its row has a green "✓ clean" badge.
- **AC-007**: Given the `make dashboard` target is run, When it completes, Then `specs/index.html` is created or updated.

## 6. Test Automation Strategy

- **Test Levels**: Script-level smoke test via `make dashboard && python -c "from pathlib import Path; h=Path('specs/index.html').read_text(); assert '<!DOCTYPE html>' in h and 'index_specs' in h"`
- **Manual Verification**: Open `specs/index.html` in a browser; confirm all groups render, bars are colored, links resolve.
- **CI/CD Integration**: `make dashboard` can be added as a post-validate step; output is a generated artifact not checked into source.

## 7. Rationale & Context

The existing Markdown index (`specs/index.md`) is machine-readable but hard to scan
visually for contributors deciding which specs need attention. An HTML dashboard with
color-coded progress bars allows quick triage — e.g., "which v4+ specs are missing
user stories?" — without reading each file.

The self-contained constraint (no CDN) keeps the tool usable offline and in air-gapped
environments, consistent with the project's OSS-first philosophy.

## 8. Dependencies & External Integrations

- **PLT-001**: Python 3.12+ standard library only (`pathlib`, `json`, `re`, `datetime`). No third-party packages.
- **PLT-002**: The generated HTML targets ES2020-capable browsers (Chrome 89+, Firefox 90+, Safari 15+).

## 9. Examples & Edge Cases

```html
<!-- Spec row example (conceptual) -->
<tr class="spec-row clean">
  <td class="spec-num">S29</td>
  <td class="spec-title"><a href="29-universe-as-first-class-entity.md">Universe as First-Class Entity</a></td>
  <td class="spec-bar"><div class="bar" style="width:100%;background:#22c55e"></div><span>100</span></td>
  <td class="spec-words">3,669</td>
  <td class="spec-acs">13</td>
  <td class="spec-warnings"><span class="badge clean">✓ clean</span></td>
</tr>
```

**Edge cases**:
- Specs with `status = "📝 Stub (Future)"` are rendered with reduced opacity to de-emphasise them.
- The CLOSEOUT_TEMPLATE pseudo-spec is excluded from score calculations and summary stats.
- Specs with `level = "Unknown"` are rendered in an "Ungrouped" section at the top.

## 10. Validation Criteria

1. `python specs/index_specs.py --html --out index && mv index.html specs/` exits 0.
2. `wc -c specs/index.html` is < 512000 bytes.
3. `grep -c '<tr' specs/index.html` equals the spec count reported by `--validate`.
4. `grep 'http\|https\|cdn\|font.googleapis' specs/index.html` returns no matches.

## 11. Related Specifications / Further Reading

- [`specs/index_specs.py`](../specs/index_specs.py) — the script being extended
- [`specs/index.md`](../specs/index.md) — existing Markdown index
- [`plans/index.md`](../plans/index.md) — plans index (separate tool)
- [WCAG 2.1 Contrast Guidelines](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html)
