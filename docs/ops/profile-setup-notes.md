# Profile Setup Notes (v1)

## Global conventions

- Board topology:
  - global-deps: cross-project dependency tracking only
  - global-systems: non-repo/system execution (Hermes, observability, infra)
  - proj:<repo-slug>: execution board per repository
- Cross-board policy:
  - Option B: global-deps tracks dependencies; project boards execute tasks
- Model tier policy:
  - Tier A (reliable/critical): codex 5.4, codex 5.3, sonnet fallback
  - Tier B (normal): codex 5.3, sonnet, constrained free-router fallback
  - Tier C (aux/cheap): free-model-router aliases
- Escalation triggers to Tier A:
  - same task fails 2x
  - flaky CI repeats 2x
  - auth/security/payment/migration scope
  - high-churn merge conflict resolution
  - release-blocking bug
- PR lifecycle policy:
  - automated code review -> orchestrator fixes -> CI/CD stabilization -> conflict resolution/rebase -> post-rebase CI -> Adam final merge with polished PR description
- Langfuse label policy:
  - dev: experimentation
  - staging: canary
  - production: live orchestration
  - critical/live runs must use production label only

## Profile: orchestrator

- Purpose:
  - decompose tasks, create/route Kanban work, enforce gates, verify evidence, produce merge-ready handoff
- Hermes profile name:
  - orchestrator
- Primary model/provider:
  - codex 5.4 (GitHub/ChatGPT path)
- Fallback chain:
  - codex 5.3 -> sonnet
- Toolsets enabled:
  - kanban, delegation, file, terminal, todo, session_search
- Toolsets disabled:
  - optional: image_gen, tts, other non-essential toolsets
- Workspace mode:
  - scratch
- Max runtime:
  - 20m per task
- System prompt source:
  - Langfuse prompt: orchestrator-system
  - label: production
- Last verified date:
  - YYYY-MM-DD

## Profile: worker-coder

- Purpose:
  - implement micro-scoped coding tasks with strict done-contract evidence
- Hermes profile name:
  - worker-coder
- Primary model/provider:
  - codex 5.3
- Fallback chain:
  - codex 5.4 -> sonnet -> (limited) free-router for low-risk only
- Toolsets enabled:
  - file, terminal, git-related tooling, tests/tooling as needed
- Toolsets disabled:
  - non-essential comms/media toolsets
- Workspace mode:
  - worktree
- Max runtime:
  - 30m per task
- System prompt source:
  - Langfuse prompt: worker-implementer-system
  - label: production
- Last verified date:
  - YYYY-MM-DD

## Profile: reviewer-gatekeeper

- Purpose:
  - verify evidence integrity, spec compliance, quality/security, release readiness
- Hermes profile name:
  - reviewer-gatekeeper
- Primary model/provider:
  - codex 5.4
- Fallback chain:
  - codex 5.3 -> sonnet
- Toolsets enabled:
  - file, terminal (verification-focused)
- Toolsets disabled:
  - broad write/action toolsets unless explicitly needed for fix tasks
- Workspace mode:
  - scratch (or worktree when assigned patch/fix tasks)
- Max runtime:
  - 20m per task
- System prompt source:
  - Langfuse prompt: reviewer-gatekeeper-system
  - label: production
- Last verified date:
  - YYYY-MM-DD

## Profile: worker-ops

- Purpose:
  - execute global-systems tasks (services, infra, config, observability)
- Hermes profile name:
  - worker-ops
- Primary model/provider:
  - codex 5.3
- Fallback chain:
  - codex 5.4 -> sonnet
- Toolsets enabled:
  - terminal, file, web (if needed), system/admin relevant tools
- Toolsets disabled:
  - unrelated media/creative toolsets
- Workspace mode:
  - dir:<ops-path> or scratch
- Max runtime:
  - 45m per task
- System prompt source:
  - Langfuse prompt: worker-ops-system
  - label: production
- Last verified date:
  - YYYY-MM-DD

## Profile: worker-research (optional)

- Purpose:
  - gather/summarize non-critical info and references
- Hermes profile name:
  - worker-research
- Primary model/provider:
  - free-model-router alias (Tier C)
- Fallback chain:
  - codex 5.3 for higher-stakes research synthesis
- Toolsets enabled:
  - web, file
- Toolsets disabled:
  - terminal (optional), write-heavy/action tools
- Workspace mode:
  - scratch
- Max runtime:
  - 15m per task
- System prompt source:
  - Langfuse prompt: worker-research-system
  - label: production
- Last verified date:
  - YYYY-MM-DD

## Required task metadata (all boards)

Every task should define:
- title
- assignee_profile
- board
- workspace_mode
- kind: feature|bug|refactor|ops|research
- risk: low|med|high
- model_tier: A|B|C
- repo: <slug|none>
- depends_on: [task_ids]
- acceptance_criteria: [list]
- verification_commands: [list]
- deliverables: [list]
- done_contract: required artifacts
- failure_policy: retries + escalation rule

## Merge-readiness gate (must all pass)

- required CI checks green
- no unresolved review threads
- branch up to date with base
- post-conflict rebase complete
- post-rebase CI rerun green
- merge-delta reviewed (changes since last approval)
- PR description finalized
- rollback note present
- migration/infra notes present when relevant

## Langfuse prompt governance

- Production orchestration prompts live in Langfuse
- No “latest/unlabelled” prompt fetch in critical paths
- Prompt-impacting PRs must include:
  - old/new prompt version+label mapping
  - expected behavior delta
  - rollback target
  - canary evidence (staging) before production promotion

## Validation commands

- List profiles:
  - hermes profile list
- Show profile details:
  - hermes profile show <name>
- Inspect config:
  - hermes -p <name> config
- Smoke test each profile:
  - hermes -p <name> chat -q "say HELLO" --quiet
- Verify Kanban assignees:
  - hermes kanban assignees
- Verify Langfuse tracing is active:
  - grep "Langfuse tracing: started trace" ~/.hermes/logs/agent.log | tail -5

## Change log

- YYYY-MM-DD:
  - Initialized v1 profile setup notes
  - Adopted Option B cross-board policy
  - Added dual global boards (global-deps, global-systems)
  - Set Codex 5.4/5.3 as reliable tier
  - Aligned prompt governance to Langfuse labels
