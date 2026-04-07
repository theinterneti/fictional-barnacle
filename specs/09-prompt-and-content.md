# S09 — Prompt & Content Management

> **Status**: 📝 Draft
> **Level**: 2 — AI & Content
> **Dependencies**: S07 (LLM Integration), S08 (Turn Processing Pipeline)
> **Last Updated**: 2026-04-07

## 1 — Purpose

This spec defines how prompts and narrative content assets are authored, versioned, tested, and deployed in TTA.

The old TTA had no prompt management system. Prompts were hardcoded strings scattered across agent implementations. This caused:
- **Invisible changes**: A prompt tweak buried in a code commit could silently change game behavior.
- **No rollback**: Breaking a prompt meant reverting the entire code deploy.
- **No attribution**: When a generation was bad, there was no way to know which prompt version produced it.
- **No authoring workflow**: Non-engineer content authors couldn't contribute to prompts.

This spec treats **prompts as first-class versioned assets** — as important as code, and managed with the same rigor.

### Design values applied

| Value | Implication |
|---|---|
| **Fun** | Prompts directly determine narrative quality. Getting prompts right IS getting the game right. |
| **Coherence** | Prompt changes must be testable to ensure they don't introduce contradictions or tone shifts. |
| **Craftsmanship** | Prompt management is a discipline, not an afterthought. |
| **Openness** | Prompt format should be simple enough for community contributors to author genre packs. |

---

## 2 — User Stories

### US-09.1 — Content author edits a prompt without touching code
> As a **content author**, I want to edit the narrative generation prompt in a human-readable file format, preview the effect, and deploy it — without writing Python or making a code commit.

### US-09.2 — Developer knows which prompt version produced a bad generation
> As a **developer**, when a player reports a weird narrative response, I want to look up exactly which prompt template and version was used to generate it, so I can reproduce and fix the issue.

### US-09.3 — Developer tests a prompt change before deploying
> As a **developer**, I want to run a suite of test scenarios against a modified prompt and compare outputs to a known-good baseline, so I can catch regressions before they reach players.

### US-09.4 — Operator rolls back a prompt change
> As an **operator**, when a new prompt version causes quality degradation, I want to instantly revert to the previous version without a code deploy or restart.

### US-09.5 — Author creates a genre pack
> As a **content author**, I want to create a "noir detective" genre pack that includes tone templates, NPC archetypes, and style guidance, so the game can run in that genre without rewriting the core prompts.

### US-09.6 — Developer composes prompts from reusable fragments
> As a **developer**, I want to build complex prompts from smaller, reusable pieces (safety preamble + genre tone + task instructions + output format) so that changes to shared components propagate everywhere.

### US-09.7 — Developer understands what variables a prompt expects
> As a **developer**, I want each prompt template to clearly declare what variables it needs (player name, location, inventory, etc.) so that I get an error at assembly time — not a confusing generation — if a variable is missing.

---

## 3 — Prompt as Code

### 3.1 — Prompts are versioned assets

**FR-09.01**: All prompts used by TTA SHALL be stored as versioned files in the repository (or a dedicated prompt store), not as inline strings in source code.

**FR-09.02**: Each prompt file SHALL contain:
- A unique identifier (slug).
- A semantic version number.
- The prompt template text with variable placeholders.
- Metadata: model role, author, description, creation date, last-modified date.
- Generation parameter overrides (temperature, max_tokens, etc.) if different from the role defaults.
- A declared list of required variables.
- An optional output schema (for structured output prompts).

**FR-09.03**: Prompt files SHALL use a human-readable format (YAML front matter + markdown body, or equivalent). The format must be editable with a text editor — no binary formats, no IDE requirement.

### 3.2 — Example prompt file

```yaml
---
id: narrative-generation-v1
version: 2.3.0
role: generation
author: content-team
description: >
  Main narrative generation prompt. Produces prose in response to
  player action, grounded in world context.
created: 2025-06-15
updated: 2025-07-20
parameters:
  temperature: 0.85
  max_tokens: 1024
  frequency_penalty: 0.3
variables:
  required:
    - player_name
    - location_description
    - player_action
    - nearby_npcs
    - inventory_summary
    - recent_events
    - genre_tone
  optional:
    - suggested_direction
    - emotional_context
output_schema: null  # free-form text, no structured output
---

# System Prompt

You are the narrator of a {{genre_tone}} text adventure game.

## World Context
The player, {{player_name}}, is currently in: {{location_description}}

### Nearby Characters
{{nearby_npcs}}

### Player's Inventory
{{inventory_summary}}

### Recent Events
{{recent_events}}

## Player's Action
The player says: "{{player_action}}"

## Your Task
Write the next part of the story (150-300 words). Rules:
- Respond to the player's action directly.
- Stay consistent with the world context above.
- Do not reference items, characters, or places not mentioned in the context.
- Match the {{genre_tone}} tone.
- End with the scene in a state where the player can act again.
{{#if emotional_context}}
- The player seems {{emotional_context}}. Adjust your tone accordingly.
{{/if}}
```

### 3.3 — No inline prompts

**FR-09.04**: Source code SHALL NOT contain prompt text longer than one sentence. All multi-line prompts SHALL be loaded from the prompt registry at runtime.

**FR-09.05**: The system SHALL fail loudly at startup if a required prompt template is missing from the registry.

---

## 4 — Prompt Registry

### 4.1 — Registry behavior

The prompt registry is the single source of truth for prompt resolution at runtime.

> **Implementation note (non-normative):** Langfuse's prompt management supports the versioning, label-based activation (e.g. "production"), rollback, diffing, and tracing linkage required by this spec. It is open-source and self-hostable. The spec defines a **Prompt Registry interface** — Langfuse is a suitable backing implementation, but any system satisfying these operations is acceptable.

**FR-09.06**: The system SHALL maintain a prompt registry that maps prompt IDs to their current active version.

**FR-09.07**: Given a prompt ID (e.g. `narrative-generation-v1`), the registry SHALL return the active version of that prompt template with all metadata.

**FR-09.08**: The registry SHALL support multiple versions of the same prompt existing simultaneously. Only one version is "active" (the default). Other versions are available for testing, rollback, and comparison.

**FR-09.09**: Activating a different version of a prompt SHALL be a runtime operation — no code deploy, no process restart.

### 4.2 — Registry operations

| Operation | Description | Access |
|---|---|---|
| `get(prompt_id)` | Return the active version of the prompt | All pipeline stages |
| `get(prompt_id, version)` | Return a specific version | Testing, debugging |
| `list()` | List all registered prompt IDs and their active versions | Admin, tooling |
| `activate(prompt_id, version)` | Set a version as active | Operator, CI/CD |
| `register(prompt_file)` | Add a new prompt or version to the registry | Author, CI/CD |
| `history(prompt_id)` | Return version history with activation timestamps | Debugging, audit |

**FR-09.10**: The `activate` operation SHALL be audited — the system records who activated which version and when.

**FR-09.11**: The registry SHALL support a `rollback(prompt_id)` operation that reactivates the previously active version.

---

## 5 — Prompt Versioning

### 5.1 — Version scheme

**FR-09.12**: Prompts SHALL use semantic versioning (MAJOR.MINOR.PATCH):
- **MAJOR**: Breaking change — the prompt expects different variables, produces different output structure, or fundamentally changes behavior.
- **MINOR**: Behavioral change — the prompt produces noticeably different output quality or style, but the interface (variables, output format) is unchanged.
- **PATCH**: Non-functional change — typo fixes, wording refinements that don't materially change output.

#### 5.1.1 — Prompt execution artifact

A **prompt execution artifact** is the immutable bundle that the pipeline (S08) uses for a given turn. It pins:

| Component | Description |
|---|---|
| `prompt_version_id` | Exact version of the root template (e.g. `narrative.generate@2.3.1`) |
| `fragment_versions` | Map of fragment slug → version for every included fragment |
| `variable_schema` | The required/optional variables at the time of activation |
| `output_schema` | JSON Schema or structured-output type the caller expects (see FR-09.02) |
| `activation_label` | The label (e.g. `production`) that resolved to this bundle |

When S07 or S08 reference "the prompt version used for this turn", they mean this artifact. The registry SHOULD be able to reconstruct the exact artifact for any past turn from the version IDs recorded in the Langfuse trace (per FR-09.40).

### 5.2 — Version lifecycle

```
Draft  →  Testing  →  Active  →  Deprecated  →  Archived
                        ↑ rollback ↓
                       Previous
```

**FR-09.13**: New prompt versions SHALL start in `Draft` status and cannot be activated until they pass testing.

**FR-09.14**: Only one version per prompt ID SHALL be in `Active` status at any time.

**FR-09.15**: When a new version is activated, the previous active version SHALL move to `Deprecated` status (still available for rollback) for a configurable retention period (default: 30 days), after which it moves to `Archived`.

### 5.3 — Migration on breaking changes

**FR-09.16**: When a prompt's MAJOR version changes (new required variables, different output schema), the system SHALL validate at registration time that all callers can provide the new required variables. If validation fails, the version cannot be activated.

---

## 6 — Template Variables

### 6.1 — Variable injection

**FR-09.17**: Prompt templates SHALL use a simple, well-defined template syntax for variable injection. The syntax SHALL support:
- Simple substitution: `{{variable_name}}`
- Conditional sections: `{{#if variable_name}} ... {{/if}}`
- Iteration: `{{#each list_variable}} ... {{/each}}`
- Default values: `{{variable_name | default: "none"}}`

**FR-09.18**: The system SHALL validate at template render time that all required variables are provided. Missing required variables SHALL cause a clear error (not a silent empty string).

**FR-09.19**: The system SHALL sanitize injected variables to prevent prompt injection. Variable values SHALL NOT be able to contain template syntax that gets interpreted (no meta-injection).

### 6.2 — Standard variable catalog

The pipeline provides these standard variables to prompt templates:

| Variable | Type | Source | Description |
|---|---|---|---|
| `player_name` | string | Player data | The player's character name |
| `player_action` | string | Understanding (Stage 1) | The player's input, possibly cleaned up |
| `player_intent` | string | Understanding (Stage 1) | Classified intent |
| `emotional_tone` | string | Understanding (Stage 1) | Detected emotional register |
| `location_description` | string | Context (Stage 2) | Current location prose description |
| `location_name` | string | Context (Stage 2) | Current location name |
| `nearby_npcs` | string | Context (Stage 2) | Formatted list of NPCs present |
| `nearby_objects` | string | Context (Stage 2) | Formatted list of interactable objects |
| `inventory_summary` | string | Context (Stage 2) | Formatted list of player's items |
| `recent_events` | string | Context (Stage 2) | Summary of recent session events |
| `conversation_history` | string | Context (Stage 2) | Recent exchange log |
| `active_quests` | string | Context (Stage 2) | Current objectives |
| `world_time` | string | Context (Stage 2) | In-game time/weather |
| `character_state` | string | Context (Stage 2) | Player character physical/emotional state |
| `genre_tone` | string | Session config | Genre and tone directive |
| `turn_number` | integer | Turn metadata | Current turn count |

**FR-09.20**: This catalog SHALL be documented and kept in sync with the pipeline's actual variable resolution. New variables require a catalog update.

**FR-09.21**: Prompt templates SHALL declare which variables they use from the catalog. Unused variables are not injected (saves tokens).

---

## 7 — Prompt Composition

### 7.1 — Fragment-based composition

Complex prompts are assembled from smaller, reusable fragments:

```
┌─────────────────────────────────────────────────────┐
│               Final Assembled Prompt                │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │
│  │   Safety    │  │   Genre     │  │   Task     │  │
│  │  Preamble   │  │   Tone      │  │ Instructions│  │
│  │ (shared)    │  │ (per-genre) │  │ (per-task)  │  │
│  └─────────────┘  └─────────────┘  └────────────┘  │
│                                                     │
│  ┌─────────────┐  ┌─────────────────────────────┐  │
│  │  Output     │  │        Context              │  │
│  │  Format     │  │    (injected variables)      │  │
│  │ (per-task)  │  │                             │  │
│  └─────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**FR-09.22**: The system SHALL support prompt composition via named fragments. A prompt template MAY include other fragments by reference: `{{> fragment_name}}`.

**FR-09.23**: Fragments SHALL be independently versioned. Updating a shared fragment (e.g. the safety preamble) automatically updates all prompts that include it — but the system SHALL log which prompts are affected.

**FR-09.24**: Circular fragment references SHALL be detected at registration time and rejected.

**FR-09.25**: The final assembled prompt (after all fragments are resolved and variables injected) SHALL be the version recorded in Langfuse, so that debugging sees exactly what the model received.

### 7.2 — Composition order

When a prompt is assembled, fragments are resolved in this order:
1. **Safety preamble** (always first — never overridden by other fragments).
2. **Genre tone** (establishes the narrative style).
3. **Task instructions** (what the model should do this call).
4. **Output format** (structured output schema or prose guidelines).
5. **Context** (injected variables with world state, history, etc.).

**FR-09.26**: The safety preamble SHALL always be the first content in the system message. No fragment or variable injection can precede it.

---

## 8 — Content Assets

### 8.1 — Non-prompt narrative content

Beyond prompts, TTA uses narrative content assets that shape the game experience:

| Asset type | Description | Example |
|---|---|---|
| **Genre pack** | A collection of tone templates, vocabulary guidance, and narrative conventions | "Noir Detective", "Cozy Fantasy", "Cosmic Horror" |
| **NPC archetype** | Personality template for NPC generation | "Wise Mentor", "Trickster", "Reluctant Ally" |
| **Location template** | Atmosphere and description patterns for location types | "Tavern", "Dark Forest", "Ancient Ruin" |
| **Tone guide** | Writing style directives (sentence length, vocabulary level, mood) | "Whimsical", "Gritty", "Literary" |
| **Fallback responses** | Pre-written responses for error scenarios | "The story pauses…", "You can't do that right now." |

**FR-09.27**: Content assets SHALL follow the same versioning and registry pattern as prompts. They are loaded by ID, versioned, and auditable.

**FR-09.28**: Genre packs SHALL be self-contained — a genre pack includes all the tone guides, archetypes, and templates needed to run the game in that genre. The core prompts reference genre pack content via variables.

### 8.2 — Genre pack structure

```yaml
---
id: genre-noir
version: 1.0.0
name: "Noir Detective"
author: content-team
description: "Hard-boiled detective fiction with moral ambiguity"
---

tone:
  vocabulary: "terse, world-weary, metaphor-heavy"
  sentence_style: "short, punchy sentences. Occasional long noir monologue."
  mood: "cynical, atmospheric, rain-soaked"
  humor: "dry, dark"
  violence: "implied, never graphic"

narrative_rules:
  - "Every NPC has a secret"
  - "Trust is currency — everyone wants something"
  - "Weather reflects mood"
  - "Night is more interesting than day"

npc_archetypes:
  - name: "Femme Fatale"
    traits: "mysterious, alluring, dangerous, always knows more than she lets on"
    speech_pattern: "speaks in half-truths, uses double entendres"
  - name: "World-Weary Cop"
    traits: "disillusioned, alcoholic, surprisingly moral core"
    speech_pattern: "clipped sentences, avoids eye contact in conversation"

location_moods:
  bar: "smoke-filled, jazz on the jukebox, a drink you didn't order"
  street: "wet pavement, neon reflections, shadows that move wrong"
  office: "venetian blinds, dust motes, a phone that might ring"

fallback_responses:
  thinking: "You light a cigarette and think it over."
  cant_do_that: "Some doors stay closed, pal."
  error: "The rain picks up. You lose your train of thought."
```

---

## 9 — Prompt Testing

### 9.1 — Why prompts need tests

A prompt change that looks minor ("adjusted wording") can dramatically alter model behavior. TTA treats prompt testing with the same seriousness as code testing.

### 9.2 — Test strategies

#### Golden tests

**FR-09.29**: The system SHALL support **golden tests** for prompts. A golden test consists of:
1. A specific prompt version.
2. A fixed set of input variables.
3. A recorded "golden" output (the expected response).
4. Evaluation criteria (see §9.3).

**FR-09.30**: When a prompt is modified, golden tests SHALL be re-run. If the new output deviates from the golden output beyond the configured tolerance, the test fails and the author must review the change.

**FR-09.31**: Golden tests SHALL use deterministic generation settings (temperature = 0, fixed seed where supported) to minimize non-determinism. The system SHALL acknowledge that even with these settings, LLM outputs are not perfectly reproducible and SHALL allow configurable tolerance.

#### Scenario tests

**FR-09.32**: The system SHALL support **scenario tests** — predefined player inputs with specific world states, where the expected behavior is described as assertions rather than exact text. Example:

```yaml
scenario: "Player tries to open locked door without key"
input:
  player_action: "I try to open the door"
  location: "castle_entrance"
  inventory: ["torch", "map"]  # no key
assertions:
  - response_contains_any: ["locked", "won't budge", "need a key"]
  - response_not_contains: ["door opens", "you enter"]
  - tone_matches: "genre_tone"
  - length_between: [50, 300]
```

**FR-09.33**: Scenario tests SHALL be runnable against any prompt version, enabling A/B comparison between the current and proposed versions.

#### Regression tests

**FR-09.34**: The system SHALL maintain a regression test suite of known-problematic scenarios — cases where previous prompt versions produced bad output. New prompt versions MUST pass all regression tests.

### 9.3 — Evaluation criteria

Prompt test evaluation goes beyond string matching:

| Criterion | Method | Applicable to |
|---|---|---|
| **Contains / not-contains** | Substring matching | All prompt types |
| **JSON schema validation** | Schema check | Structured output prompts |
| **Length bounds** | Word/char count | Generation prompts |
| **Tone consistency** | LLM-as-judge or keyword analysis | Generation prompts |
| **Factual grounding** | Check that response only references provided context | Generation prompts |
| **Intent preservation** | Classified intent of response matches expected | Classification prompts |
| **Human review** | Author reviews flagged outputs | Any (manual gate) |

**FR-09.35**: Evaluation criteria SHALL be defined per prompt template, not globally. A classification prompt needs schema validation; a generation prompt needs tone and grounding checks.

---

## 10 — Prompt Observability

### 10.1 — Prompt-to-generation linkage

**FR-09.36**: Every LLM generation event in Langfuse SHALL include:
- The prompt template ID.
- The prompt template version.
- The fragment versions included (if composition was used).
- A hash of the final assembled prompt (after variable injection).

**FR-09.37**: Langfuse SHALL support filtering generations by prompt version, enabling a developer to see "all generations from `narrative-generation-v1` version 2.3.0 in the last 24 hours".

### 10.2 — Prompt performance tracking

**FR-09.38**: The system SHALL track per-prompt-version metrics:
- Average generation quality (if rated by players or automated evaluation).
- Average generation latency.
- Average token count (input + output).
- Average cost.
- Error rate (how often this prompt triggers fallback, quality rejection, or structured output parse failure).

**FR-09.39**: When a new prompt version is activated, the system SHALL automatically compare its metrics against the previous version's baseline after a configurable warm-up period (default: 100 generations). If the new version performs significantly worse on any metric, the system SHALL alert the operator.

---

## 11 — Prompt Authoring Workflow

### 11.1 — Authoring lifecycle

```
 1. Author creates/edits prompt file
          │
          ▼
 2. Prompt is validated (syntax, variables, fragments)
          │
          ▼
 3. Prompt is registered as a new Draft version
          │
          ▼
 4. Author runs scenario tests and golden tests
          │
          ▼
 5. Author runs interactive preview (sends test inputs, sees outputs)
          │
          ▼
 6. Author (or reviewer) approves the version → status: Testing
          │
          ▼
 7. Version runs in shadow mode (processes real inputs but doesn't serve to players)
          │
          ▼
 8. After validation, operator activates the version → status: Active
          │
          ▼
 9. System monitors metrics; auto-alerts on regression
```

**FR-09.40**: The system SHALL support an **interactive preview mode** where an author can submit test inputs with specific context variables and see the LLM output, without affecting any live sessions.

**FR-09.41**: The system SHALL support **shadow mode** — a new prompt version processes real turn inputs alongside the active version, but only the active version's output is delivered to the player. Shadow outputs are logged for comparison.

**FR-09.42**: Shadow mode results SHALL be stored with the prompt version for A/B analysis before activation.

### 11.2 — Validation at registration

**FR-09.43**: When a prompt is registered, the system SHALL validate:
- Template syntax is correct (no unclosed tags, valid fragment references).
- All required variables are declared in the variable list.
- All referenced fragments exist in the registry.
- If an output schema is specified, it is valid JSON Schema.
- The prompt + typical context fits within the target model's context window (estimated).

**FR-09.44**: Validation failures SHALL produce clear, actionable error messages (e.g. "Variable `player_name` used in template but not declared in `variables.required`").

---

## 12 — Guardrails

### 12.1 — Prompt-level content guidelines

This is NOT a full safety system (that's future S19). These are baseline guardrails built into the prompt layer.

**FR-09.45**: Every prompt that generates player-facing content SHALL include a safety preamble fragment. This fragment contains baseline content guidelines:
- No graphic violence, sexual content, or self-harm encouragement.
- No real-world medical, legal, or financial advice.
- No content that could be mistaken for real-world emergency communication.
- Respect the player's emotional state (if detected by the pipeline).

**FR-09.46**: The safety preamble SHALL be a shared fragment (see §7) so that updates to content guidelines propagate to all prompts automatically.

**FR-09.47**: The safety preamble SHALL be immutable by prompt authors — it cannot be overridden, removed, or weakened by task-specific prompt templates.

**FR-09.48**: If the system detects that a generated response may violate content guidelines (via keyword detection or a classification call), the response SHALL be intercepted before delivery and replaced with a safe alternative. The interception SHALL be logged with the original response for review.

### 12.2 — Prompt injection defense

**FR-09.49**: Variable values injected into prompts SHALL be treated as untrusted input. The system SHALL defend against prompt injection by:
- Clearly delineating system instructions from user-provided content in the message structure (system message vs. user message).
- Never including raw player input in the system message — player input goes in the user message.
- Logging and flagging inputs that appear to contain injection attempts (e.g. "ignore previous instructions", "you are now", "system:").

**FR-09.50**: Detected prompt injection attempts SHALL NOT block the turn (false positives are too costly for player experience) but SHALL be logged as a security event with the raw input for review.

---

## 13 — Edge Cases

### EC-09.1 — Prompt template references a deleted fragment
The system should detect this at registration time (FR-09.43) and reject the prompt. If a fragment is deleted while prompts reference it, the deletion should be blocked or at minimum a warning issued listing affected prompts.

### EC-09.2 — Variable contains template syntax
Player names like "{{admin}}" or NPC dialogue containing "{{#if}}" could be interpreted as template syntax. FR-09.19 requires sanitization — variable values must be treated as literal strings, never interpreted as template directives.

### EC-09.3 — Prompt version rollback during active sessions
If a prompt is rolled back while sessions are in progress, currently-processing turns may use the new (rolled-back) version while previous turns used the now-deprecated version. This is acceptable — prompt version changes apply to new LLM calls, not retroactively. The session's narrative may shift slightly in style, which is preferable to interrupting the session.

### EC-09.4 — Genre pack conflicts with safety preamble
A genre pack says "describe violence graphically" but the safety preamble says "no graphic violence". The safety preamble wins — it is always the first and highest-priority content in the prompt (FR-09.47). Genre pack content is additive, never overriding safety constraints.

### EC-09.5 — Very long variable values exceed token budget
A player with 50 inventory items might produce an `inventory_summary` variable that's 2000 tokens. The prompt template should use the token-budgeted version of variables (truncated per S07 §5 priority tiers), not raw values. Context assembly (S08 §5) handles truncation before variables reach the prompt template.

### EC-09.6 — Author creates a prompt with no required variables
Valid edge case — some prompts (e.g. a pure system prompt for classification) may not need injected variables. The system should accept this but warn if the prompt is registered for a role that typically uses variables.

### EC-09.7 — Two authors activate different versions simultaneously
The `activate` operation must be atomic. If two authors try to activate different versions of the same prompt concurrently, one wins (last-write-wins), and both activations are logged. The system should not enter an inconsistent state.

### EC-09.8 — Golden test with non-deterministic LLM output
Even with temperature=0 and fixed seeds, LLM outputs vary across API calls, model updates, and providers. Golden tests should use fuzzy matching (semantic similarity or structural assertions) rather than exact string equality. The configurable tolerance (FR-09.31) accounts for this.

### EC-09.9 — Valid prompt template produces empty output for certain variable combinations
A prompt template is syntactically valid and passes registration checks, but certain rare variable combinations (e.g. empty `nearby_npcs`, no `active_quests`, minimal `location_description`) cause the model to produce empty or very short output. The system SHOULD treat this as a generation quality issue (per S08 §6.5 FR-08.22) and retry. Prompt authors SHOULD include scenario tests covering minimal-context combinations.

### EC-09.10 — Fragment update propagates to many dependent prompts
Updating a shared fragment (e.g. the safety preamble) triggers re-validation of all prompts that include it. If dozens of prompts reference the same fragment, the system SHOULD batch-validate affected prompts and report all failures, not fail on the first. The system SHOULD log which prompts are affected by the update (per FR-09.23).

### EC-09.11 — Prompt version and output schema drift across S07/S08
A prompt template declares an output schema (FR-09.02), but the downstream consumer (e.g. S08's Input Understanding expecting a specific Understanding object shape) evolves independently. The system SHOULD validate at registration time that the prompt's declared output schema remains compatible with the consuming pipeline stage's expected input schema.

---

## 14 — Acceptance Criteria

### AC-09.1 — Prompts as versioned assets
- [ ] All prompts are stored as files, not inline code strings.
- [ ] Each prompt has a unique ID, semantic version, and declared variables.
- [ ] Prompt files are human-readable and editable with a text editor.
- [ ] The system refuses to start if a required prompt is missing.

### AC-09.2 — Prompt registry
- [ ] The registry resolves prompt IDs to active versions at runtime.
- [ ] Multiple versions of a prompt can coexist; only one is active.
- [ ] Activation and rollback are runtime operations — no code deploy needed.
- [ ] All activation/rollback events are audited.

### AC-09.3 — Template variables
- [ ] Variables are injected correctly at render time.
- [ ] Missing required variables cause a clear error, not silent empty strings.
- [ ] Variable sanitization prevents prompt injection via template syntax in values.
- [ ] The variable catalog is documented and stays in sync with the pipeline.

### AC-09.4 — Prompt composition
- [ ] Prompts can include shared fragments by reference.
- [ ] Updating a fragment affects all prompts that include it.
- [ ] Circular references are detected and rejected.
- [ ] The final assembled prompt (post-composition, post-injection) is what gets logged.

### AC-09.5 — Prompt testing
- [ ] Golden tests detect unintended output changes from prompt modifications.
- [ ] Scenario tests validate behavioral assertions (contains, not-contains, length, tone).
- [ ] Regression tests cover known-bad scenarios.
- [ ] Tests run with deterministic settings where possible.

### AC-09.6 — Content assets
- [ ] Genre packs are loadable and versioned.
- [ ] Genre packs include tone, archetypes, location moods, and fallback responses.
- [ ] Switching genres is a configuration change, not a code change.

### AC-09.7 — Observability
- [ ] Every generation in Langfuse includes the prompt template ID, version, and fragment versions.
- [ ] Generations are filterable by prompt version.
- [ ] Per-version metrics (quality, latency, cost, error rate) are tracked.
- [ ] New version activation triggers automatic baseline comparison after warm-up.

### AC-09.8 — Guardrails
- [ ] Every player-facing prompt includes the safety preamble.
- [ ] The safety preamble cannot be removed or overridden by prompt authors.
- [ ] Player input is never in the system message — always in the user message.
- [ ] Suspected prompt injection is logged but does not block the turn.

### AC-09.9 — Authoring workflow
- [ ] Authors can preview prompt output interactively.
- [ ] Shadow mode allows new versions to process real inputs without serving to players.
- [ ] Registration validates syntax, variables, fragments, and estimated token fit.
- [ ] Validation errors are clear and actionable.

---

## 15 — Out of Scope

The following are explicitly NOT covered by this spec:

- **Visual prompt editor (web UI)** — A graphical tool for authoring and previewing prompts. — Open question Q-09.2; file-based editing is sufficient for v1.
- **Localization and multi-language prompt variants** — Translating prompt templates into multiple languages. — Deferred; the pipeline operates in one configured language per session. See Q-09.6.
- **Automated prompt optimization (DSPy, etc.)** — ML-driven prompt tuning or auto-optimization. — Out of scope; the spec covers manual authoring and testing.
- **Community prompt marketplace** — A sharing or exchange system for user-created genre packs or prompt templates. — Not planned for v1.
- **Full content moderation and safety system** — Baseline guardrails are defined in §12 (Safety Constraints). A dedicated safety layer is a separate concern. — See future S19.
- **Prompt execution and LLM dispatch** — The registry stores and resolves prompts; execution is the responsibility of S07 (LLM Integration) and S08 (Turn Processing Pipeline).
- **Fine-tuning or LoRA adaptation** — Model training is outside the prompt content layer. — See S07 §15.

---

## 16 — Open Questions

| # | Question | Impact | Resolution needed by |
|---|---|---|---|
| Q-09.1 | Should prompt files live in the main repo, a separate content repo, or a database? | Affects authoring workflow and deployment pipeline | Before implementation |
| Q-09.2 | Do we need a visual prompt editor (web UI) or is file editing sufficient for v1? | Affects tooling investment and content author accessibility | Before content author onboarding |
| Q-09.3 | How does prompt versioning interact with game save/load? If a player loads a save from last week, should the game use the current prompts or the prompts from when the save was created? | Affects save format and prompt registry design | Before save/load feature |
| Q-09.4 | Should genre packs be community-contributed? If so, what review/safety process is needed? | Affects content pipeline and moderation needs | Before community launch |
| Q-09.5 | How should prompt A/B testing work at scale? Random assignment? Player cohorts? | Affects prompt versioning infrastructure | Before optimization phase |
| Q-09.6 | Should prompts support localization (multiple languages)? | Major scope increase if yes | Before internationalization planning |

---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| **Prompt template** | A versioned file containing prompt text with variable placeholders and metadata. |
| **Fragment** | A reusable piece of prompt text that can be included in multiple templates. |
| **Prompt registry** | The runtime system that maps prompt IDs to their active versions. |
| **Golden test** | A test comparing LLM output against a recorded baseline for regression detection. |
| **Scenario test** | A test defining input conditions and behavioral assertions (not exact output matching). |
| **Genre pack** | A collection of tone, archetype, and style assets that configure the game's narrative flavor. |
| **Shadow mode** | Running a new prompt version against real inputs without serving its output to players. |
| **Safety preamble** | A shared, immutable prompt fragment containing baseline content safety guidelines. |

## Appendix B — Prompt Template Syntax Quick Reference

| Syntax | Purpose | Example |
|---|---|---|
| `{{var}}` | Simple variable substitution | `{{player_name}}` |
| `{{var \| default: "x"}}` | Variable with default value | `{{mood \| default: "neutral"}}` |
| `{{#if var}} ... {{/if}}` | Conditional section | `{{#if quest}} Current quest: {{quest}} {{/if}}` |
| `{{#each list}} ... {{/each}}` | Iteration over list | `{{#each npcs}} - {{name}}: {{desc}} {{/each}}` |
| `{{> fragment_id}}` | Include a named fragment | `{{> safety-preamble}}` |
| `{{!-- comment --}}` | Template comment (stripped from output) | `{{!-- TODO: refine tone --}}` |
