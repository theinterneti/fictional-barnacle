# Spec Close-Out Template

Reference template for v1 close-out sections. Copy the frontmatter additions and
section block into each spec. **Do not edit spec ACs, FRs, or scope** — close-outs
are non-normative retrospective sections only.

---

## Frontmatter Additions

Add these two fields immediately after the existing `Status:` line in each spec's
blockquote header block:

```
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ✅ Full  # or ⚠️ Partial or ❌ Significant gaps
```

**`Status:`** — Leave unchanged. This tracks doc lifecycle (Draft/Review/Approved).

**`Release Baseline:`** — New field. Set to `🔒 v1 Closed` for every closed spec.

**`Implementation Fit:`**
- `✅ Full` — All normative ACs verified with evidence
- `⚠️ Partial` — Most ACs verified; 1–2 gaps with known v2 path
- `❌ Significant gaps` — Multiple ACs unverified or unimplemented

---

## Section Template

Append this block verbatim at the bottom of each spec, filling in the
`<!-- ... -->` placeholders:

```markdown
---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It records what shipped in v1,
> evidence used to verify each requirement, gaps found, and items deferred to v2.
> Normative requirements (ACs, FRs) remain unchanged above.

**Closed:** <!-- YYYY-MM-DD -->
**Implementation Fit:** <!-- ✅ Full / ⚠️ Partial / ❌ Significant gaps -->
**Validation Basis:** <!-- one line describing primary evidence source -->

### Evidence / Validation Basis

<!-- One paragraph. State what evidence was used:
     - For S01–S09: cite sim harness scenario names + pass/fail counts, or unit tests
     - For S10–S17, S23–S28: cite specific test files (unit/integration), CI run, or config review
     - For deployment/CI: cite config files reviewed, CI run results
     Never cite sim as sole evidence for platform or ops specs. -->

### Implementation Fit

| Item | Shipped | Verified | Evidence | Notes |
|------|---------|----------|----------|-------|
| <!-- AC-XX.Y — short label --> | ✅/⚠️/❌ | ✅/⚠️/❌ | <!-- test file or sim scenario --> | <!-- optional note --> |

### Deferred to v2

| Item | Reason | v2 Priority |
|------|--------|-------------|
| <!-- AC or FR ref + short description --> | <!-- why deferred --> | <!-- High/Med/Low --> |

### Gaps Found

<!-- Prose summary of gaps discovered via sim or review that are not already tracked
     above. Include observable symptom (what the player/operator sees), root cause
     (which module/design choice), and how this informs v2.
     
     OMIT THIS SECTION if there are no gaps beyond what's in the Deferred table. -->
```

---

## Evidence Validity Rules

| Spec Group | Valid Evidence |
|---|---|
| S01–S09 (core game + AI/content) | Sim harness pass/fail, unit tests, code review |
| S10–S17, S23–S28 (platform + ops) | Unit tests, integration tests, CI results |
| S14, S15 (deployment, observability) | Config review, dashboard screenshots, CI run |
| S16 (testing strategy) | Test suite inventory, coverage report |

**Do not cite sim harness as sole evidence for platform or ops specs.**

---

## Implementation Fit Scale

Use the same scale for both the frontmatter field and the table:

| Symbol | Meaning |
|---|---|
| ✅ | Shipped and verified with evidence |
| ⚠️ | Shipped; gap exists with known v2 resolution path |
| ❌ | Not shipped, or shipped but fundamentally unverified |
