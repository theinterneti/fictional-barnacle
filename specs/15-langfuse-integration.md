# S15-LF — Langfuse Integration

> **Status**: 📝 Draft
> **Release Baseline**: 🔒 v1 Closed (extends S15)
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: S15 (Observability), S11 (Player Identity & Sessions), S09 (Prompt & Content Management), S45 (Evaluation Pipeline)
> **Last Updated**: 2026-05-13

## Overview

This spec extends S15 §4 (LLM Observability) into a comprehensive Langfuse
integration covering **three tracing surfaces** not fully addressed by S15:

1. **User lifecycle** — account creation, login, logout, preference changes,
   account deletion, admin actions on users
2. **Session / game lifecycle** — session creation, resume, end, timeout,
   abandon; game start, completion; universe binding events
3. **Prompt enrichment & evaluation** — prompt-to-generation provenance
   linking, prompt version metrics, evaluation score pipeline integration

This spec does NOT duplicate S15's LLM call instrumentation requirements
(FR-15.17–15.21). It ADDS tracing for non-LLM events and enriches the
LLM tracing surface with prompt provenance and eval integration.

### Relationship to S15

| Surface | S15 Coverage | This Spec Adds |
|---------|-------------|----------------|
| LLM calls | FR-15.17–15.21 (required) | Prompt provenance metadata, `langfuse_prompt` object forwarding, per-version metrics (AC-09.7) |
| User events | Not covered | Account lifecycle traces, admin actions |
| Session events | FR-15.18 (hierarchy definition) | Lifecycle event traces (create/resume/end/timeout/abandon) |
| Prompt mgmt | FR-15.20 (versioning) | Sync pipeline, caching strategy, namespace conventions |
| Evaluations | S45 mentions Langfuse scores | Score naming convention, emission path, baseline comparison |
| Correlation | FR-15.29–15.31 (cross-system) | Langfuse session grouping, `session_id` → Langfuse session mapping |

### Guiding Principles

- **Langfuse-first observability**: Langfuse is the primary LLM and game
  observability store. Grafana is supplemental for infrastructure metrics.
  Dashboards that duplicate Langfuse data are anti-pattern.
- **Resilience over completeness**: Langfuse unavailability SHALL NOT affect
  gameplay. Every trace/score emission is fire-and-forget with throttled
  error logging (EC-15.5, extended).
- **Privacy by construction**: PII pseudonymization, GDPR erasure path,
  consent-gated storage — same guarantees as S15 §8 extended to all new
  trace types.
- **Session-native**: Every trace carries a `session_id`. Langfuse sessions
  group all traces for a player's game session. The Langfuse session view
  shows the full session lifecycle.

---

## 1. User Lifecycle Tracing

### 1.1 User Stories

- **US-LF.1**: As a developer, I can see every user's account lifecycle in
  Langfuse — when they registered, when they logged in, and when they
  deleted their account — linked to their pseudonymized identity.
- **US-LF.2**: As an operator, I can audit admin actions on user accounts
  (disable, enable, data export) with full trace context.
- **US-LF.3**: As a developer, I can trace a user's journey from first
  anonymous play through account creation to their 50th session.

### 1.2 Functional Requirements

**FR-LF.1**: The following user lifecycle events SHALL create Langfuse
traces:

| Event | Trace Name | Key Metadata |
|-------|-----------|--------------|
| Anonymous play start | `user.anonymous_start` | `anonymous_id` |
| Account registration | `user.register` | `user_id` (pseudonymized), `auth_method` |
| Login | `user.login` | `user_id`, `auth_method`, `login_count` |
| Login failure | `user.login_failed` | `user_id` (if known), `failure_reason` |
| Logout | `user.logout` | `user_id`, `session_duration_s` |
| Display name change | `user.preference_change` | `user_id`, `field: display_name` |
| Account deletion | `user.delete` | `user_id`, `sessions_orphaned` |
| Admin: user disable | `admin.user_disable` | `target_user_id`, `admin_user_id`, `reason` |
| Admin: user enable | `admin.user_enable` | `target_user_id`, `admin_user_id` |
| Admin: data export | `admin.data_export` | `target_user_id`, `admin_user_id`, `format` |
| GDPR erasure | `privacy.erasure` | `user_id`, `traces_purged`, `sessions_purged` |

**FR-LF.2**: User lifecycle traces SHALL:
- Carry `user_id` (pseudonymized via SHA-256 truncated to 16 chars, per FR-15.21)
- Carry `session_id` when the event occurs within an active session
- NOT carry raw email addresses, IP addresses, or passwords
- Be tagged `lifecycle` for filtering in the Langfuse UI

**FR-LF.3**: All user lifecycle traces for a given user SHALL be linkable
via the pseudonymized `user_id` field in Langfuse's `userId` trace attribute.
This enables filtering all traces by user in the Langfuse UI.

**FR-LF.4**: The trace function SHALL be fire-and-forget. If the Langfuse
client is unavailable or the trace creation fails, the user operation
completes normally and the error is logged (throttled, per EC-15.5).

### 1.3 Edge Cases

- **EC-LF.1**: If a user registers mid-session (US-11.2), the `user.register`
  trace SHALL reference the existing `session_id` so the registration event
  appears in the session timeline.
- **EC-LF.2**: If account deletion fails mid-operation (partial cleanup),
  the `user.delete` trace SHALL include `cleanup_status: partial` and the
  specific subsystems that succeeded/failed.
- **EC-LF.3**: If an anonymous session never converts to a registered
  account, all traces for that session SHALL use a consistent anonymous
  `user_id` (derived from `anonymous_id`) rather than `null`.

### 1.4 Acceptance Criteria

- [ ] Account registration creates a `user.register` trace with pseudonymized `user_id`.
- [ ] Five logins by the same user produce five `user.login` traces with incrementing `login_count`.
- [ ] Admin disable creates an `admin.user_disable` trace with `target_user_id` and `reason`.
- [ ] Account deletion creates a `user.delete` trace with `sessions_orphaned` count.
- [ ] All user lifecycle traces are filterable by `user_id` in Langfuse UI.
- [ ] Langfuse unavailability does not prevent login or registration.

---

## 2. Session & Game Lifecycle Tracing

### 2.1 User Stories

- **US-LF.4**: As a developer, I can see the full timeline of a game session
  in Langfuse — session creation, each turn, pauses, resumes, and termination.
- **US-LF.5**: As an operator, I can identify abandoned sessions, sessions
  with high cost, and sessions that triggered safety systems.
- **US-LF.6**: As a developer debugging session state bugs, I can see exactly
  when a session was paused, resumed, and what universe it was bound to.

### 2.2 Functional Requirements

**FR-LF.5**: The following session lifecycle events SHALL create Langfuse
traces:

| Event | Trace Name | Key Metadata |
|-------|-----------|--------------|
| Session created | `session.create` | `session_id`, `game_id`, `universe_id`, `user_id`, `creation_source` (anonymous/registered) |
| Session resumed | `session.resume` | `session_id`, `idle_duration_s`, `resume_source` (web/returning) |
| Game started | `game.start` | `session_id`, `game_id`, `universe_id`, `scenario_seed_id`, `genesis_duration_ms` |
| Game completed | `game.complete` | `session_id`, `game_id`, `total_turns`, `total_cost_usd`, `ending_type` |
| Session ended | `session.end` | `session_id`, `total_turns`, `total_cost_usd`, `end_reason` (explicit/timeout/abandon) |
| Session abandoned | `session.abandon` | `session_id`, `last_turn_at`, `idle_duration_s` |
| Session timeout | `session.timeout` | `session_id`, `timeout_policy`, `last_turn_at` |
| Universe bound | `session.universe_bind` | `session_id`, `universe_id`, `universe_name` |
| Universe unbound | `session.universe_unbind` | `session_id`, `universe_id` |

**FR-LF.6**: Session lifecycle traces SHALL:
- Use the same `session_id` as S11 game sessions
- Be grouped into a **Langfuse session** (via `trace.session_id`) so the
  Langfuse UI shows a single session timeline with all events
- Include `game_id` and `universe_id` when applicable for cross-referencing
- Be tagged `lifecycle` and `session`

**FR-LF.7**: Langfuse session grouping SHALL follow this hierarchy:
```
Langfuse Session  (session_id = S11 game session ID)
├── Trace: session.create
├── Trace: game.start
├── Trace: turn-1 (LLM calls as generations)
├── Trace: turn-2
├── Trace: session.resume        (if paused/resumed)
├── Trace: turn-3
├── Trace: game.complete
└── Trace: session.end
```

**FR-LF.8**: The `session.create` trace SHALL be created BEFORE the first
turn is processed. If game genesis (S02) is asynchronous, the trace is
created immediately and updated with `genesis_duration_ms` when genesis
completes.

**FR-LF.9**: Session end tracing SHALL distinguish explicit termination
(player clicks "End Game") from timeout (server-enforced) from abandon
(idle beyond policy + no explicit action). The `end_reason` field SHALL
be one of: `explicit`, `timeout`, `abandon`.

### 2.3 Edge Cases

- **EC-LF.4**: If a session is created but the player never takes a turn
  (zero-turn session), a `session.end` trace SHALL still be created with
  `total_turns: 0` and `end_reason: abandon`.
- **EC-LF.5**: If the Langfuse export fails for `session.create`, subsequent
  turn traces MAY still be created (they reference the same `session_id`
  which Langfuse will accept as part of a new session implicitly). The
  session grouping will be incomplete but functional.
- **EC-LF.6**: Universe binding events during game start SHALL be traced
  even if genesis fails mid-process — the trace carries `genesis_status:
  failed` and the failure reason.

### 2.4 Acceptance Criteria

- [ ] Creating a new game produces `session.create`, `game.start`, and
  `session.universe_bind` traces in Langfuse.
- [ ] Completing a game from start to finish produces traces for each
  turn, `game.complete`, and `session.end`.
- [ ] All traces for a single session appear grouped under one Langfuse
  session when filtering by `session_id`.
- [ ] An abandoned session (no turns for > timeout) produces a
  `session.timeout` trace followed by `session.abandon`.
- [ ] Session traces include `total_cost_usd` aggregated from all LLM
  calls in the session.

---

## 3. Prompt Enrichment & Provenance

### 3.1 User Stories

- **US-LF.7**: As a developer, I can see which prompt version was used for
  every LLM generation in Langfuse, including fragment versions when
  prompts are composed from multiple templates.
- **US-LF.8**: As a prompt engineer, I can compare latency, token usage,
  and cost between prompt versions in the Langfuse UI without writing
  custom queries.
- **US-LF.9**: As a developer, I know whether a generation used the
  Langfuse-managed prompt or fell back to a file-system template.

### 3.2 Functional Requirements

**FR-LF.10**: Every LLM generation in Langfuse SHALL carry the following
prompt provenance fields in generation metadata:

| Field | Source | Example |
|-------|--------|---------|
| `prompt_id` | `LangfusePromptBridge` render | `narrative-generation` |
| `prompt_version` | Langfuse prompt version label | `production` or `3` |
| `prompt_hash` | Stable canonical serialization | `a1b2c3d4e5f6` |
| `prompt_family` | Template namespace | `narrative` |
| `fragment_versions` | Resolution graph (if composed) | `{"system_persona": 2, "generation_style": 1}` |
| `prompt_source` | Resolution path | `langfuse` or `filesystem_fallback` |

**FR-LF.11**: The `LangfusePromptBridge` (S09) SHALL return a
`RenderedPrompt` object that includes a `langfuse_prompt` reference
(the Langfuse `TextPromptClient` or `ChatPromptClient`). This object
SHALL be forwarded to the Langfuse generation recorder.

**FR-LF.12**: The Langfuse generation recorder SHALL pass the
`langfuse_prompt` object to `trace.generation(prompt=...)` so that
Langfuse links the generation to the prompt version. This enables
per-version metrics (latency, tokens, cost, scores) in the Langfuse UI.

**FR-LF.13**: Prompt provenance SHALL survive retry. If an LLM call is
retried with the same prompt, all retry generations SHALL carry the same
`prompt_id`, `prompt_version`, and `prompt_hash`. The retry wrapper in
`guarded_llm_call()` SHALL preserve and forward the provenance fields.

**FR-LF.14**: When a prompt is resolved from the filesystem fallback
(Langfuse unreachable), the generation SHALL carry `prompt_source:
filesystem_fallback` and `prompt_version: unknown`. This ensures
traceability even during Langfuse outages.

### 3.3 Edge Cases

- **EC-LF.7**: If the `LangfusePromptBridge` returns a rendered prompt
  but the `langfuse_prompt` object is `None` (e.g., Langfuse client
  recreated between render and record), the generation still carries
  full metadata provenance but the UI-level prompt version link is absent.
- **EC-LF.8**: If a prompt template is composed from fragments where one
  fragment fails to resolve, `fragment_versions` SHALL include the
  failing fragment with version `error` and the generation proceeds
  with a warning.

### 3.4 Acceptance Criteria

- [ ] Every LLM generation in Langfuse shows `prompt_id` and `prompt_version`
  in the generation metadata.
- [ ] Changing a prompt in Langfuse and re-running the same turn produces
  a new generation linked to the new prompt version.
- [ ] The Langfuse UI shows per-version metrics (latency, cost, tokens)
  for prompts with multiple versions.
- [ ] During a Langfuse outage, generations show `prompt_source:
  filesystem_fallback` and the game proceeds normally.
- [ ] Retried LLM calls carry the same prompt provenance as the original.

---

## 4. Evaluation Score Integration

### 4.1 User Stories

- **US-LF.10**: As a developer, I can see narrative quality scores in
  Langfuse alongside the session traces they evaluate.
- **US-LF.11**: As a release coordinator, I can compare evaluation scores
  across releases in Langfuse to detect narrative quality regressions.
- **US-LF.12**: As an operator, I can see evaluation pipeline throughput
  and failure rates in Langfuse.

### 4.2 Functional Requirements

**FR-LF.15**: The S45 Evaluation Pipeline SHALL emit every
`NarrativeQualityReport` score to Langfuse as a NUMERIC score on the
corresponding session trace.

**FR-LF.16**: Langfuse score naming SHALL follow the convention:

| S44 Dimension | Langfuse Score Name | Value Range |
|---------------|-------------------|-------------|
| Coherence | `eval.coherence` | 0.0–1.0 |
| Consistency | `eval.consistency` | 0.0–1.0 |
| Engagement | `eval.engagement` | 0.0–1.0 |
| Prose Quality | `eval.prose_quality` | 0.0–1.0 |
| Wonder | `eval.wonder` | 0.0–1.0 |
| Overall | `eval.overall` | 0.0–1.0 |
| Session cost | `eval.session_cost_usd` | float |

**FR-LF.17**: Each score emission SHALL include a `comment` field
containing:
- The `session_id` evaluated
- The evaluator type (`llm` or `human`)
- The S44 version used
- A summary of any failing dimensions

**FR-LF.18**: S45 pipeline runs SHALL themselves be traced as Langfuse
traces (name `eval.pipeline_run`) with:
- `run_mode` (ci/release)
- `scenario_count`
- `sessions_evaluated`
- `baseline_compared` (bool)
- `verdict` (pass/fail)
- Tags: `evaluation`, `run_mode:{ci|release}`

**FR-LF.19**: Evaluation scores SHALL NOT be emitted for sessions where
the player has NOT consented to evaluation data collection (per S17).

### 4.3 Edge Cases

- **EC-LF.9**: If an S44 evaluator fails for a specific dimension
  (e.g., Wonder not evaluable), the dimension score SHALL be omitted
  rather than emitting a zero value. Missing dimensions SHALL be
  documented in the `eval.pipeline_run` trace metadata.
- **EC-LF.10**: If Langfuse is unreachable during evaluation, scores
  SHALL be buffered to a local file and retried on the next pipeline
  run. The pipeline run trace carries `score_export: buffered`.

### 4.4 Acceptance Criteria

- [ ] Running S45 in CI mode produces an `eval.pipeline_run` trace in Langfuse.
- [ ] Each evaluated session shows `eval.*` scores attached to its session trace.
- [ ] Scores include the evaluator type and S44 version in the comment field.
- [ ] Sessions without evaluation consent have zero Langfuse scores.
- [ ] Missing dimensions do not produce zero-value scores.

---

## 5. Langfuse Session Configuration

### 5.1 User Stories

- **US-LF.13**: As a developer, I can configure Langfuse via environment
  variables without code changes.
- **US-LF.14**: As an operator, I can verify Langfuse connectivity at
  startup with a clear health check message.

### 5.2 Functional Requirements

**FR-LF.20**: Langfuse configuration SHALL use these environment variables
(prefixed with `TTA_` per Settings config):

| Env Var | Config Field | Required | Default |
|---------|-------------|----------|---------|
| `TTA_LANGFUSE_HOST` | `langfuse_host` | No | `None` (disabled) |
| `TTA_LANGFUSE_PUBLIC_KEY` | `langfuse_public_key` | If host set | — |
| `TTA_LANGFUSE_SECRET_KEY` | `langfuse_secret_key` | If host set | — |
| `TTA_LANGFUSE_ENABLED` | `langfuse_enabled` | No | `true` when host set |
| `TTA_LANGFUSE_SAMPLE_RATE` | `langfuse_sample_rate` | No | `1.0` |
| `TTA_LANGFUSE_ENVIRONMENT` | `langfuse_environment` | No | `development` |

**FR-LF.21**: The local self-hosted Langfuse instance at `http://localhost:3001`
SHALL be the default for development. The TTA project (`cmonj12g70006guxy9z6qo25g`)
SHALL be used for all fictional-barnacle traces.

**FR-LF.22**: At startup, if Langfuse is configured, the application SHALL:
1. Initialize the Langfuse client
2. Log the project connection status (success/warning/disabled)
3. Verify connectivity with a lightweight health check
4. Proceed regardless — Langfuse unavailability is non-fatal (FR-15.19)

### 5.3 Acceptance Criteria

- [ ] Setting `TTA_LANGFUSE_HOST` alone does not enable Langfuse
  (both keys required).
- [ ] Setting all three variables enables Langfuse tracing.
- [ ] Startup log shows `langfuse_enabled` or `langfuse_disabled` status.
- [ ] Langfuse unavailability at startup logs a warning but does not
  prevent the application from serving traffic.

---

## 6. Privacy & Data Retention

### 6.1 Functional Requirements

**FR-LF.23**: All privacy guarantees from S15 §8 SHALL apply to every
trace type defined in this spec. No trace SHALL contain raw PII in
metadata, tags, or input/output fields.

**FR-LF.24**: Player identifiers across ALL trace types SHALL be
pseudonymized using the same `pseudonymize_player_id()` function
(SHA-256, truncated to 16 chars).

**FR-LF.25**: GDPR erasure requests SHALL:
1. Delete all Langfuse traces and scores for the pseudonymized user ID
   via the Langfuse API
2. Log a `privacy.erasure` trace (using a separate admin API key so the
   trace survives the deletion)
3. Return the count of purged traces and sessions to the caller

**FR-LF.26**: Langfuse data SHALL be retained according to the Langfuse
project's retention policy. TTA SHALL NOT implement its own trace
deletion scheduler — retention is managed at the Langfuse level.

### 6.2 Acceptance Criteria

- [ ] No trace in Langfuse contains a raw email address, IP address, or password.
- [ ] Player `user_id` values in Langfuse are 16-char hex hashes, not
  database primary keys.
- [ ] GDPR erasure purges all traces for a user within 5 minutes of request.

---

## 7. Key Scenarios (Gherkin)

```gherkin
Scenario: Full session lifecycle is traceable in Langfuse
  Given Langfuse is configured and reachable
  And a player has an account
  When the player creates a new game session
  Then a trace named "session.create" appears in Langfuse
  And the trace carries session_id, game_id, and pseudonymized user_id
  When the player completes 3 turns
  Then each turn produces a trace with LLM generations
  And each generation carries prompt_id and prompt_version metadata
  When the player explicitly ends the game
  Then traces "game.complete" and "session.end" appear
  And "session.end" carries total_turns=3 and total_cost_usd > 0
  And all traces are grouped under the same Langfuse session

Scenario: User registration mid-session is traced
  Given an anonymous session exists with session_id "sess_anon"
  When the player registers an account during the session
  Then a "user.register" trace appears with session_id "sess_anon"
  And subsequent turns carry the new pseudonymized user_id
  And the anonymous turns still carry the anonymous user_id

Scenario: Langfuse outage does not affect gameplay
  Given Langfuse is configured
  And Langfuse becomes unreachable
  When a player submits a turn
  Then the turn is processed normally
  And a narrative response is returned
  And a throttled warning is logged
  And no error is returned to the player
  And the generation metadata shows prompt_source: filesystem_fallback

Scenario: Evaluation scores appear in Langfuse
  Given a completed game session exists
  When the S45 evaluation pipeline runs in CI mode
  Then an "eval.pipeline_run" trace appears in Langfuse
  And the trace carries run_mode=ci and verdict
  And each evaluated session shows eval.coherence, eval.engagement scores
  And failing dimensions are documented in the pipeline trace metadata

Scenario: Prompt version change is visible in Langfuse
  Given prompt "narrative-generation" is at version 1
  When a turn is processed using version 1
  Then the generation carries prompt_version=1
  When the prompt is updated to version 2 in Langfuse
  And a new turn is processed
  Then the new generation carries prompt_version=2
  And the Langfuse UI shows separate metrics for version 1 and version 2
```

---

## 8. Non-Normative: Trace Architecture

### 8.1 Trace Hierarchy

```
Langfuse Project: TTA (cmonj12g70006guxy9z6qo25g)
│
├── User Lifecycle Traces (tag: lifecycle)
│   ├── user.anonymous_start
│   ├── user.register
│   ├── user.login / user.login_failed
│   ├── user.logout
│   ├── user.preference_change
│   ├── user.delete
│   ├── admin.user_disable / admin.user_enable
│   ├── admin.data_export
│   └── privacy.erasure
│
├── Session Lifecycle Traces (tag: lifecycle, session)
│   ├── session.create        ← grouped by session_id
│   ├── game.start
│   ├── turn-{id}             ← S15 traces (LLM calls as generations)
│   │   ├── generation: input_understanding
│   │   ├── generation: context_assembly
│   │   └── generation: narrative_generation
│   ├── session.resume
│   ├── session.universe_bind / session.universe_unbind
│   ├── game.complete
│   ├── session.end / session.timeout / session.abandon
│   └── session.universe_unbind
│
├── Evaluation Traces (tag: evaluation)
│   ├── eval.pipeline_run
│   └── eval.* scores (attached to session traces)
│
└── Prompt Management
    └── Generation metadata carries prompt_id, prompt_version,
        prompt_hash, fragment_versions, prompt_source
```

### 8.2 Score Taxonomy

```
eval.coherence       0.0–1.0   NUMERIC   S44 dimension
eval.consistency     0.0–1.0   NUMERIC   S44 dimension
eval.engagement      0.0–1.0   NUMERIC   S44 dimension
eval.prose_quality   0.0–1.0   NUMERIC   S44 dimension
eval.wonder          0.0–1.0   NUMERIC   S44 dimension
eval.overall         0.0–1.0   NUMERIC   S44 composite
eval.session_cost_usd  float    NUMERIC   Per-session cost
```

### 8.3 Implementation Map

| Component | File | Responsibility |
|-----------|------|---------------|
| Langfuse client init | `src/tta/observability/langfuse.py` | `init_langfuse()` — already exists |
| LLM generation recording | `src/tta/observability/langfuse.py` | `record_llm_generation()` — already exists, add provenance |
| User lifecycle tracing | `src/tta/observability/langfuse.py` | New: `trace_user_event()` |
| Session lifecycle tracing | `src/tta/observability/langfuse.py` | New: `trace_session_event()` |
| Eval score emission | `src/tta/eval/pipeline.py` | `ship_to_langfuse()` — add score emission |
| Prompt bridge | `src/tta/prompts/langfuse_bridge.py` | Already exists — verify `langfuse_prompt` forwarding |
| GDPR erasure | `src/tta/privacy/retention.py` | New: `purge_langfuse_user_data()` |
| Startup health check | `src/tta/api/app.py` | `init_langfuse()` — already called in lifespan |

---

## Changelog

- 2026-05-13: Initial draft. Extends S15 §4 with user lifecycle, session
  lifecycle, prompt provenance enrichment, and evaluation score integration.
