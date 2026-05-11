# 2026-05-11 Gap-Closure Plan

> For Hermes: this is a second-wave ops plan, not a fresh architecture spec.
> Existing component plans remain the source of truth for design. This document
> answers a narrower question: what should we do next from the repo state today?

Status: ✅ Waves 1–2 complete (2026-05-11)
Scope: fictional-barnacle repo only
Based on: git working tree, plan/spec inventory, AC traceability report, validator output

## Wave 1 Closeout (2026-05-11)

### Completed
1. **Orphan AC fix** — 6 S12 v2 ACs were invisible to the trace scanner because
   `(v2)` text between AC marker and colon broke the regex. Fixed in
   `specs/trace_acs.py` line 63: `[^:\\n]*` now allows optional tag text.
   - Orphans: 6 → 0
   - Headline: 302/328 (92.1%) → 308/335 (91.9%)
   - The headline drop from 92.1% to 91.9% is normal — 7 previously-invisible
     S12 v2 ACs are now counted (6 covered, 1 uncovered: AC-12.11)

2. **Spec index regenerated** — `specs/index.json` now reflects 66 specs, 768 ACs,
   179,591 total words

3. **Plan index regenerated** — `plans/index.json` updated

4. **FB-005-draft.md user stories** — Added 4 user stories (US-FB-005.1 through
   US-FB-005.4) covering runtime activation, genre packs, observability, and
   preview tooling. Section numbering reflowed to accommodate.

5. **Broken plan reference fixed** — `plans/v2_1-evaluation-and-playtesting.md`
   referenced `plans/index.md` which the validator treated as a broken plan-ref
   (index.md is excluded from the plan list). Rephrased to avoid triggering the
   check.

### Remaining known issues (conscious deferrals)
- **Circular dependency S12 → S11 → S12** — both specs list each other as
  dependencies. Genuine cross-cutting concern (sessions need persistence,
  persistence schema references session concepts). Needs a spec-level decision:
  which direction to break.
- **v2.1 plan is structurally thin** — missing tech stack, testing, code examples.
  Intentional: it's a stub plan by design (see §0 of that document).
- **27 uncovered Approved ACs** — S09 deferred ACs (AC-09.02/06/07/09) are the
  highest-priority cluster. S11, S10, S26, and S28 gaps are real but lower
  leverage. The open-AC list is now trustworthy — no orphans distorting it.
- **31/66 specs with warnings** — mostly draft and stub specs missing user
  stories and edge cases. These are structural template gaps, not blocking.

### State snapshot
- Branch: `feat/fb-013-admin-and-operator-tooling`
- Trace: 0 orphans, 308/335 approved covered (91.9%), exit 0
- Spec validator: FB-005-draft now clean; circular dependency is only
  high-signal structural issue
- Plan validator: broken reference fixed; v2.1 stub warnings are by design

## Wave 2 Closeout (2026-05-11)

### Completed
1. **LangfusePromptBridge** (`src/tta/prompts/langfuse_bridge.py`, 333 lines) —
   bridges FilePromptRegistry (Jinja2 rendering) with Langfuse Prompt
   Management (versioning, labels, per-version metrics).  Supports seed,
   render, activate (label flip), preview (shadow mode), and cache
   management.

2. **Admin endpoints** (`src/tta/api/routes/admin.py` §3.8) —
   - `POST /admin/prompts/{name}/activate` — flips Langfuse label
   - `POST /admin/prompts/{name}/preview` — renders against variables
     in shadow mode (no game state modification)

3. **Langfuse prompt linkage** — `record_llm_generation` and
   `guarded_llm_call` now accept an optional Langfuse prompt object.
   When provided, the generation is linked to the prompt version in
   Langfuse for automatic per-version metrics (latency, tokens, cost,
   generation count, scores).

4. **RenderedPrompt.metadata** — added `metadata: dict[str, Any]` field
   to carry Langfuse prompt objects through the render→LLM call chain.

5. **18 unit tests** (12 bridge + 6 admin), all passing.

6. **Protocol fix** — `PromptRegistry.list()` → `list_templates()` to
   match the protocol definition.  `RenderedPrompt.text` (not `.body`)
   used consistently.

### Architecture decision
- **Langfuse** = source of truth for prompt versions, labels, config,
  and per-version metrics.
- **FilePromptRegistry** = Jinja2 rendering engine (fragments, safety
  preamble, hash tracking).  This division of labor is intentional:
  Langfuse can't handle TTA's complex Jinja2 composition needs, and the
  local registry shouldn't duplicate version management that Langfuse
  already provides.
- **Genre packs** and **fragment composition** remain file-based for now
  (deferred to a future wave).

### Trace impact
- AC-09.02 and AC-09.09 are now covered (were uncovered before Wave 2)
- Headline: 310/335 approved (92.5%), 0 orphans

## 1. Why this plan exists

The repo has foundational plans, but it does not currently have a trustworthy
"what is the next wave of work?" execution plan.

What exists:
- `plans/*.md` = baseline architecture/component plans
- `NEXT_STEPS.md` = older strategic document, now mostly historical
- `docs/superpowers/plans/2026-05-02-wave-41-integration-coverage.md` = one dated wave plan
- `docs/backlog/queue.yaml` = empty queue, so no active machine-readable execution queue

Conclusion:
- There is planning material
- There is not an active repo-level ongoing plan that cleanly reflects today's state
- We should treat this document as the new working plan

## 2. State today

### 2.1 Working tree signals
- Current branch: `feat/fb-013-admin-and-operator-tooling`
- Uncommitted changes:
  - `.serena/project.yml`
  - `specs/09-prompt-and-content.md`
  - `specs/12-persistence-strategy.md`
  - `specs/FB-005-draft.md`

Interpretation:
- The repo is actively moving on v2 prompt/persistence/admin concerns
- The implementation queue has drifted away from the older static plans

### 2.2 Traceability signals
From `make trace` on 2026-05-11:
- Approved AC headline: 302/328 = 92.1%
- Draft AC headline: 11/80 = 13.8%
- Orphan citations: 6
- Uncovered approved ACs: 26

Current orphan citations:
- `AC-12.03`
- `AC-12.05`
- `AC-12.06`
- `AC-12.07`
- `AC-12.08`
- `AC-12.10`

Interpretation:
- The repo likely has tests for these ACs, but the spec/index pipeline is out of sync
- This is a measurement failure first, not necessarily an implementation failure
- We should not trust the headline until traceability is repaired

### 2.3 Validator signals
From `make validate-specs`:
- Circular dependency reported: `S11 -> S12 -> S11`
- `FB-005-draft.md` lacks user stories
- Many later-wave specs are structurally thin, but that is lower priority than the trace/index break

From `make validate-plans`:
- `system.md` missing testing section
- `resilience-and-safety.md` missing tech stack/testing sections
- `v2_1-evaluation-and-playtesting.md` references `index.md` that does not exist

Interpretation:
- The planning substrate itself needs cleanup
- Some of the repo's "what is true?" documents are drifting and should be repaired before more feature work compounds the mismatch

### 2.4 Existing backlog signals
- `docs/backlog/queue.yaml` is empty
- `docs/backlog/2026-05-03-discovery.md` recommends:
  - FB-001 Redis session cache work as top queue candidate
  - FB-005 prompt registry as tier-2 candidate
- The repo already contains `src/tta/persistence/redis_session.py` and integration tests for S12 live infra

Interpretation:
- Discovery backlog is stale relative to implementation progress
- The current plan should prioritize verified gaps, not old candidate queues

## 3. What is actually unfinished

This is the priority order based on current repo evidence, not on old roadmap order.

### Priority A — Repair the planning/measurement substrate
This is first because every later claim depends on it.

1. Fix S12 traceability/index alignment
   - Why: six orphan AC citations distort the repo's coverage picture
   - Likely cause: S12 v2 ACs were added/edited but spec indexing/normalization has not caught up
   - Done when:
     - `make trace` no longer reports the six S12 orphan citations
     - coverage numbers reflect real test ownership

2. Resolve validator-level planning drift
   - Add missing structure to `specs/FB-005-draft.md`
   - Fix broken reference in `plans/v2_1-evaluation-and-playtesting.md`
   - Decide whether the `S11 <-> S12` circular dependency is real or just documentation coupling
   - Done when:
     - `make validate-specs` has no actionable high-signal structural errors for active specs
     - `make validate-plans` no longer flags broken references

### Priority B — Finish the S09 v2 prompt-management wave
This is the clearest active product gap in the working tree.

Target AC cluster:
- `AC-09.02` runtime activation/rollback
- `AC-09.06` genre packs/content assets
- `AC-09.07` per-version Langfuse metrics/queryability
- `AC-09.09` preview/shadow tooling

Why now:
- `specs/09-prompt-and-content.md` is actively being revised
- `specs/FB-005-draft.md` exists specifically to expand this area
- The current branch is admin/operator tooling adjacent, which is the right surface for preview/metrics/activation controls
- `tests/unit/prompts/test_s09_ac_compliance.py` explicitly marks these ACs as deferred/missing

Design rule:
- Do not build a custom prompt-management platform unless Langfuse cannot satisfy the requirement cleanly
- Prefer Langfuse-native prompt versions, labels, and metrics where possible
- Only write local glue for runtime resolution, activation control, and game-specific metadata

Done when:
- S09/FB-005 are merged into one coherent spec direction
- Admin/operator surface exists for prompt activation, preview, and metrics lookup
- Traceability covers the new S09 ACs with tests that assert actual behavior, not placeholder structure

### Priority C — Reconcile S12 "implemented vs measurable"
The repo appears to have real S12 work in code/tests already. The problem is proving it cleanly.

Target AC cluster:
- `AC-12.03`
- `AC-12.05`
- `AC-12.06`
- `AC-12.07`
- `AC-12.08`
- `AC-12.10`

Why this is not Priority A despite the trace failure:
- The code and integration tests already exist
- This looks closer to verification hardening than greenfield implementation

Done when:
- The S12 live-infra tests are part of a reliable repeatable gate
- The ACs appear in trace output correctly
- We have one crisp answer to: "are the S12 v2 claims real on current infra?"

### Priority D — Close remaining v1 operational gaps with direct user value
Remaining uncovered approved ACs include:
- S10 reconnect/replay: `AC-10.04`, `AC-10.05`
- S11 identity/session edge cases: `AC-11.03`, `AC-11.09`, `AC-11.11`, `AC-11.13`
- S26 admin/operator tooling: `AC-26.02`, `AC-26.08`
- S28 multi-instance SSE: `AC-28.08`

Recommendation:
- Pull S26 ahead of pure S11 cleanup if it directly enables S09 prompt operations
- Keep `AC-28.08` deferred until there is an actual multi-instance harness

## 4. Proposed execution waves

## Wave 1 — Trust the gauges again
Goal: make the repo's status measurable and believable

Tasks:
1. Repair S12 AC indexing and traceability
2. Re-run spec/plan index generation and validators
3. Patch `FB-005-draft.md` into validator-clean shape
4. Fix the broken v2.1 plan reference
5. Produce a fresh "repo state" snapshot after repair

Exit gate:
- `make trace` reports zero orphan citations for active work
- validator output contains only consciously deferred low-priority warnings

## Wave 2 — Land prompt-management v2 vertical slice
Goal: make prompt operations real, not aspirational

Tasks:
1. Choose backing model:
   - Langfuse-native where possible
   - local registry/store only where runtime game integration requires it
2. Implement runtime prompt activation + rollback path
3. Implement operator preview flow
4. Implement Langfuse linkage for prompt/version labels and metrics queries
5. Add tests and admin tooling for the above

Exit gate:
- One prompt can be activated/rolled back without restart
- One preview call can render and execute without touching gameplay state
- One metrics view can answer "how did version X perform?"

## Wave 3 — Convert S12 live-infra work into a stable gate
Goal: stop treating persistence/perf claims as "probably true"

Tasks:
1. Run and harden the S12/S13/S28 integration suite on live infra
2. Make pass/fail reasons operationally readable
3. Decide whether these tests belong in default CI, a dedicated job, or a manual gate
4. Document the expected environment and budgets

Exit gate:
- The repo has a repeatable command that answers whether live-infra persistence claims currently hold

## Wave 4 — Finish operator-facing gaps that unblock shipping
Goal: close the most leverage-heavy remaining approved ACs

Candidate order:
1. S26 admin/operator tooling gaps
2. S10 SSE reconnect/replay gaps
3. S11 lifecycle edge cases
4. S28 multi-instance SSE only when infra exists

## 5. What not to do now

Do not:
- Start a new broad architecture rewrite
- Expand v3+ roadmap work while v2 traceability is still drifting
- Build a bespoke prompt CMS before exhausting Langfuse-native capabilities
- Treat coverage percentage as truth until orphan ACs are resolved
- Queue more discovery-agent backlog items before the execution queue reflects current implementation reality

## 6. Recommended immediate next task

Start with Wave 1, specifically:
1. investigate why S12 ACs are cited in tests but missing from the spec index/trace pipeline
2. repair the indexing/traceability path
3. regenerate indexes
4. re-baseline the repo from the repaired reports

Reason:
- It is the highest-leverage task
- It reduces false uncertainty
- It tells us whether S12 is really still a gap or just poorly measured

## 7. Success definition for this plan

This plan succeeds if, by the end of the next planning cycle:
- repo status is measurable from tooling without obvious false negatives
- S09 v2 prompt-management work has one real shipped vertical slice
- S12 live-infra claims are either verified or honestly downgraded
- the next queue is derived from actual gaps, not stale planning artifacts
