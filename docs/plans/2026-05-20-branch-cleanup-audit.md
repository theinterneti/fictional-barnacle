# Branch Cleanup Audit — 2026-05-20

Baseline:
- main = 231c04f and matches origin/main
- worktree is clean on main

## 1. Salvage Branch Audit

Branch:
- wip/salvage-dirty-main-2026-05-20-093445
- tip = d6582b8
- relationship to main = ahead 6, behind 0
- relationship to safety branch = one extra WIP snapshot commit on top of the 5 preserved local-main commits

Safety parent branch:
- safety/main-2026-05-20-093312
- tip = dc78fe5
- unique commits vs main:
  1. 3721998 refactor(llm): replace LiteLLM with direct FMR client
  2. feec7b0 fix(genesis): sanitize output, improve name heuristic, add force-advance
  3. fe64d0e docs(vision): v2.1 architecture review and code audit
  4. 5bce47b docs(specs): v2.1 content richness cluster — S51-S54
  5. dc78fe5 docs(plan): S51 technical plan — procedural location generation

The salvage WIP commit is not a coherent PR. It contains at least five mixed buckets:

### Bucket A — FMR / rate-limit / playtester pressure work
Files:
- src/tta/llm/fmr_client.py
- src/tta/llm/rate_limiter.py
- src/tta/llm/__init__.py
- src/tta/jobs/jobs.py
- src/tta/playtest/agent.py
- tests/unit/jobs/test_playtester_job_rate_limit.py
- tests/unit/llm/test_rate_limit_budget.py
- tests/unit/playtest/test_playtester_rate_limit.py
- tests/unit/test_app_rate_limit_contract.py

Assessment:
- High value.
- Most aligned with current v2.1 direction.
- Candidate to salvage first onto a fresh feature branch.

### Bucket B — procedural quests / content richness scaffolding
Files:
- plans/s52-dynamic-quests.md
- src/tta/quests/*
- tests/unit/quests/*
- tests/unit/test_app_quest_bootstrap_contract.py

Assessment:
- Large isolated feature slice.
- Potentially worth preserving, but not the next thing unless content richness is gating the next version.
- Should be split into its own branch, not mixed with FMR work.

### Bucket C — genesis / structured output / auth / API edits
Files:
- src/tta/api/app.py
- src/tta/api/errors.py
- src/tta/api/routes/auth.py
- src/tta/api/routes/games.py
- src/tta/api/routes/players.py
- src/tta/auth/jwt.py
- src/tta/genesis/genesis_v2.py
- src/tta/genesis/structured_output.py
- src/tta/lifecycle/cleanup.py
- src/tta/privacy/purge.py
- tests/unit/api/test_app.py
- tests/unit/api/test_errors.py
- tests/unit/api/test_games.py
- tests/unit/api/test_genesis_integration.py
- tests/unit/genesis/test_genesis_v2.py
- tests/unit/moderation/test_ac24_09_recording.py
- tests/unit/test_ac24_09_deferred_contract.py
- tests/unit/test_v2_deferred_contract.py
- tests/unit/v2_deferred_coverage.py

Assessment:
- Mixed bag.
- Needs re-audit against specs before resurrection.
- Not safe to cherry-pick wholesale.

### Bucket D — planning/docs/index copies
Files:
- docs/plans/2026-05-20-fictional-barnacle-next-steps.md
- specs/index.json
- index.json
- index.md

Assessment:
- Keep the plan doc.
- The root-level index.json and index.md copies look accidental/noisy until proven otherwise.
- Do not revive those copies blindly.

### Bucket E — generated/ephemeral artifact
Files:
- data/genesis_v2_smoke_results.json

Assessment:
- Do not carry forward by default.
- Re-generate when needed.

Recommended salvage order:
1. Bucket A (FMR/rate-limit/playtester)
2. Keep plan doc from Bucket D
3. Re-evaluate Bucket B separately
4. Re-audit Bucket C file-by-file
5. Drop Bucket E and likely the root index copies

## 2. Worktree Audit

Registered worktrees:
- /mnt/data/Repos/fictional-barnacle -> main (clean)
- /home/theinterneti/.config/superpowers/worktrees/fictional-barnacle/wave-30/production-hardening -> clean
- /home/theinterneti/.config/superpowers/worktrees/fictional-barnacle/wave-32/save-load -> clean
- /home/theinterneti/Repos/fictional-barnacle/.worktrees/wave-41 -> DIRTY
- /mnt/data/Repos/fictional-barnacle/.worktrees/t_ba947364 -> clean

Dirty worktree warning:
- branch wave-41/integration-coverage has uncommitted edits in:
  - docker-compose.test.yml
  - src/tta/llm/__init__.py
  - tests/fixtures/neo4j/world_full.cypher
  - tests/fixtures/neo4j/world_large.cypher
  - tests/integration/conftest.py
  - tests/integration/test_s13_neo4j_integration.py

Implication:
- There is active or abandoned dirty state outside the main worktree.
- Do not prune that worktree/branch until those edits are either committed, stashed, or explicitly discarded.

## 3. Branch Audit

### Keep now
- main
- safety/main-2026-05-20-093312
- wip/salvage-dirty-main-2026-05-20-093445
- wave-41/integration-coverage (because its linked worktree is dirty)
- any branch with a live external upstream and a clean matching tip, until we intentionally prune them

### Safe immediate prune candidates
These are already fully merged into main or redundant anchors:
- t_ba947364
- wave-40/fix-s26-test-mocks

### Likely stale local-only branches with no worktree and substantial drift from main
Review, then prune if no active need:
- feat/wave-0-bootstrap
- feat/wave-10-review-debt
- wave-13/metrics-and-compliance
- wave-16/character-commands-lifecycle
- wave-29/narrative-and-character-quality
- wave-37/s01-s02-compliance
- tmp-rebase-170

Why these are suspect:
- no upstream or orphaned purpose
- behind main by 33–129 commits
- not merged into main
- likely historical residue rather than active delivery lanes

### Branch needing special attention
- wave-40/status-aware-coverage
  - upstream is gone
  - local branch still exists
  - ahead 2 / behind 18 relative to main fallback
  - do not auto-delete without deciding whether those 2 commits matter

### Active-looking local-only branches worth preserving until inspected
- feat/multi-backend-llm-fmr
- feat/rate-limit-budget
- feat/arq-playtester
- feat/htmx-ui
- feat/v2.0-gate-closure

Reason:
- They are closer to current concerns and may contain reusable work related to routing, UI, and playtesting.

## 4. Recommended Next Actions

### Immediate hygiene
1. Resolve or snapshot the dirty wave-41 worktree.
2. Delete obvious junk after confirmation:
   - t_ba947364
   - wave-40/fix-s26-test-mocks
3. Preserve safety + salvage branches until the useful commits are rehomed.

### Productive next branch
Create a fresh branch from clean main for the next real work item:
- feat/v2.1-prompt-provenance-metrics

Start there with:
1. prompt provenance verification
2. Langfuse per-version observability/queryability
3. measured FMR-backed playtester runs

### Salvage strategy
Do not continue development on the salvage branch.
Instead:
1. mine Bucket A into a clean new branch
2. mine Bucket B only if content-richness is promoted into the near-term gate
3. leave Bucket C for a separate audit

## 5. Recommended Deletion Order Once Confirmed

Phase 1:
- delete t_ba947364 branch and remove its worktree
- delete wave-40/fix-s26-test-mocks

Phase 2:
- either commit/stash/discard wave-41 dirty worktree, then decide whether to keep the branch

Phase 3:
- prune stale drifted branches one-by-one after a quick `git log main..branch --oneline` review

## Bottom line
The repo trunk is clean now, but the repository is still carrying historical branch debt and one dirty side worktree. The salvage branch contains useful material, but only after splitting. The next real delivery branch should be built from clean main and focused on prompt provenance + Langfuse metrics + measured FMR playtesting, not resumed from the salvage snapshot.
