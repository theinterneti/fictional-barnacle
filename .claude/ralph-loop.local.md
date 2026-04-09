---
active: true
iteration: 2
session_id:
max_iterations: 25
completion_promise: "WAVE 11 COMPLETE"
started_at: "2026-04-09T00:00:00Z"
---

You are implementing Wave 11 of the TTA (Therapeutic Text Adventure) rebuild.

## Context
- Repo: ~/Repos/fictional-barnacle
- Wave 10 is COMPLETE (content moderation, game management, auto-save/resume)
- Quality gate: `make quality` must pass (ruff + pyright) — run it after every change
- Tests: `make test` — fix failures you introduce
- Specs: `specs/26-admin-and-operator-tooling.md` and `specs/28-performance-and-scaling.md`
- Plans: `plans/ops.md`
- Convention: Conventional Commits, SDD workflow — spec ACs are source of truth

## Your Task
Implement Wave 11 iteratively. Each iteration, pick the NEXT unimplemented piece:

**Priority order:**
1. S26 Admin API — admin endpoints (player management, moderation queue review, audit log query)
2. S26 Moderation queue — admin UI for reviewing flagged content
3. S28 Performance — LLM semaphore, DB connection pool tuning, latency budget middleware
4. CI improvements — ensure integration tests run in CI (check .github/workflows/)

## Each Iteration
1. Read the relevant spec section before touching any code
2. Check git log to see what was done in previous iterations
3. Implement the next unfinished piece
4. Run `make quality` — fix any issues before continuing
5. Commit with a conventional commit message

## Completion Criteria
Output <promise>WAVE 11 COMPLETE</promise> only when ALL of the following are true:
- S26 admin endpoints exist and match spec ACs
- S28 performance controls (semaphore, pool, latency middleware) are in place
- `make quality` passes clean
- All new code has corresponding tests
