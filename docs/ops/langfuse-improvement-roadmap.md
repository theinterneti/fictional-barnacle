# Langfuse Improvement Roadmap

Date: 2026-05-06
Owner: Adam + Hermes
Status: Proposed / ready for execution

## Goal / Problem Statement

Turn Langfuse into the shared control plane for Hermes, free-model-router, and repo-native agent workflows so we can answer, for any important run:
- what prompt/version/label was used
- what model/provider handled it
- what repo/branch/PR/task it belonged to
- how it performed
- whether quality improved or regressed

Today the stack already emits meaningful telemetry, but it is fragmented:
- Hermes traces are active in project `hermes-traces`
- free-model-router is heavily active in project `cmorfd4n30007sl02ok5c7pe6`
- Langfuse prompt inventory currently contains only 5 prompts, all under `free-model-router/*`
- fictional-barnacle has good local prompt metadata (`template_id`, `template_version`, `fragment_versions`, `prompt_hash`) but that metadata is not yet flowing into Langfuse generations from the live pipeline
- fictional-barnacle evaluation exports scores to Langfuse by `session_id`, but datasets/experiments/prompt-promotion workflows are not yet first-class
- project topology is messy: duplicate/overlapping projects exist, and at least one project appears provisioned but not materially used

The objective is not just “more Langfuse usage”. The objective is a clean, release-safe, eval-backed telemetry model that spans Hermes orchestration, router decisions, and repo workflows.

## Current Audit Snapshot

### Live Langfuse projects

- `hermes-traces` — active Hermes project
- `cmorfd4n30007sl02ok5c7pe6` — active router-heavy project; recent traces are mostly `smart-router-chat`
- `tta-dev` — active historical/dev traces
- `cmonj12g70006guxy9z6qo25g` / `TTA` — provisioned project, not visibly active in current ClickHouse summary
- `cmou7oo1u0003sl02d3x3fuwn` / `free model router` — provisioned project, not visibly active in current ClickHouse summary

### Current prompt inventory

Langfuse currently contains 5 prompts:
- `free-model-router/classifier`
- `free-model-router/comparison-judge`
- `free-model-router/llm-judge`
- `free-model-router/task-taxonomy`
- `Evaluator`

This is a good start for router governance, but it is not yet a platform-wide prompt control plane.

### Hermes state

Evidence from `~/.hermes/logs/agent.log` shows:
- historical OTLP HTTP 401 credential failures on 2026-05-05
- current successful trace creation on 2026-05-05 and 2026-05-06
- recent ClickHouse data confirms Hermes traces and observations are present in `hermes-traces`

Conclusion:
- Hermes is meaningfully integrated
- but historical credential drift means we should treat runtime health as “working now, previously mixed”, not “permanently solved”

### free-model-router state

Code and storage confirm:
- classifier prompt is fetched from Langfuse production label
- router opens Langfuse traces with optional `sessionId`
- router attaches judge verdict scores at trace level via `scoreJudgeVerdicts(...)`
- router propagates `X-Langfuse-Trace-Id`
- router project is extremely active in ClickHouse

Nuance:
- low-level OTEL / API-noise traces can muddy project dashboards
- `attachJudgeScores(...)` exists for generation-level scores but is not yet the primary visible path

### fictional-barnacle state

The repo already has strong local foundations:
- Langfuse client initialization is wired in app startup
- prompt rendering produces `template_id`, `template_version`, `fragment_versions`, and `prompt_hash`
- observability code can record `prompt_id`, `prompt_version`, `fragment_versions`, and `prompt_hash` on Langfuse generations
- evaluation pipeline ships category scores to Langfuse using `session_id`

Important gap:
- `record_llm_generation(...)` supports prompt provenance fields, but `llm_guard.py` does not currently pass them through from rendered prompts
- this means barnacle has provenance-ready plumbing but not end-to-end prompt lineage in live Langfuse traces

## Key Design Decisions

1. Keep separate runtime projects, but rationalize them
- Hermes, router, and repo-app traces should not be collapsed into one giant project
- We want clean dashboards and project-scoped prompt inventories
- We do want shared naming, metadata, and promotion policy across projects

2. Treat prompts, traces, and evals as one system
- Prompt management without trace linkage is incomplete
- Tracing without evals is passive observability
- Evals without prompt/version provenance are hard to trust

3. Make session/work-item identity first-class
- Session IDs should map to a real work unit: PR, kanban card, issue, run, or player session
- Every important trace should carry enough metadata to join back to repo work

4. Use labels as deploy artifacts
- `dev` = experimentation
- `staging` = canary
- `production` = live path
- no critical path should use unlabelled/latest fetches

5. Start with provenance before sophistication
- Before adding fancy experiments and dashboards, fix prompt/version/session metadata on live traces
- This gives immediate debugging value and makes later eval work reliable

## Target Architecture / Flow

### Hermes / router / repo telemetry contract

For every important trace/generation, capture:
- `service`
- `repo`
- `environment`
- `branch`
- `commit_sha`
- `pr_number` or `task_id`
- `session_id`
- `user_id` or pseudonymous actor id
- `agent_role`
- `provider`
- `model`
- `prompt_name`
- `prompt_version`
- `prompt_label`
- `prompt_hash`
- `outcome`

### Prompt lifecycle

Author/edit prompt -> publish version in Langfuse -> assign `dev` or `staging` -> canary on representative work -> compare evals/quality/cost/latency -> promote `production` label -> traces show exact version used -> rollback by label if needed

### Evaluation lifecycle

Real runs and curated examples -> dataset/golden set -> experiments against prompt/model variants -> automated evaluator scores + manual review for misses -> promotion gate -> ongoing dashboarding

## Scoring / Success Criteria

We should consider the Langfuse upgrade successful when all of the following are true:

1. Trace lineage
- >= 95% of important production traces have usable session/work-item metadata
- >= 95% of important LLM generations show prompt identity/version details

2. Prompt governance
- all critical prompts live in Langfuse
- all critical fetches use labels (`staging`/`production`), not `latest`

3. Evaluation coverage
- router has at least one regression dataset and one promotion gate
- each major repo workflow has at least one evaluator family
- prompt promotions are experiment-backed rather than intuition-only

4. Operational health
- no recurring exporter/auth drift for Hermes
- storage growth and backups are documented and monitored
- dashboards distinguish semantic traces from infra noise

## Temporal Horizons

### Horizon 1: 0-2 weeks — Foundation

Focus:
- clean project map
- standard metadata contract
- end-to-end prompt provenance in barnacle
- fix obvious project/prompt topology confusion

Deliverables:
- project inventory + target ownership map
- metadata schema doc
- barnacle prompt provenance on live generations
- router/Hermes project naming cleanup plan

### Horizon 2: 2-6 weeks — Governance and quality

Focus:
- prompt label workflow
- router datasets and experiments
- repo-specific prompt families
- canary and rollback operationalization

Deliverables:
- dev/staging/production label discipline
- first router regression dataset
- first experiment-based prompt promotion
- repo dashboards for quality/cost/latency

### Horizon 3: 6-12 weeks — Platformization

Focus:
- per-repo scorecards
- unified release reporting
- mature self-host operations
- manual annotation + review loop

Deliverables:
- shared scorecard format across repos
- health/retention/backups docs + checks
- periodic eval cadence
- incident-style rollback history for prompt regressions

## Phase Plan

## Phase 1 — Rationalize project topology

Problem:
- project names and actual usage do not cleanly line up
- prompts, traces, and runtime ownership are harder to reason about than they should be

Actions:
- inventory every active Langfuse project, API key, and owning runtime
- choose the canonical project for:
  - Hermes runtime
  - free-model-router runtime
  - fictional-barnacle / TTA app traces
- decide whether to retire or repurpose low/no-traffic projects
- document prompt ownership boundaries per project

Output:
- one-page project map with owners, purpose, and retention expectations

## Phase 2 — Standardize metadata and provenance

Problem:
- trace payloads do not yet consistently answer “what work was this?”

Actions:
- define a shared metadata schema for Hermes, router, and repo apps
- standardize `session_id` semantics by workflow
- ensure prompt identity and version fields appear in every important generation
- bind repo/branch/commit/task metadata where available

Output:
- shared telemetry contract doc
- repo-specific implementation tasks for each runtime

## Phase 3 — Make fictional-barnacle prompt lineage real

Problem:
- barnacle already computes prompt metadata but does not fully emit it to Langfuse during live guarded calls

Actions:
- thread rendered prompt metadata through turn-processing stages into `record_llm_generation(...)`
- ensure session/turn/correlation IDs are stable and queryable in Langfuse
- verify live traces show `template_id`, `template_version`, `fragment_versions`, and `prompt_hash`
- add tests for provenance propagation

Output:
- first repo with reliable end-to-end prompt provenance
- reproducible debug path from trace -> prompt asset -> code path

## Phase 4 — Upgrade router prompt/eval governance

Problem:
- router uses Langfuse well, but prompt promotion and experiments are still light

Actions:
- create staging/canary discipline for router prompts
- add dataset for classifier and comparison-judge failures
- compare judge prompt versions before promotion
- promote generation-level scoring where useful, not just trace-level scores

Output:
- eval-backed router prompt promotions
- cleaner judge-quality visibility

## Phase 5 — Bring Hermes prompt management under Langfuse control

Problem:
- Hermes traces are active, but Langfuse prompt management is not yet the obvious source of truth for orchestration prompts

Actions:
- identify stable Hermes prompts worth externalizing first
- map each to a Langfuse prompt naming convention
- adopt `staging` / `production` labels
- ensure Hermes traces record prompt identity/version consistently

Output:
- versioned Hermes prompt governance with rollback path

## Phase 6 — Make evals and experiments a release gate

Problem:
- Langfuse stores traces and some scores, but is not yet driving promotion decisions

Actions:
- curate datasets from real failures and representative successful runs
- create experiment comparisons for prompt/model changes
- define pass/fail promotion rules per workflow
- use manual review for high-value false positives and regressions

Output:
- prompt/model changes become auditable, comparable, and rollbackable

## Phase 7 — Harden self-host operations

Problem:
- as usage grows, storage, retention, and observability hygiene become mandatory

Actions:
- define retention/TTL policy for old traces and observations
- document backup/restore for Postgres, ClickHouse, and object storage
- add health checks for ingestion, queue depth, disk growth, and slow-query symptoms
- document how to distinguish semantic trace health from OTEL noise

Output:
- boring, supportable Langfuse ops

## First Implementation Slice (execute next)

### Slice name
Barnacle prompt provenance MVP

### Why this first
This is the highest-leverage next move because:
- the repo already has the right local metadata
- the Langfuse emitter already supports the needed fields
- the missing work is mostly plumbing and tests, not architecture invention
- success immediately makes traces far more useful for debugging and evaluation

### Slice goal
Make fictional-barnacle live Langfuse generations reliably show:
- prompt/template id
- prompt/template version
- prompt hash
- fragment versions
- session/turn/correlation linkage

### Expected code areas
- `src/tta/pipeline/llm_guard.py`
- `src/tta/pipeline/stages/understand.py`
- `src/tta/pipeline/stages/generate.py`
- any prompt-carrying pipeline types/models used between render and guarded call
- `src/tta/observability/langfuse.py`
- tests under `tests/unit/observability/` and/or pipeline compliance tests

### Acceptance criteria
- a rendered prompt’s provenance fields are passed into `record_llm_generation(...)`
- Langfuse generation metadata contains provenance for both classification and generation flows
- session/turn IDs remain intact
- tests fail before change and pass after change
- docs note the new metadata contract

### Verification
- unit tests for provenance propagation
- targeted live smoke trace in Langfuse
- confirm metadata appears on recent generations in the correct project

### Estimated build time
- implementation: 1 focused session
- verification and trace smoke test: 1 focused session

## Phase-1 backlog after the MVP slice

1. Barnacle prompt provenance MVP
2. Project topology cleanup doc
3. Shared metadata contract for Hermes/router/repos
4. Router prompt-governance dataset seed
5. Hermes prompt externalization shortlist

## Gates and Failure Modes

### Gates
- no critical flow should regress if Langfuse is unavailable
- no prompt promotion without rollback target
- no production prompt fetch from `latest`
- no ambiguous project ownership after topology cleanup

### Failure modes to watch
- credential drift between shell env and long-lived services
- project sprawl causing prompts and traces to land in different places than intended
- dashboards polluted by low-value OTEL noise
- score export keyed to the wrong trace/session identifier
- false confidence from “prompt exists in Langfuse” without runtime linkage

## Open Questions for Human Review

1. Do we want a dedicated Langfuse project for fictional-barnacle/TTA production traces, or should `tta-dev` evolve into the canonical repo project?
2. Should router prompts remain in the router project only, or do we want a platform-shared prompt namespace pattern across projects?
3. Which Hermes prompts are stable enough to externalize first without creating churn?
4. Do we want experiments and datasets centralized in one project, or kept next to each runtime’s traces?

## Risk Register

- Low: Barnacle provenance plumbing
- Medium: project consolidation / migration confusion
- Medium: prompt promotion process introduces temporary operator overhead
- Medium: dataset quality is poor if we do not curate examples carefully
- High: storage/retention issues if router traffic keeps growing without policy
- High: false attribution if session IDs are not standardized before dashboards and evals spread

## Immediate Recommendation

Start with Barnacle prompt provenance MVP, then do project topology cleanup immediately after. That sequence gives us:
- one concrete repo win
- a reusable metadata pattern
- better evidence for how to clean up the rest of the stack

## Estimated Overall Program Time

- Foundation and first real wins: 1-2 weeks
- Prompt governance + router evals: 2-6 weeks
- Full platform rollout and ops hardening: 6-12 weeks
