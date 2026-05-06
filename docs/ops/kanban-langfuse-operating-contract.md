# Kanban + Langfuse Operating Contract

## Board topology
- global-deps: cross-project dependency tracking only
- global-systems: non-repo/system work (Hermes, observability, infra)
- proj:<repo-slug>: execution board per repo

## Cross-board policy (Option B)
- global-deps tracks blockers/dependencies
- project boards execute tasks
- use bridge tasks to reflect dependency state across boards

## Model tiers
- Tier A (critical): codex 5.4, codex 5.3, sonnet fallback
- Tier B (normal): codex 5.3, sonnet, limited free-router fallback
- Tier C (aux): free-model-router aliases only

Escalate to Tier A when:
- same task fails twice
- flaky CI repeats twice
- security/auth/payment/migrations
- conflict resolution on high-churn branches

## Task sizing
Every task should be:
- 1 acceptance criterion
- ideally 1 file cluster
- target runtime 2–15 minutes

## Mandatory done contract
Worker must return:
- files changed (absolute paths)
- commit SHA
- command exit codes
- test tail/status tail
- CI URL/run ID when applicable

Orchestrator must verify before completion:
- file exists/changed
- commit exists
- tests pass
- CI state accurate

## PR gate flow
1. Automated review
2. Orchestrator fixes
3. CI/CD stabilization
4. Rebase + resolve conflicts
5. Re-run required CI
6. Merge-delta review
7. Ready-to-merge handoff to Adam

## Langfuse prompt governance
- Production prompt source of truth: Langfuse
- Labels: dev, staging, production
- Production runs fetch production label only
- No unlabelled/latest fetch in critical flows
- Rollback by label/version first, then code changes if needed

## Required run metadata
Capture per run:
- board/task id
- profile
- model/provider
- prompt name
- prompt version/label
- outcome (pass/fail/retry/escalated)
