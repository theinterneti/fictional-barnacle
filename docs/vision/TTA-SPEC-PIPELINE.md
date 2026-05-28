# TTA Spec Pipeline Governance

> **Status**: Active governance document
> **Purpose**: Define the lifecycle stages every spec moves through, map all 73 current specs to their stage, and provide the canonical directory structure.
> **Last Updated**: 2026-05-28

---

## 1. Pipeline Stages

Every TTA spec belongs to exactly one stage. Advancement requires explicit evidence — no spec silently graduates.

```
 STUB ──→ DRAFT ──→ REVIEW ──→ APPROVED ──→ PLANNED ──→ IMPLEMENTING ──→ DONE ──→ ARCHIVED
  │         │          │           │             │             │            │
  └── Can stay here indefinitely (boundary/future stubs)
```

### Stage Definitions

| Stage | Meaning | Required Evidence | Who Advances |
|---|---|---|---|
| **STUB** | Placeholder for future work. May have a title and one-paragraph intent. No ACs, no stories. | N/A (entry point) | Author |
| **DRAFT** | Written spec with ACs, stories, edge cases. Awaiting review. | Passes `--validate` with no warnings on THIS spec | Author → Reviewer |
| **REVIEW** | Independent reviewer has approved the spec's completeness and coherence. | Review approval documented in spec or review artifact | Reviewer |
| **APPROVED** | Spec is locked for implementation. No further scope changes without a new spec. | Status field changed to `✅ Approved`, index regenerated | Vision Manager (paid model) |
| **PLANNED** | Implementation plan exists and has been reviewed. | Plan passes `plans/index_plans.py --validate`, plan references this spec | Plan Author + Plan Reviewer |
| **IMPLEMENTING** | Code/tests exist for some or all ACs. Not all ACs covered. | `make trace` shows partial coverage of this spec's ACs | Code Implementer |
| **DONE** | All ACs have passing tests. Code reviewed. Merged to main. | `make trace` shows 100% AC coverage, `make gate` green, PR merged | Code Reviewer + CI |
| **ARCHIVED** | Spec is fully complete and no longer active. Superseded or part of a completed release. | All ACs covered, spec moved to `specs/archived/` | Any after DONE |

### Advancement Rules

1. **No skipping stages.** STUB → DRAFT requires writing the full spec. DRAFT → REVIEW requires a review pass.
2. **No silent regression.** If a DONE spec gets new ACs, it returns to IMPLEMENTING.
3. **Stubs are intentional.** Boundary stubs (v4/v5 futures) stay as STUB indefinitely — the validator warning is expected, not a defect.
4. **Drafts with warnings are not reviewable.** Clean DRAFT means zero warnings from `index_specs.py --validate` for that spec.
5. **Approved specs with warnings are acceptable** if the warnings are intentional (e.g. S00 charter has no user stories by design, S42-S45 lack edge cases by scope).

---

## 2. Directory Structure

```
specs/
├── TEMPLATE.md              ← Canonical spec template
├── CLOSEOUT_TEMPLATE.md     ← Closeout evidence template
├── README.md                ← How to use specs/
├── index.md                 ← Auto-generated (index_specs.py)
├── index.json               ← Auto-generated (index_specs.py)
│
├── active/                  ← APPROVED and PLANNED specs (locked, ready for implementation)
│   ├── 01-gameplay-loop.md
│   ├── ...
│   └── 67-autonomous-queue-readiness-gate.md
│
├── draft/                   ← DRAFT specs (being written or awaiting review)
│   ├── 46-cloud-deployment-target.md
│   ├── 47-live-neo4j-in-ci.md
│   ├── 48-async-job-runner.md
│   ├── 49-horizontal-scaling.md
│   ├── 68-playtester-client-evolution.md
│   ├── 69-world-based-systems-difficulty-progression.md
│   ├── 70-routes-distances-and-text-map.md
│   └── 71-langfuse-integration.md
│
├── review/                  ← REVIEW stage (post-review, pre-approval)
│   └── (currently empty)
│
├── stubs/                   ← STUB stage (boundary/future placeholders)
│   ├── 18-therapeutic-framework.md
│   ├── 19-crisis-and-content-safety.md
│   ├── 20-story-sharing.md
│   ├── 21-collaborative-writing.md
│   ├── 22-community.md
│   ├── 50-concurrent-universe-loading.md
│   ├── 51-cross-universe-travel-protocol.md
│   ├── 52-nexus-as-special-universe.md
│   ├── 53-nexus-access-rules.md
│   ├── 54-inter-universe-event-substrate.md
│   ├── 55-bleedthrough-propagation-rules.md
│   ├── 56-resonance-correlation-engine.md
│   ├── 57-multi-actor-universe-model.md
│   ├── 58-turn-conflict-resolution.md
│   ├── 59-multiplayer-transport.md
│   ├── 60-crisis-safety-protocol.md
│   ├── 61-therapeutic-framework.md
│   ├── 62-story-sharing.md
│   └── 63-community-and-user-generated-worlds.md
│
├── implementing/            ← IMPLEMENTING stage (partial code coverage)
│   └── (currently empty)
│
├── archived/                ← ARCHIVED stage (complete, superseded)
│   └── (future — DONE specs move here after release closeout)
│
└── (legacy root files)      ← To be relocated during migration
    ├── 00-project-charter.md       → active/
    ├── 01-gameplay-loop.md         → active/
    ├── ... (S01-S45, S64-S67)      → active/
    └── future/                     → stubs/ (contents moved up one level)
```

### Migration Plan

The current flat structure is a legacy of growth. Migration should be done in a single atomic commit:

1. Create `active/`, `draft/`, `review/`, `stubs/`, `implementing/`, `archived/` subdirectories
2. `git mv` each spec into its stage directory
3. Update `specs/index_specs.py` to scan subdirectories (it already handles `future/`)
4. Regenerate `index.md` and `index.json`
5. Run `--validate` and fix any path issues in cross-references

**Do not do this migration yet** — it requires updating the indexer, plan references, and CI. Schedule as a dedicated governance PR after the current S46-S49 + S68-S70 bundle is implemented.

---

## 3. Current Spec → Stage Mapping

### STUB (24 specs)

These are boundary/future stubs. Warnings are expected — do not "fix" by inventing fake ACs.

| Spec | Title | Location |
|---|---|---|
| S18 | Therapeutic Framework | `specs/future/` |
| S19 | Crisis & Content Safety | `specs/future/` |
| S20 | Story Sharing | `specs/future/` |
| S21 | Collaborative Writing | `specs/future/` |
| S22 | Community | `specs/future/` |
| S50 | Concurrent Universe Loading | `specs/` root |
| S51 | Cross-Universe Travel Protocol | `specs/` root |
| S52 | Nexus as Special Universe | `specs/` root |
| S53 | Nexus Access Rules | `specs/` root |
| S54 | Inter-Universe Event Substrate | `specs/` root |
| S55 | Bleedthrough Propagation Rules | `specs/` root |
| S56 | Resonance Correlation Engine | `specs/` root |
| S57 | Multi-Actor Universe Model | `specs/` root |
| S58 | Turn Conflict Resolution | `specs/` root |
| S59 | Multiplayer Transport | `specs/` root |
| S60 | Crisis Safety Protocol | `specs/` root |
| S61 | Therapeutic Framework | `specs/` root |
| S62 | Story Sharing | `specs/` root |
| S63 | Community and User-Generated Worlds | `specs/` root |

### DRAFT — Clean (8 specs)

These pass `--validate` with no warnings. Ready for REVIEW.

| Spec | Title | Has Plan? |
|---|---|---|
| S46 | Cloud Deployment Target | Yes (`s46-s49-production-runtime.md`) |
| S47 | Live Neo4j in CI | Yes (same bundle plan) |
| S48 | Async Job Runner | Yes (same bundle plan) |
| S49 | Horizontal Scaling | Yes (same bundle plan) |
| S68 | Playtester Client Evolution | Yes (`v2_1-playtester-bundle.md`) |
| S69 | World-Based Systems, Difficulty, Progression | Yes (same bundle plan) |
| S70 | Routes, Distances, and Text Map | Yes (same bundle plan) |
| S71 | Langfuse Integration | No |

### DRAFT — Has Warnings (14 specs)

These are S50-S63. They have Gherkin scenarios but no user stories or edge cases. They are functionally boundary stubs that happen to have partial ACs. Reclassify as STUB rather than trying to complete them now.

### APPROVED (37 specs)

S01-S17 (except S12 is "Approved (v2)"), S23-S40, S64-S67. Some have edge-case/story warnings by design (S00, S42-S45).

### APPROVED — Has Plan (most of S01-S45)

Component-level plans exist (`system.md`, `api-and-sessions.md`, `llm-and-pipeline.md`, etc.) but not all are spec-granular.

### PLANNED (0 specs)

No spec has a reviewed, locked implementation plan yet. The S46-S49 and S68-S70 bundle plans are DRAFT plans — they need plan review before specs advance to PLANNED.

### IMPLEMENTING (0 specs)

No spec has partial code coverage tracked by stage.

### DONE (0 specs)

No spec has 100% AC coverage verified by `make trace` and tracked by stage.

---

## 4. S71 Decision

**S71 (Langfuse Integration)** is a 561-line draft spec extending S15 with user/session lifecycle tracing, prompt provenance, and evaluation pipeline integration. It was renumbered from S15-LF to S71 during the portfolio rebase to resolve a duplicate spec ID.

**Decision: Keep as DRAFT. Do not include in the current S46-S49 + S68-S70 implementation bundle.**

Rationale:
- S71 was not part of the session's four priority components (Infrastructure, Systems, Client, Maps)
- It requires Langfuse self-hosted deployment to be stable before implementation
- It has no implementation plan
- Including it would expand scope beyond what the portfolio control plane approved
- It is a well-written spec — it should advance through the pipeline on its own track

**Next step for S71**: After the current bundle is implemented, run S71 through REVIEW → APPROVED → PLANNED → IMPLEMENTING as a standalone lane.

---

## 5. Templates (Not Specs)

These files should move to `docs/` or stay as root-level references in `specs/`:

| File | Current Location | Proposed |
|---|---|---|
| `TEMPLATE.md` | `specs/TEMPLATE.md` | `specs/TEMPLATE.md` (keep as reference) |
| `CLOSEOUT_TEMPLATE.md` | `specs/CLOSEOUT_TEMPLATE.md` | `specs/CLOSEOUT_TEMPLATE.md` (keep as reference) |

---

## 6. Immediate Actions

### Now (this session)

- [x] Commit S48/S49 contradiction patches
- [x] Create this pipeline governance doc
- [ ] Decide: promote S46-S49 bundle plan from DRAFT to REVIEWED (plan review pass)
- [ ] Decide: promote S68-S70 bundle plan from DRAFT to REVIEWED (plan review pass)
- [ ] Move S50-S63 to `stubs/` mental classification (physical move during migration)

### Next Session (implementation)

- [ ] Pick up untracked RED test `tests/unit/world/test_s70_route_read_model.py` for TDD
- [ ] Start with contract-first slice per `v21-playtester-contract-first-slice` pattern
- [ ] Run independent review on S68-S70 (separate from Hermes review — per review discipline)

### Governance PR (after implementation bundle)

- [ ] Migrate specs to pipeline directory structure
- [ ] Update `specs/index_specs.py` for subdirectory scanning
- [ ] Add pipeline stage column to `specs/index.md` table
- [ ] Regenerate indexes

---

## 7. Stage Transition Checklist

When advancing a spec, use this checklist:

### DRAFT → REVIEW

- [ ] Spec passes `uv run python specs/index_specs.py --validate` with zero warnings for THIS spec
- [ ] Independent reviewer (different model than author) has reviewed
- [ ] Review documented in spec or `docs/spec-review-*.md`
- [ ] No blocking findings remain

### REVIEW → APPROVED

- [ ] Vision Manager (paid model) confirms strategic alignment
- [ ] Status updated to `✅ Approved` in spec header and index
- [ ] `specs/index_specs.py` run to regenerate index

### APPROVED → PLANNED

- [ ] Implementation plan exists for this spec (or bundle covering it)
- [ ] Plan passes `plans/index_plans.py --validate`
- [ ] Plan reviewer (different model) has approved
- [ ] Spec header updated with plan reference

### PLANNED → IMPLEMENTING

- [ ] At least one AC has a passing `@pytest.mark.spec` test
- [ ] Branch created for implementation
- [ ] `make trace` confirms partial AC coverage

### IMPLEMENTING → DONE

- [ ] All ACs have passing `@pytest.mark.spec` tests
- [ ] `make trace` shows 100% AC coverage
- [ ] `make gate` green
- [ ] Code reviewed and PR merged
- [ ] Practical application gate evidence captured

### DONE → ARCHIVED

- [ ] All ACs covered and verified
- [ ] Spec moved to `specs/archived/`
- [ ] Index regenerated
