# FB-005 — Prompt Registry v2: Runtime Versioning, Genre Packs, Observability & Authoring Workflow

> **Status**: 📝 Draft
> **Release Baseline**: v2
> **Dependencies**: S09 (Prompt & Content Management), S07 (LLM Integration), S15 (Observability), S39 (Universe Composition Model)
> **Last Updated**: 2026-05-10

## 1 — Purpose

This spec fills four gaps identified in the S09 v1 closeout as **deferred to v2**:

| AC | Area | v1 Status | v2 Priority |
|---|---|---|---|
| AC-09.02 | Runtime prompt activation & rollback | File-based only; requires redeploy | High |
| AC-09.06 | Genre packs & content assets | Single template `haunted_manor` only | High |
| AC-09.07 | Langfuse per-version metrics & filtered querying | No Langfuse prompt linkage | Medium |
| AC-09.09 | Interactive preview & shadow mode | No authoring tooling shipped | Low |

Each section below decomposes its AC into concrete, testable sub-ACs with implementation guidance.

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Runtime prompt switching enables rapid iteration on narrative quality without downtime |
| **Coherence** | Genre packs must be self-validating; switching genre must not break prompt variable contracts |
| **Craftsmanship** | Every prompt version's performance is tracked and comparable |
| **Openness** | Genre pack format must be authorable by community contributors in a text editor |

---

## 2 — User Stories

### US-FB-005.1 — Runtime prompt activation without redeploy
> As a **content author**, I want to activate a new prompt version, preview its output, and roll it back if quality degrades — without a code deployment or process restart.

### US-FB-005.2 — Genre-pack portability
> As a **universe designer**, I want to bundle prompts, variable defaults, and metadata into a portable genre pack (`haunted_manor`, `space_opera`, `noir_detective`) that can be loaded into any compatible TTA instance.

### US-FB-005.3 — Prompt performance observability
> As an **operator**, I want to compare Langfuse trace metrics (latency, cost, completion rate) across prompt versions so I can decide which version is performing best.

### US-FB-005.4 — Interactive preview without gameplay side effects
> As a **content author**, I want to render a prompt against a saved game state in shadow mode, see the output, and compare it to the currently-active version — without modifying game state, consuming turn credits, or affecting observability dashboards.

---

## 3 — AC-09.02: Runtime Prompt Registry

The existing `FilePromptRegistry` (S09 §4) loads all templates at startup and cannot switch versions without a process restart. This section adds runtime version activation, rollback, and a version-store backend.

### 2.1 — Version store

**FB-AC-09.02.01**: The system SHALL maintain a **version store** — a persistence layer (PostgreSQL JSONB or Redis) that maps `(prompt_id, semver)` → full prompt metadata + body. The version store SHALL be the source of truth for all prompt versions at runtime.

**FB-AC-09.02.02**: The file-based `FilePromptRegistry` SHALL act as a seed loader: on startup, all `.prompt.md` files SHALL be loaded into the version store as `Draft` versions. After initial load, the registry SHALL resolve prompts from the version store, not from disk.

**FB-AC-09.02.03**: The version store SHALL support the full registry API from S09 §4.2:
- `get(prompt_id)` → active version metadata + body
- `get(prompt_id, version)` → specific version metadata + body
- `list()` → all prompt IDs with active versions
- `activate(prompt_id, version)` → set a version as active
- `register(prompt_data)` → add a new prompt version
- `history(prompt_id)` → version history with activation timestamps

### 2.2 — Runtime activation without restart

**FB-AC-09.02.04**: The `activate(prompt_id, version)` operation SHALL take effect immediately for all subsequent `get(prompt_id)` calls. In-flight renders that have already loaded a template SHALL continue using the version they loaded (no mid-render swap).

**FB-AC-09.02.05**: The `rollback(prompt_id)` operation SHALL reactivate the previously active version. The system SHALL maintain a stack of at least the last 5 active versions per prompt for multi-step rollback.

**FB-AC-09.02.06**: Activation and rollback SHALL be atomic. Concurrent activation requests for the same prompt SHALL be serialized (first-wins or last-write-wins) and both logged. No inconsistent state SHALL result.

### 2.3 — Notification & cache invalidation

**FB-AC-09.02.07**: When a version is activated or rolled back, the system SHALL publish a `prompt.version.activated` event (via a in-process event bus or Redis pub/sub). Any component caching a rendered prompt SHALL invalidate its cache on receiving this event.

### 2.4 — Audit

**FB-AC-09.02.08**: Every `activate` and `rollback` call SHALL be recorded with:
- Timestamp (UTC, ISO 8601)
- Actor identity (API key owner, operator session, or CI/CD pipeline)
- Prompt ID
- Previous version → new version
- Reason (if provided)

### 2.5 — Version lifecycle enforcement

**FB-AC-09.02.09**: Only versions in `Testing` or `Active` status SHALL be eligible for activation. `Draft` versions MUST pass registration validation first. `Deprecated` versions SHALL be eligible for rollback within the retention window. `Archived` versions SHALL NOT be eligible for activation.

**FB-AC-09.02.10**: The retention period for `Deprecated` status SHALL be configurable per prompt (default: 30 days). After the retention period, the version transitions to `Archived` automatically.

---

## 4 — AC-09.06: Genre Packs & Content Assets

The existing system has a single `haunted_manor` template. This section defines a **genre pack** system that bundles tone, archetypes, location moods, and fallback responses into self-contained, versioned assets.

### 3.1 — Genre pack format

**FB-AC-09.06.01**: A genre pack SHALL be a directory conforming to:

```
genre-packs/
  noirdetective/
    pack.json              # metadata + manifest
    tones/                 # tone guide fragments
      primary.tone.md
    archetypes/            # NPC archetype definitions
      femme-fatale.archetype.md
      weary-cop.archetype.md
    locations/             # location mood templates
      bar.location.md
      street.location.md
    fallbacks/             # fallback response templates
      thinking.fallback.md
      cant_do.fallback.md
```

**FB-AC-09.06.02**: The `pack.json` manifest SHALL contain:
- `id`: unique slug (e.g., `noirdetective`)
- `version`: semantic version
- `name`: human-readable name (e.g., "Noir Detective")
- `author`: creator identifier
- `description`: short summary
- `genre_tone`: the genre tone string injected into prompt templates (e.g., "noir detective")
- `required_templates`: list of prompt template IDs this pack is designed for
- `compatible_templates`: list of prompt template IDs this pack is compatible with

**FB-AC-09.06.03**: Tone, archetype, location, and fallback files SHALL use YAML front matter + body format (same as `.prompt.md`). Each SHALL declare:
- `id`: unique within the pack
- `version`: semantic version
- `description`: what this asset contributes

### 3.2 — Genre pack loading

**FB-AC-09.06.04**: The system SHALL support loading a genre pack at startup via a `GENRE_PACKS` configuration setting (list of directory paths or pack IDs). Packs SHALL be registered in a **content asset registry** parallel to the prompt registry.

**FB-AC-09.06.05**: The active genre pack SHALL be selectable per session (via session configuration). Switching the active genre pack for a session SHALL NOT require a server restart or redeploy.

**FB-AC-09.06.06**: When a genre pack is loaded, the system SHALL validate that all `required_templates` exist in the prompt registry. If a required template is missing, the pack SHALL fail to load with a clear error listing the missing templates.

### 3.3 — Variable injection from genre packs

**FB-AC-09.06.07**: Genre pack content SHALL be injected into prompt templates via standard variables. The pipeline (S08) SHALL resolve the session's active genre pack and inject:
- `genre_tone` → from `pack.genre_tone`
- `genre_tone_guide` → concatenated tone `.tone.md` content
- `genre_archetypes` → formatted list of available archetypes
- `genre_location_moods` → map of location type → mood description
- `genre_fallbacks` → map of fallback scenario → response text

These SHALL be added to the standard variable catalog (S09 §6.2).

### 3.4 — Content asset versioning

**FB-AC-09.06.08**: Content assets (genre packs, individual tone/archetype files) SHALL follow the same semantic versioning scheme as prompts (S09 §5.1). A pack's version MAJOR bump indicates breaking changes in its variable contracts.

**FB-AC-09.06.09**: The content asset registry SHALL support runtime version activation for individual assets within a pack, independent of the pack version. This allows hotfixing a single archetype without re-releasing the entire pack.

### 3.5 — Multiple active genre packs

**FB-AC-09.06.10**: The system SHALL support up to 3 genre packs loaded simultaneously. Only one pack SHALL be "active" per session. The `genre_tone` variable SHALL come exclusively from the active pack; other packs are available for cross-referencing or fallback.

---

## 5 — AC-09.07: Prompt Observability & Metrics

The existing Langfuse integration (`src/tta/observability/langfuse.py`) already records `prompt_id`, `prompt_version`, `fragment_versions`, and `prompt_hash` in generation metadata (lines 166–173). This section formalizes the observability contract and adds per-version metric aggregation and automated regression detection.

### 4.1 — Generation-to-prompt linkage

**FB-AC-09.07.01**: Every LLM generation recorded in Langfuse SHALL include in its metadata (already partially implemented):
- `prompt_id`: the root template ID
- `prompt_version`: exact version of the root template
- `fragment_versions`: dict of fragment slug → version hash
- `prompt_hash`: SHA-256 prefix (16 chars) of the final assembled prompt
- `prompt_activation_label`: the label (e.g., `production`, `testing`, `shadow`) that resolved the version

**FB-AC-09.07.02**: The system SHALL add a Langfuse dataset tag or trace tag of the form `prompt:{prompt_id}:{prompt_version}` for every generation. This enables filtering by prompt version in the Langfuse UI without relying on metadata queries alone.

### 4.2 — Per-version metric aggregation

**FB-AC-09.07.03**: The system SHALL aggregate the following metrics per `(prompt_id, prompt_version)` daily:
- Generation count
- Mean latency (ms)
- P50/P95/P99 latency
- Mean input tokens
- Mean output tokens
- Mean cost (USD)
- Error rate (fraction of generations that raised an exception, hit a fallback, or failed structured output parsing)
- Quality rejection rate (fraction of generations flagged by the moderation layer per S24)
- Mean player rating (if a feedback mechanism exists for the active session)

**FB-AC-09.07.04**: Aggregated metrics SHALL be stored in PostgreSQL in a `prompt_metrics` table with schema:
- `id` UUID PK
- `prompt_id` VARCHAR NOT NULL
- `prompt_version` VARCHAR NOT NULL
- `date` DATE NOT NULL
- `generation_count` INTEGER
- `mean_latency_ms` FLOAT, `p50_latency_ms` FLOAT, `p95_latency_ms` FLOAT, `p99_latency_ms` FLOAT
- `mean_input_tokens` FLOAT, `mean_output_tokens` FLOAT
- `mean_cost_usd` FLOAT
- `error_rate` FLOAT, `quality_rejection_rate` FLOAT
- `mean_player_rating` FLOAT (nullable)
- UNIQUE constraint on `(prompt_id, prompt_version, date)`

### 4.3 — Automated regression detection

**FB-AC-09.07.05**: When a new prompt version is activated, the system SHALL start a **warm-up period** (configurable per prompt, default: 100 generations). During warm-up, metrics SHALL be collected but no comparison is made.

**FB-AC-09.07.06**: After the warm-up period, the system SHALL compare the new version's metrics against the previous active version's baseline (last 7 days of the previous version's data). If ANY metric exceeds a configurable degradation threshold, the system SHALL:
- Log a warning structlog event `prompt_metric_regression`
- Send an alert via the configured alerting channel (S26 admin tooling)
- NOT automatically rollback — the alert requires human review

**FB-AC-09.07.07**: Default degradation thresholds SHALL be:
- Mean latency increase > 50%
- Error rate > 2× the previous version
- Mean output tokens decrease > 40% (suggests truncated/empty output)
- Mean player rating decrease > 0.5 (if rating data available)

### 4.4 — Metrics API

**FB-AC-09.07.08**: The system SHALL expose a read-only API endpoint `GET /admin/prompts/{prompt_id}/metrics` (or equivalent admin tooling) that returns:
- Available versions for the prompt
- Per-version metric summaries for a requested date range
- Comparison view (selected version vs. baseline version)

---

## 6 — AC-09.09: Authoring Workflow

The v1 authoring workflow is file → commit → deploy. This section adds interactive preview and shadow mode so authors can iterate without deployment.

### 5.1 — Interactive preview mode

**FB-AC-09.09.01**: The system SHALL expose a `POST /admin/prompts/preview` endpoint (or equivalent admin tooling) that accepts:
- `prompt_id`: template to render
- `version`: specific version (or `latest`)
- `variables`: key-value map of template variables
- `model_override`: optional model ID (defaults to the prompt's configured model)
- `parameters_override`: optional generation parameter overrides

**FB-AC-09.09.02**: The preview endpoint SHALL:
1. Resolve the prompt template using the prompt registry
2. Render the template with provided variables
3. Send the rendered prompt to the LLM (with temperature=0 for reproducibility)
4. Return `{ "rendered_prompt": "...", "output": "...", "token_estimate": N, "latency_ms": N }`
5. Log the preview call to Langfuse with tag `preview` (distinct from production generations)

**FB-AC-09.09.03**: Preview calls SHALL NOT be associated with any session, SHALL NOT modify any game state, and SHALL NOT be delivered to any player. They SHALL be rate-limited separately from game-turn LLM calls (default: 30 previews per minute per operator).

### 5.2 — Validation at registration

**FB-AC-09.09.04**: When a prompt version is registered (via API or file re-scan), the system SHALL validate (per S09 §11.2 FR-09.43):
- Template syntax (Jinja2 AST parses without error)
- All required variables are declared in the metadata variable list
- All referenced fragments exist in the registry
- If an output schema is specified, it is valid JSON Schema
- The prompt + estimated maximum context fits within the target model's context window (estimated)

**FB-AC-09.09.05**: Validation failures SHALL produce structured error responses with:
- `field`: the specific field or section that failed
- `message`: human-readable description
- `code`: machine-readable error code (e.g., `MISSING_VARIABLE`, `INVALID_SYNTAX`, `CONTEXT_OVERFLOW`)
- `detail`: additional context (e.g., the missing variable name, the line number of the syntax error)

### 5.3 — Shadow mode

**FB-AC-09.09.06**: The system SHALL support **shadow mode** for prompt versions. When a prompt version is running in shadow mode:
1. For every turn, the active (production) prompt processes the input normally.
2. The shadow prompt version processes the SAME input with the SAME variables.
3. Only the production output is delivered to the player.
4. The shadow output is logged to Langfuse with tag `shadow` and linked to the same turn trace.
5. No game state mutation occurs from shadow execution.

**FB-AC-09.09.07**: Shadow mode SHALL support running up to 3 shadow versions concurrently alongside the active version. Each shadow version SHALL have its own Langfuse trace within the same turn, tagged with `prompt_version` and `shadow`.

**FB-AC-09.09.08**: Shadow mode results SHALL be included in the metrics aggregation (FB-AC-09.07.03) with a `shadow=true` flag for separate analysis.

**FB-AC-09.09.09**: If shadow execution raises an exception, it SHALL be logged but MUST NOT affect the production pipeline or the player experience. Shadow errors are silently swallowed with a warning log.

### 5.4 — Registration API

**FB-AC-09.09.10**: The system SHALL expose a `POST /admin/prompts/register` endpoint that accepts a complete prompt file (YAML front matter + body) and:
1. Parses and validates the file
2. If valid, creates a new `Draft` version in the version store
3. Returns the assigned version number and prompt metadata
4. If invalid, returns structured validation errors (per FB-AC-09.09.05)

**FB-AC-09.09.11**: The registration endpoint SHALL detect duplicate version numbers for the same prompt ID and auto-increment the PATCH version unless the caller explicitly specifies a version.

---

## 7 — Implementation Guidance

### 6.1 — Version store backing

The version store can use either:
- **PostgreSQL JSONB** (preferred): Table `prompt_versions` with columns `id`, `prompt_id`, `version`, `status`, `metadata` (JSONB), `body` (TEXT), `created_at`, `activated_at`. The `metadata` column stores parameters, variables, fragments list, etc.
- **Redis** (acceptable for smaller deployments): Hash keyed by `prompt:version:{prompt_id}:{version}` with a sorted set for active version resolution.

Migration from the current file-based `FilePromptRegistry`:
1. Phase 1: `FilePromptRegistry` loads files into the version store on startup (existing behavior + store write)
2. Phase 2: Add version store `get()` fallback when file not found
3. Phase 3: Runtime `activate()` writes to version store, bypassing file system
4. Phase 4: File watching watches `.prompt.md` changes and auto-registers new versions

### 6.2 — Genre pack resolution order

When a session requests prompt rendering:
```
1. Resolve prompt template ID + version from registry
2. Resolve session's active genre pack from content asset registry
3. Inject genre pack variables into template variable map
4. Render template with combined variables + genre pack content
```

### 6.3 — Shadow mode concurrency

Shadow mode uses the same LLM client (S07) but with non-blocking execution. The turn processing pipeline (S08) SHALL fire production and shadow LLM calls concurrently where possible to avoid increasing player-facing latency. Production call results are streamed immediately; shadow results are collected asynchronously.

### 6.4 — Langfuse trace hierarchy for shadow mode

```
Turn N (production trace)
├── Generation: narrative.generate@1.2.0 (active)
└── ← linked via session_id + turn_id

Turn N (shadow trace) — same session_id, different trace_id
├── Generation: narrative.generate@1.3.0-rc1 (shadow)
└── metadata: { shadow: true }
```

### 6.5 — Migration path from current FilePromptRegistry

| Step | What changes | ACs unblocked |
|---|---|---|
| 1 | Add version store table; seed from file loader | — (infra) |
| 2 | `PromptRegistry` protocol gets `activate`/`history`/`rollback` | AC-09.02 |
| 3 | Runtime API endpoints for activation | AC-09.02 |
| 4 | Genre pack format defined; loader built | AC-09.06 |
| 5 | Genre pack variables injected into standard pipeline variables | AC-09.06 |
| 6 | metrics aggregation job + DB table | AC-09.07 |
| 7 | Regression detection logic | AC-09.07 |
| 8 | Preview endpoint + shadow mode pipeline hooks | AC-09.09 |
| 9 | Registration endpoint + validation | AC-09.09 |

---

## 8 — Rationale

### Why PostgreSQL over Redis for the version store

The version store is write-seldom, read-often. PostgreSQL JSONB provides durability, queryability (can query by `metadata->>author`), and audit trails without additional infrastructure. Redis adds operational complexity (persistence config, eviction policies) for minimal latency gain — prompt resolution is already sub-5ms with JSONB and an index on `prompt_id`.

### Why a separate content asset registry (not the prompt registry)

Genre packs contain multi-file structured content (tone guides, archetypes, location moods) that are referenced individually by prompt templates. Merging them into the prompt registry's flat ID→template mapping would lose the pack structure. A parallel registry with pack-level operations (load, activate, validate) keeps the prompt registry simple.

### Why shadow mode runs alongside production (not ahead-of-time)

Running shadow on real player inputs gives the most realistic evaluation. Synthetic test suites (golden tests, scenario tests from S09 §9.2) catch regressions, but shadow mode catches subtle quality differences that only appear with real-world inputs.

### Why no auto-rollback on metric regression

Auto-rollback risks oscillation if a metric degradation is temporary (e.g., transient LLM API latency spike). Human review is required to distinguish genuine prompt quality regression from infrastructure issues.

---

## 9 — Edge Cases

### EC-FB-01 — Version activation during an active turn
If `activate()` is called while a turn is in the middle of LLM generation, the generation SHALL complete using the version it loaded at start. The new version SHALL apply to the NEXT turn's generation. This prevents mid-response version switching.

### EC-FB-02 — Rollback chain exhaustion
If rollback is called more times than the history stack depth, the system SHALL reject the rollback with an error: "No previous version to roll back to for prompt {prompt_id}".

### EC-FB-03 — Genre pack missing a required tone file
If a genre pack manifest references a tone file that does not exist in the pack directory, the pack SHALL fail to load with a listing of all missing files.

### EC-FB-04 — Shadow mode with very long generation time
If shadow generation significantly exceeds the production generation's latency, the shadow may still be running when the next turn arrives. Shadow mode SHALL have a configurable timeout (default: 30s). If the shadow times out, the shadow result for that turn is discarded and logged as `shadow_timeout`.

### EC-FB-05 — Preview endpoint called with invalid template syntax
The preview endpoint SHALL return a 400 Bad Request with structured validation errors. It SHALL NOT attempt to render invalid templates.

### EC-FB-06 — Prometheus scraping race with metric aggregation
The metrics aggregation job runs on a schedule (default: every 6 hours). If Prometheus (or an equivalent metrics system) also records prompt-level metrics, the two systems may disagree on metric values for the current partial window. The `prompt_metrics` table SHALL only contain complete-day aggregations to avoid this discrepancy.

### EC-FB-07 — Genre pack switching mid-session
If a session's genre pack is changed while the session is active, subsequent turns use the new pack's variables. Prior turn narratives remain unaffected. The session's `genre_tone` variable changes for future renders, which may cause a tonal shift. This is acceptable per EC-09.3.

### EC-FB-08 — Concurrent shadow and preview load on LLM
Shadow mode runs on every turn; preview runs on demand. Both consume LLM API quota and may hit rate limits. The LLM client (S07) SHALL track shadow and preview calls separately in its rate limiter. If the LLM provider enforces a global rate limit, production generations take priority over shadow — shadow calls that would exceed the limit are skipped and logged.

---

## 10 — Acceptance Criteria Summary

### AC-09.02 (Runtime Prompt Registry)
- [ ] FB-AC-09.02.01: Version store persists prompt metadata + body in PostgreSQL/Redis
- [ ] FB-AC-09.02.02: File-based loader seeds the version store at startup
- [ ] FB-AC-09.02.03: Version store supports full registry API (get, list, activate, register, history)
- [ ] FB-AC-09.02.04: activate() takes effect for subsequent get() calls only
- [ ] FB-AC-09.02.05: rollback() restores previous version; 5-deep history maintained
- [ ] FB-AC-09.02.06: Concurrent activations are serialized and logged
- [ ] FB-AC-09.02.07: Activation publishes prompt.version.activated event
- [ ] FB-AC-09.02.08: Every activation/rollback logged with timestamp, actor, version delta
- [ ] FB-AC-09.02.09: Only Testing/Active versions eligible for activation
- [ ] FB-AC-09.02.10: Deprecated versions auto-archive after configurable retention (default 30d)

### AC-09.06 (Content Assets & Genre Packs)
- [ ] FB-AC-09.06.01: Genre pack directory format defined with subdirectories for tones, archetypes, locations, fallbacks
- [ ] FB-AC-09.06.02: pack.json manifest contains id, version, name, genre_tone, required_templates
- [ ] FB-AC-09.06.03: Asset files use YAML front matter + body format with id and version
- [ ] FB-AC-09.06.04: Genre pack loads from configuration, registered in content asset registry
- [ ] FB-AC-09.06.05: Active genre pack selectable per session without restart
- [ ] FB-AC-09.06.06: Pack loading validates required_templates exist in prompt registry
- [ ] FB-AC-09.06.07: Genre pack content injected as standard pipeline variables (genre_tone, genre_tone_guide, etc.)
- [ ] FB-AC-09.06.08: Content assets use semantic versioning
- [ ] FB-AC-09.06.09: Content asset registry supports runtime version activation per asset
- [ ] FB-AC-09.06.10: Up to 3 packs loaded simultaneously; one active per session

### AC-09.07 (Observability)
- [ ] FB-AC-09.07.01: Every Langfuse generation includes prompt_id, prompt_version, fragment_versions, prompt_hash, activation_label
- [ ] FB-AC-09.07.02: Langfuse dataset/trace tags include prompt:{id}:{version}
- [ ] FB-AC-09.07.03: Daily per-version metric aggregation (count, latency, tokens, cost, error rate, quality rejection, player rating)
- [ ] FB-AC-09.07.04: Aggregated metrics stored in PostgreSQL prompt_metrics table
- [ ] FB-AC-09.07.05: Warm-up period (default 100 generations) on new version activation
- [ ] FB-AC-09.07.06: Metric regression detected and alerted (no auto-rollback)
- [ ] FB-AC-09.07.07: Default degradation thresholds defined
- [ ] FB-AC-09.07.08: Admin API endpoint for per-version metric comparison

### AC-09.09 (Authoring Workflow)
- [ ] FB-AC-09.09.01: POST /admin/prompts/preview accepts prompt_id, version, variables, model_override
- [ ] FB-AC-09.09.02: Preview endpoint renders, sends to LLM (temperature=0), returns rendered_prompt + output
- [ ] FB-AC-09.09.03: Preview calls: no session association, no game state mutation, rate-limited separately
- [ ] FB-AC-09.09.04: Registration validates syntax, variables, fragments, output schema, context window fit
- [ ] FB-AC-09.09.05: Validation errors structured with field, message, code, detail
- [ ] FB-AC-09.09.06: Shadow mode: production + shadow process same input; only production output delivered
- [ ] FB-AC-09.09.07: Up to 3 shadow versions concurrently supported
- [ ] FB-AC-09.09.08: Shadow results included in metrics aggregation with shadow=true flag
- [ ] FB-AC-09.09.09: Shadow exceptions logged but never affect production pipeline
- [ ] FB-AC-09.09.10: POST /admin/prompts/register accepts full prompt file, validates, creates Draft version
- [ ] FB-AC-09.09.11: Duplicate versions auto-increment PATCH unless explicitly specified

---

## 11 — Out of Scope

- **Visual prompt editor (web UI)** — CLI and API-based authoring only; deferred to future spec
- **Automatic A/B testing (random cohort assignment)** — Shadow mode is manual; automated A/B requires Q-09.5 resolution
- **Community prompt marketplace** — Genre packs are local files; sharing infra deferred
- **Multi-language genre packs** — Genre packs are single-language; localization deferred
- **Prompt optimization (DSPy, etc.)** — Not covered; manual authoring + testing only
- **Graphical genre pack builder** — File-based format only

---

## 12 — Open Questions

| # | Question | Impact | Resolution needed by |
|---|---|---|---|
| Q-FB-01 | Should the version store use PostgreSQL JSONB or Redis? | Affects deployment complexity and query capability | Before Phase 1 implementation |
| Q-FB-02 | Should genre packs support inheritance (pack A extends pack B)? | Affects pack schema and resolution order | Before genre pack design finalization |
| Q-FB-03 | Should shadow mode results be human-reviewable in a UI? | Affects admin tooling scope for v2 | Before shadow mode implementation |
| Q-FB-04 | Should metrics regression alerts be routed to the same channel as production alerts, or a separate "content quality" channel? | Affects S26 alert routing design | Before FB-AC-09.07.06 implementation |
| Q-FB-05 | How should the version store handle prompt template files deleted from disk after being registered? | Affects version lifecycle and cleanup strategy | Before Phase 3 implementation |

---

## 13 — Appendix: Comparison with S09 Existing ACs

| S09 AC | Status in S09 | FB-005 coverage |
|---|---|---|
| AC-09.02 (registry resolves IDs, multiple versions coexist, activation/rollback audited) | Defined but deferred | Expanded to 10 sub-ACs with version store, event bus, audit, lifecycle enforcement |
| AC-09.06 (genre packs loadable and versioned, include tone/archetypes/location mood/fallbacks, switch without code change) | Defined but deferred | Expanded to 10 sub-ACs with pack format spec, content asset registry, variable injection, multi-pack support |
| AC-09.07 (every generation includes prompt ID/version/fragments, filterable by version, per-version metrics tracked, baseline comparison after warm-up) | Defined but deferred; partial Langfuse integration exists | Expanded to 8 sub-ACs with formalized observability contract, metric aggregation table, regression detection thresholds |
| AC-09.09 (interactive preview, shadow mode, registration validation, clear errors) | Defined but deferred | Expanded to 11 sub-ACs with preview API, shadow mode concurrency model, structured validation errors, registration API |

SPEC_WRITE_OK
