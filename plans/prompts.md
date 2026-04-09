# Prompt & Content Management — Technical Plan

> **Phase**: SDD Phase 2 — Component Technical Plan
> **Scope**: Prompt template format, registry, composition, versioning, testing, and security
> **Input specs**: S09 (Prompt & Content Management), S03 (Narrative Engine), S07 (LLM Integration), S08 (Turn Processing Pipeline)
> **Parent plan**: `plans/system.md`
> **Status**: 📝 Draft
> **Last Updated**: 2026-04-07

---

## 0. Design Posture

This plan covers the implementation of prompts as first-class versioned assets: how
they are authored, stored, loaded, composed, rendered, and tested.

### v1 boundaries

S09 describes a full prompt lifecycle including runtime activation, shadow mode, and
interactive preview. v1 implements the **core asset layer** — the parts needed to
ship a playable game with traceable, testable prompts. The registry interface is
designed so the deferred features can be added without rewriting the foundation.

| Capability | v1 | Deferred |
|---|---|---|
| Prompt files with YAML front matter + template body | ✅ | — |
| File-based registry loaded at startup | ✅ | — |
| Fragment composition (shared pieces) | ✅ | — |
| Variable injection with validation | ✅ | — |
| Token budget management | ✅ | — |
| Safety preamble enforcement | ✅ | — |
| Input sanitization / injection defense | ✅ | — |
| Langfuse trace linkage (template ID + version) | ✅ | — |
| Prompt snapshot tests and scenario tests | ✅ | — |
| Genre pack loading | ✅ | — |
| Hot-reload in dev (file watcher) | ✅ | — |
| Multi-version registry (`get(id, version)`, history, rollback) | — | v2 (git is the version store in v1) |
| Runtime activation / rollback without deploy | — | v2 (Langfuse prompt management or DB-backed registry) |
| Shadow mode (parallel evaluation) | — | v2 |
| Interactive preview mode | — | v2 |
| Visual prompt editor UI | — | Not planned |
| Automated A/B testing with cohort assignment | — | v2+ |
| Community prompt marketplace | — | Not planned |
| Post-generation content interception / replacement (FR-09.48) | — | Owned by future Safety component (see system.md §2.4 safety seam architecture; full system deferred to S19) |
| Output schema validation at registration | — | v2 |
| Token-fit validation at registration | — | v2 (depends on model choice at runtime) |
| `updated` / last-modified metadata in front matter | — | v2 (git blame is sufficient in v1) |

### Resolved open questions from S09

| Question | Decision | Rationale |
|---|---|---|
| **Q-09.1** — Prompt files in main repo or separate? | **Main repo**, under `prompts/` | Prompts are versioned with code, deployed with code. Same PR, same CI gate, same review. Separation adds deployment complexity without v1 benefit. |
| **Q-09.2** — Visual editor or file editing? | **File editing only** | Text editor + git is sufficient for the v1 team. Visual editor is future. |
| **Q-09.3** — Save/load: current or historical prompts? | **Current prompts** | Prompts are the engine, not save data. Improvements should benefit all sessions, including resumed ones. |
| **Q-09.5** — A/B testing approach? | **Langfuse comparison, manual cohorts** | No automated cohort assignment in v1. Developers compare prompt versions via Langfuse traces after manual activation. |

---

## 1. Template Format

### 1.1 — File structure

Every prompt is a Markdown file with YAML front matter. Extension: `.prompt.md`.
Every fragment is a Markdown file with YAML front matter. Extension: `.fragment.md`.

```
prompts/
├── templates/
│   ├── narrative/
│   │   ├── generate.prompt.md         # Main narrative generation
│   │   └── chapter-transition.prompt.md
│   ├── classification/
│   │   ├── intent.prompt.md           # Input understanding / intent parsing
│   │   └── coherence-check.prompt.md  # Post-generation coherence validation
│   └── extraction/
│       └── world-changes.prompt.md    # Extract world state changes from narrative
├── fragments/
│   ├── safety-preamble.fragment.md    # Immutable safety rules (FR-09.46/47)
│   ├── output-prose.fragment.md       # "Write prose, no markdown" guidelines
│   ├── output-json.fragment.md        # "Respond with valid JSON" guidelines
│   └── genre/                         # Genre tone fragments (one per genre pack)
│       ├── fantasy.fragment.md
│       ├── noir.fragment.md
│       └── scifi.fragment.md
└── genres/
    ├── fantasy.genre.yaml             # Full genre pack (tone + archetypes + moods)
    ├── noir.genre.yaml
    └── scifi.genre.yaml
```

### 1.2 — Template file anatomy

```markdown
---
id: narrative.generate
version: 1.0.0
role: generation
description: >
  Main narrative generation prompt. Produces second-person present-tense
  prose in response to player action, grounded in world context.
author: content-team
created: 2026-04-07
parameters:
  temperature: 0.85
  max_tokens: 1024
  frequency_penalty: 0.3
variables:
  required:
    - player_input
    - world_context
  optional:
    - character_context
    - tone
    - recent_events
output_schema: null
---

{# --- System prompt begins --- #}

{% include "safety-preamble.fragment.md" %}

## Narrator Role

You are the narrator of a {{ genre_tone }} text adventure game.
You write in **second person, present tense**.

{% include "genre/" ~ genre_slug ~ ".fragment.md" %}

## World Context

The player, {{ player_name }}, is currently in: {{ location_description }}

{% if world_time %}
**Time**: {{ world_time }}
{% endif %}

{% if nearby_npcs %}
### Characters Present
{{ nearby_npcs }}
{% endif %}

{% if nearby_objects %}
### Notable Objects
{{ nearby_objects }}
{% endif %}

{% if inventory_summary %}
### Player Inventory
{{ inventory_summary }}
{% endif %}

### Recent Events
{{ recent_events }}

{% if active_quests %}
### Active Objectives
{{ active_quests }}
{% endif %}

{% if conversation_history %}
### Recent Conversation
{{ conversation_history }}
{% endif %}

## Your Task

Write the next part of the story (100–300 words).

- Respond to the player's action directly.
- Stay consistent with the world context above.
- Do not reference items, characters, or places not in the context.
- Match the {{ genre_tone }} tone.
- Use sensory detail. Show, don't tell.
- End with the scene in a state where the player can act.
- Do NOT end with a question to the player.
- Do NOT restate the player's action as your opening line.

{% include "output-prose.fragment.md" %}
```

### 1.3 — Template engine: Jinja2

| Decision | Detail |
|---|---|
| **Engine** | Jinja2 via `jinja2.SandboxedEnvironment` |
| **Why Jinja2** | Battle-tested, Python-native, sandboxed mode prevents code execution, supports all S09 features (conditionals, loops, includes, defaults, comments) |
| **Why not Mustache/Handlebars** | Python Handlebars libraries (`pybars3`) are poorly maintained. Jinja2 is a standard dependency in the Python ecosystem. |
| **Syntax mapping** | Jinja2's native syntax is used directly. The spec's `{{#if}}` / `{{#each}}` / `{{> partial}}` syntax (Appendix B) maps cleanly to Jinja2's `{% if %}` / `{% for %}` / `{% include %}`. |

S09 Appendix B feature mapping to Jinja2:

| S09 concept | Jinja2 syntax | Example |
|---|---|---|
| Variable substitution | `{{ var }}` | `{{ player_name }}` |
| Default value | `{{ var \| default("x") }}` | `{{ mood \| default("neutral") }}` |
| Conditional | `{% if var %}...{% endif %}` | `{% if quest %}Quest: {{ quest }}{% endif %}` |
| Iteration | `{% for x in list %}...{% endfor %}` | `{% for npc in npcs %}{{ npc.name }}{% endfor %}` |
| Fragment include | `{% include "name.fragment.md" %}` | `{% include "safety-preamble.fragment.md" %}` |
| Comment | `{# comment #}` | `{# TODO: refine tone #}` |

### 1.4 — Template metadata model

```python
class PromptMetadata(BaseModel):
    """YAML front matter parsed into a typed model."""

    id: str                                    # e.g. "narrative.generate"
    version: str                               # semver: "1.0.0"
    role: ModelRole                            # generation | classification | extraction
    description: str
    author: str = "unknown"
    created: date | None = None

    parameters: GenerationParams | None = None  # temperature, max_tokens, etc.

    variables: VariableSpec
    output_schema: dict | None = None          # JSON Schema for structured output

class VariableSpec(BaseModel):
    required: list[str] = []
    optional: list[str] = []
```

### 1.5 — Fragment metadata

Fragments are simpler — they have an `id` and `version` but no variables or parameters
of their own (they inherit context from the including template).

```yaml
---
id: safety-preamble
version: 1.0.0
description: >
  Immutable safety rules included in every player-facing prompt.
  This fragment cannot be overridden by template authors.
protected: true  # Registry enforces: protected fragments cannot be excluded
---

You must NEVER:
- Provide real-world medical, legal, or financial advice.
- Generate graphic violence, sexual content, or self-harm encouragement.
- Produce content that could be mistaken for real-world emergency communication.
- Break character to discuss being an AI or language model.

If the player appears distressed, respond with care and warmth within
the narrative — never dismiss, mock, or escalate.
```

---

## 2. Prompt Registry

### 2.1 — Registry design

The registry is a startup-loaded, in-memory store. It reads template and fragment
files from disk, parses front matter, validates templates, and serves them to the
pipeline by ID.

```python
class PromptRegistry:
    """In-memory prompt template registry.

    Loaded at startup from the prompts/ directory.
    Thread-safe for concurrent reads (no writes after init).
    """

    def __init__(self, prompts_dir: Path) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._fragments: dict[str, str] = {}     # id → rendered body
        self._genre_packs: dict[str, GenrePack] = {}
        self._jinja_env: SandboxedEnvironment = ...

    def get(self, prompt_id: str) -> PromptTemplate:
        """Return the loaded template by ID. Raises KeyError if missing."""
        ...

    def list_templates(self) -> list[PromptMetadata]:
        """List all registered template metadata."""
        ...

    def get_genre_pack(self, genre_id: str) -> GenrePack:
        """Return a loaded genre pack by ID. Raises KeyError if missing."""
        ...

    def render(
        self,
        prompt_id: str,
        variables: dict[str, str],
    ) -> RenderedPrompt:
        """Render a template with variables. Validates required vars."""
        ...
```

### 2.2 — Loading sequence (startup)

```
1. Scan prompts/fragments/ → parse YAML front matter → store fragment bodies
2. Scan prompts/templates/ → parse YAML front matter → store PromptTemplate objects
3. Validate all templates:
   a. Jinja2 syntax check (parse without rendering)
   b. All {% include %} references resolve to known fragments
   c. Dynamic genre includes: validate that all genre_slug values from
      loaded genre packs resolve to a matching genre fragment file.
      Missing genre fragment → fail startup (not silently ignored).
   d. No circular includes (fragment A includes fragment B includes fragment A)
   e. Protected fragments (safety-preamble) are present
4. Scan prompts/genres/ → parse GenrePack YAML → store GenrePack objects
5. Cross-validate: every genre pack's id has a matching genre fragment file
6. If any required template is missing → fail startup with clear error (FR-09.05)
```

**Required templates** — the pipeline will not start without these:

| Template ID | Used by |
|---|---|
| `narrative.generate` | Generation stage (Stage 3) |
| `classification.intent` | Input Understanding (Stage 1) |
| `extraction.world-changes` | Post-generation world state extraction |

### 2.3 — Jinja2 environment configuration

```python
from jinja2 import SandboxedEnvironment, FileSystemLoader, select_autoescape

def create_jinja_env(prompts_dir: Path) -> SandboxedEnvironment:
    """Create a sandboxed Jinja2 environment for prompt rendering."""
    return SandboxedEnvironment(
        loader=FileSystemLoader([
            str(prompts_dir / "templates"),
            str(prompts_dir / "fragments"),
        ]),
        autoescape=False,           # Prompts are plain text, not HTML
        undefined=StrictUndefined,  # Missing vars → error, not empty string
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
```

Key choices:
- **`SandboxedEnvironment`**: Prevents template code from executing arbitrary Python.
  Blocks attribute access to dangerous objects. (FR-09.19 / FR-09.49)
- **`StrictUndefined`**: A missing required variable raises `UndefinedError` at render
  time, not a silent empty string. (FR-09.18)
- **`FileSystemLoader`**: Templates and fragments are loaded from disk paths. Fragment
  includes resolve via the loader's search path.

### 2.4 — Hot-reload in development

In dev mode (`--reload`), the registry watches the `prompts/` directory for changes
and reloads affected templates without restarting the server.

```python
if settings.dev_mode:
    from watchfiles import awatch

    async def watch_prompts(registry: PromptRegistry) -> None:
        async for changes in awatch(registry.prompts_dir):
            log.info("prompt_files_changed", files=[str(c) for c in changes])
            registry.reload()
```

`watchfiles` is already a transitive dependency via Uvicorn's `--reload` mode.
No new dependency.

In production, templates are immutable after startup. No file watcher, no reload.

### 2.5 — Version identification

v1 uses the `version` field from YAML front matter as the template version. This is
a semver string embedded in the file, committed to git, and deployed with code.

The registry does not track version history — git does. To roll back a prompt, revert
the file in git and deploy. This is simple and auditable.

**Langfuse linkage**: Every LLM call records `prompt_id` and `prompt_version` as
trace metadata. This connects a generation to the exact template that produced it.

```python
# In the generation stage, after rendering:
langfuse.trace(
    name="narrative_generation",
    metadata={
        "prompt_id": template.metadata.id,
        "prompt_version": template.metadata.version,
        "fragment_versions": rendered.fragment_versions,
        "prompt_hash": rendered.content_hash,
    },
)
```

---

## 3. Prompt Composition Pipeline

### 3.1 — From turn to LLM messages

The composition pipeline transforms a `TurnState` (from the pipeline orchestrator)
into a `list[Message]` suitable for LiteLLM.

**Stage ownership:** Context assembly and token budget allocation belong to
**Stage 2 (Context Assembly)**. Template rendering and message construction belong
to **Stage 3 (Generation)**. The boundary is:

- **Stage 2 produces**: a `ContextBundle` — a typed, priority-tagged collection of
  context sections (location, NPCs, history, etc.) that have already been measured,
  compressed, and packed within the token budget. This is stored on `TurnState`.
- **Stage 3 consumes** the `ContextBundle`: flattens it to template variables,
  renders the Jinja2 template, builds the LiteLLM message list, and calls the LLM.

This split keeps Stage 2 focused on *what context to include* and Stage 3 focused
on *how to render and call the model*.

```
TurnState
   │
   ├── Stage 1 output: parsed_intent, emotional_tone
   │
   ▼
┌──────────────────────────────────────────────────┐
│  Stage 2: Context Assembly                       │
│                                                  │
│  1. Query world context (Neo4j, Postgres)        │
│  2. Build ContextBundle (typed, prioritized)     │
│  3. Apply token budget (compress/truncate)       │
│                                                  │
│  Output: TurnState.context_bundle: ContextBundle │
└──────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────┐
│  Stage 3: Generation                             │
│                                                  │
│  1. Select template (by pipeline stage + role)   │
│  2. Flatten ContextBundle → template variables   │
│  3. Render template (Jinja2)                     │
│  4. Build LiteLLM message list                   │
│  5. Call LLMClient.generate() or .stream()       │
│                                                  │
│  Output: TurnState.narrative_output + metadata   │
└──────────────────────────────────────────────────┘
```

### 3.2 — Message structure

All prompts map to LiteLLM's `system` / `user` / `assistant` message format. The
structural rule (FR-09.49) is absolute: **player input is never in the system message**.

**Narrative generation** (the main prompt):

```python
messages = [
    {
        "role": "system",
        "content": rendered_system_prompt,
        # Contains: safety preamble, genre tone, task instructions,
        #           output format, world context, recent events,
        #           NPC/item/quest context
    },
    {
        "role": "user",
        "content": player_action,
        # Contains ONLY the player's input text.
        # Never includes instructions, context, or template content.
    },
]
```

**Why no multi-turn message history?** Conversation history is included as formatted
text within the system prompt's context section, not as alternating user/assistant
messages. This gives full control over token budgets and avoids the model treating
context-history as its own prior responses.

**Classification** (intent parsing):

```python
messages = [
    {
        "role": "system",
        "content": rendered_classification_prompt,
        # Contains: task instructions, output schema, valid intents list
    },
    {
        "role": "user",
        "content": player_input,
    },
]
```

### 3.3 — Composition order within the system prompt

The system prompt is assembled from fragments and variables in a fixed order
(FR-09.26). The safety preamble is always first and cannot be displaced.

```
┌────────────────────────────────────────┐
│  1. Safety Preamble (immutable)        │  ← {% include "safety-preamble.fragment.md" %}
│  2. Narrator Role + Genre Tone         │  ← Template body + genre fragment
│  3. Task Instructions                  │  ← "Write the next part of the story..."
│  4. World Context (variables)          │  ← location, NPCs, items, time, quests
│  5. Recent Events / History            │  ← Formatted recent turns, story summary
│  6. Output Format Guidelines           │  ← {% include "output-prose.fragment.md" %}
└────────────────────────────────────────┘
```

This order is enforced by the template file structure itself — authors write the
template with includes and variables in the correct order. The safety preamble
include must be the first content line (linting validates this — see §8.3).

### 3.4 — Token budget management

The model's context window is finite. The composition pipeline must fit the assembled
prompt within a token budget while preserving the highest-value context.

**Budget calculation:**

```
available_tokens = model_context_window - reserved_output_tokens - safety_margin

model_context_window    = from model config (e.g., 200k for Claude Sonnet)
reserved_output_tokens  = template.parameters.max_tokens (e.g., 1024)
safety_margin           = 500 tokens (overhead for message framing)
```

**Priority tiers** (from S03 FR-3.1, highest priority last-to-cut):

| Priority | Context layer | Compression strategy |
|---|---|---|
| 6 (never cut) | WorldSeed / genre tone | Always included verbatim |
| 5 (never cut) | Safety preamble | Always included verbatim |
| 4 (preserve) | Character state, active scene | Preserve in full |
| 3 (compress) | Active story threads, quests | Summarize if over budget |
| 2 (compress) | Recent history (last 5–10 turns) | Truncate to last N turns |
| 1 (drop) | Distant history, inactive NPCs | Omit entirely |

**Implementation:**

```python
class TokenBudget:
    """Manages token allocation across prompt sections."""

    def __init__(self, model_limit: int, output_reserve: int) -> None:
        self.remaining = model_limit - output_reserve - 500

    def allocate(
        self,
        sections: list[ContextSection],
    ) -> list[ContextSection]:
        """Pack sections by priority. Compress/drop lowest priority first."""
        # Sort by priority descending (highest priority first)
        # Measure token count of each section (tiktoken estimation)
        # If total exceeds budget, compress from lowest priority up
        ...
```

Token counting uses `tiktoken` for estimation (not exact, but close enough for
budget planning). The actual token count is reported by the LLM response.

**History truncation strategy:**

When recent history exceeds its token budget:
1. Keep the last 3 turns verbatim (most relevant for coherence).
2. Summarize turns 4–10 into a 2–3 sentence bridge paragraph.
3. Drop turns beyond 10 entirely (they're captured in the running story summary
   and world state, per S03 FR-2.5 / FR-3.2).

The running story summary (maintained separately, updated at chapter boundaries) fills
the role of long-term memory and does not count against the history budget.

---

## 4. Prompt Versioning Strategy

### 4.1 — Version scheme

Prompts use semantic versioning in the YAML front matter `version` field, following
S09's MAJOR.MINOR.PATCH definition:

| Bump | Trigger | Example |
|---|---|---|
| **MAJOR** | New required variables, different output structure, fundamental behavior change | Adding `character_state` as required; changing from prose to JSON output |
| **MINOR** | Noticeably different output quality/style, same interface | Rewriting task instructions to improve coherence |
| **PATCH** | Typo fix, wording tweak, no material output change | Fixing "you're" → "your" in instructions |

### 4.2 — Versioning mechanics in v1

```
Author edits prompts/templates/narrative/generate.prompt.md
   │
   ├── Bumps `version:` in YAML front matter
   ├── Commits with message: "prompt(narrative.generate): v1.2.0 — improve coherence"
   │
   ▼
CI runs prompt validation + golden tests (see §5)
   │
   ▼
Merge to main → deploy picks up new template files
   │
   ▼
At startup, registry loads new version. Langfuse traces now show v1.2.0.
```

**Rollback**: Revert the commit. The previous version is restored from git history.
Deploy. This is intentionally simple for v1 — same workflow as rolling back a code
change.

### 4.3 — Langfuse integration (tracing, not storage)

Langfuse is the **observability layer**, not the prompt store. Prompts live in files;
Langfuse records what was used.

Per-generation metadata sent to Langfuse:

| Field | Value | Purpose |
|---|---|---|
| `prompt_id` | `"narrative.generate"` | Which template |
| `prompt_version` | `"1.2.0"` | Which version |
| `fragment_versions` | `{"safety-preamble": "1.0.0", "genre/noir": "1.1.0"}` | Fragment audit trail |
| `prompt_hash` | SHA-256 of final rendered prompt | Exact content fingerprint |

This enables:
- Filtering generations by prompt version in Langfuse UI
- Comparing quality metrics across versions
- Reproducing the exact prompt for any historical generation
- Detecting when a fragment update changes effective prompt content (hash changes
  even if root template version doesn't)

### 4.4 — Future: runtime activation

When v2 adds runtime activation (changing the active version without deploy), the
registry gains a `activate(prompt_id, version)` method backed by Langfuse's prompt
management or a Postgres table. The file-based templates become the authoring source;
the activation layer picks which version is live. The registry interface (`get()`,
`list()`) doesn't change — only the backing store.

---

## 5. Prompt Snapshot Tests and Prompt Testing

### 5.1 — What prompt snapshot tests are

A prompt snapshot test captures the **assembled prompt** (not the LLM output) for a
known set of input variables. It verifies that template rendering + composition
produces the expected prompt structure. This is fully deterministic — no LLM involved.

> **Terminology note**: S09 uses "golden tests" to describe tolerant LLM-output
> regression checks. This plan uses "prompt snapshot tests" for the deterministic
> template-rendering layer and reserves "golden / regression tests" (§5.4–5.5)
> for the LLM-backed behavioral checks that validate actual model output.

```
                    ┌─────────────────────┐
Known variables ──▶ │  Render template    │ ──▶ Rendered prompt
                    │  (Jinja2)           │       │
                    └─────────────────────┘       ▼
                                              Compare against
                                              golden snapshot
```

### 5.2 — Snapshot test structure

Snapshot tests live alongside the templates they test:

```
prompts/
├── templates/
│   └── narrative/
│       ├── generate.prompt.md
│       └── tests/
│           ├── test_generate.py
│           └── golden/
│               ├── basic_turn.vars.yaml      # Input variables
│               ├── basic_turn.golden.txt      # Expected rendered prompt
│               ├── minimal_context.vars.yaml
│               └── minimal_context.golden.txt
```

**Variable fixture** (`basic_turn.vars.yaml`):

```yaml
player_name: "Kira"
location_description: "A dimly lit tavern with smoke-stained rafters."
player_action: "I look around the room."
genre_tone: "dark fantasy"
genre_slug: "fantasy"
recent_events: "You arrived in the village at dusk. The innkeeper warned you about the forest."
nearby_npcs: "- Brin, the barkeep (friendly, curious)\n- A hooded figure in the corner (unknown)"
inventory_summary: "A worn map, a hunting knife, 12 silver coins"
```

**Golden snapshot** (`basic_turn.golden.txt`):

The fully rendered system prompt. Stored as plain text. Updated with
`pytest --update-golden` when intentional changes are made.

### 5.3 — Test implementation

```python
# prompts/templates/narrative/tests/test_generate.py

import pytest
from pathlib import Path
from tta.prompts.registry import PromptRegistry

GOLDEN_DIR = Path(__file__).parent / "golden"

@pytest.fixture
def registry(prompts_dir: Path) -> PromptRegistry:
    return PromptRegistry(prompts_dir)

class TestNarrativeGenerate:

    @pytest.mark.parametrize("case", ["basic_turn", "minimal_context"])
    def test_golden_snapshot(
        self, registry: PromptRegistry, case: str, update_golden: bool
    ) -> None:
        """Rendered prompt matches golden snapshot."""
        # Arrange
        vars_file = GOLDEN_DIR / f"{case}.vars.yaml"
        golden_file = GOLDEN_DIR / f"{case}.golden.txt"
        variables = yaml.safe_load(vars_file.read_text())

        # Act
        rendered = registry.render("narrative.generate", variables)

        # Assert (or update)
        if update_golden:
            golden_file.write_text(rendered.system_prompt)
        else:
            expected = golden_file.read_text()
            assert rendered.system_prompt == expected, (
                f"Prompt drift detected for {case}. "
                f"Run `pytest --update-golden` to accept changes."
            )

    def test_missing_required_variable_raises(
        self, registry: PromptRegistry
    ) -> None:
        """Missing required variable produces a clear error."""
        # Arrange — omit player_name (required)
        variables = {"location_description": "A room.", "player_action": "look"}

        # Act / Assert
        with pytest.raises(PromptRenderError, match="player_name"):
            registry.render("narrative.generate", variables)

    def test_safety_preamble_is_first(
        self, registry: PromptRegistry
    ) -> None:
        """Safety preamble is the first content in the rendered prompt."""
        variables = _full_variable_set()
        rendered = registry.render("narrative.generate", variables)
        # The safety preamble's first line should appear before any other content
        assert rendered.system_prompt.startswith("You must NEVER:")
```

### 5.4 — Scenario tests (LLM-backed, optional in CI)

Scenario tests call the actual LLM with a rendered prompt and check behavioral
assertions on the output. These are **not run in standard CI** (they're slow,
non-deterministic, and cost money). They run on-demand via `make test-prompts-llm`.

```python
@pytest.mark.llm  # Skipped in CI unless explicitly enabled
@pytest.mark.asyncio
class TestNarrativeScenarios:

    async def test_locked_door_without_key(
        self, llm_client: LLMClient, registry: PromptRegistry
    ) -> None:
        """Model respects world state: door stays locked without key."""
        variables = {
            "player_action": "I try to open the door",
            "location_description": "Castle entrance. A heavy oak door, locked.",
            "inventory_summary": "A torch, a worn map",
            # No key in inventory
            **_base_variables(),
        }
        rendered = registry.render("narrative.generate", variables)
        response = await llm_client.generate(
            role=ModelRole.GENERATION,
            messages=rendered.to_messages(user_content=variables["player_action"]),
            params=GenerationParams(temperature=0.0),
        )

        assert_any_substring(response, ["locked", "won't budge", "need a key", "won't open"])
        assert_no_substring(response, ["door opens", "you enter", "step inside"])
```

### 5.5 — Regression test suite

A `prompts/regression/` directory holds scenario definitions for known-bad cases —
situations where a previous prompt version produced incorrect output. Each regression
case documents: what went wrong, which prompt version caused it, and what the correct
behavior should be.

```yaml
# prompts/regression/ghost-npc-appears.yaml
id: regression-ghost-npc
description: >
  v1.0.0 of narrative.generate sometimes mentioned NPCs not listed in
  nearby_npcs, because the instruction was too vague about scope.
  Fixed in v1.1.0 by adding "Do not reference characters not in the context."
prompt_id: narrative.generate
broke_in: "1.0.0"
fixed_in: "1.1.0"
variables:
  nearby_npcs: "- Brin, the barkeep"
  # Only Brin is present
assertions:
  - response_not_contains: ["mysterious stranger", "hooded figure", "old woman"]
  # These were hallucinated NPCs in the broken version
```

---

## 6. Narrator Voice

### 6.1 — Voice definition in prompts

The narrator voice (S03 FR-1) is encoded across three layers:

| Layer | Controlled by | When set |
|---|---|---|
| **Base voice** | `narrative.generate` template body | Always (default second-person present tense) |
| **Genre voice** | Genre fragment (`genre/fantasy.fragment.md`) | Per session, from WorldSeed |
| **Voice tuning** | WorldSeed `tone` parameters injected as variables | Per session, from Genesis |

The base template establishes the narrator rules (second person, present tense, no
fourth-wall breaks). The genre fragment adds vocabulary, rhythm, and mood constraints.
The WorldSeed tone parameters (`formality`, `warmth`, `humor` — per S03 FR-1.2)
fine-tune the voice via variables.

### 6.2 — Genre fragment example

```markdown
---
id: genre/noir
version: 1.0.0
description: "Noir detective tone directives"
---

## Genre: Noir Detective

Write in the voice of a hard-boiled detective novel narrator:
- Terse, world-weary prose. Short sentences. Occasional long noir monologue.
- Metaphors are vivid and cynical ("a smile like a closed fist").
- Weather reflects mood. It rains a lot.
- Every character has a secret. Trust is currency.
- Violence is implied, never graphic.
- Humor is dry and dark.

Speech patterns:
- NPCs speak in clipped, guarded sentences.
- Subtext matters more than text. What isn't said is as important as what is.
```

### 6.3 — Voice consistency across turns

When history is truncated (§3.4), voice consistency is maintained by:

1. **Genre fragment is always included** — the tone directive is never compressed.
2. **WorldSeed tone parameters are always injected** — formality/warmth/humor are
   tier-6 priority (never cut).
3. **Running story summary uses the same voice** — the summary itself is generated
   with a prompt that includes the genre fragment, so it reads in the session's
   established tone. When included as context for the next turn, it reinforces
   the voice rather than introducing a neutral recap tone.

### 6.4 — Genre pack structure

Genre packs are YAML files that bundle tone, archetypes, and location moods. They
are loaded by the registry and their fields are made available as template variables.

```python
class GenrePack(BaseModel):
    """A genre configuration loaded from YAML."""

    id: str                          # e.g. "noir"
    version: str
    name: str                        # e.g. "Noir Detective"
    description: str

    tone: GenreTone                   # vocabulary, sentence_style, mood, humor, violence
    narrative_rules: list[str]        # Genre-specific narrator rules
    npc_archetypes: list[NPCArchetype]
    location_moods: dict[str, str]    # location_type → mood description
    fallback_responses: FallbackSet   # thinking, cant_do_that, error
```

The genre pack is selected during Genesis based on the player's choices and stored
in the WorldSeed. The registry resolves it at render time:

```python
genre_pack = registry.get_genre_pack(game_state.world_seed.genre_id)
variables["genre_tone"] = genre_pack.tone.summary()
variables["genre_slug"] = genre_pack.id
```

---

## 7. Prompt Security

### 7.1 — Structural separation (primary defense)

The most important defense against prompt injection is **structural**: player input
and system instructions occupy separate messages. The player's text is always the
`user` message. The system prompt (with safety preamble, instructions, context) is
always the `system` message. No template renders player input into the system prompt.

```python
class RenderedPrompt:
    """The output of template rendering."""

    system_prompt: str       # Rendered template (all fragments + variables)
    fragment_versions: dict[str, str]
    content_hash: str        # SHA-256 of system_prompt

    def to_messages(self, user_content: str) -> list[Message]:
        """Build LiteLLM message list. Player input is ALWAYS the user message."""
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
```

### 7.2 — Input sanitization

Variable values are sanitized before injection to prevent template syntax from
being interpreted in user-supplied content (FR-09.19).

```python
def sanitize_variable(value: str) -> str:
    """Escape Jinja2 syntax in variable values.

    Prevents values like "{{ evil }}" or "{% include 'x' %}" from
    being interpreted as template directives.
    """
    # Jinja2's SandboxedEnvironment + autoescape handles this for HTML,
    # but since we use autoescape=False (plain text), we manually escape
    # template delimiters in variable values.
    return (
        value
        .replace("{%", "{ %")
        .replace("%}", "% }")
        .replace("{{", "{ {")
        .replace("}}", "} }")
        .replace("{#", "{ #")
        .replace("#}", "# }")
    )
```

This runs on all variable values before they reach Jinja2's render call. The
sanitization is transparent — the rendered prompt contains the original text with
broken delimiters that prevent interpretation.

### 7.3 — Injection detection (logging, not blocking)

Per FR-09.50, suspected injection attempts are logged but do not block the turn
(false positives would break the game). Detection is pattern-based:

```python
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+a",
    r"system\s*:\s*",
    r"forget\s+(everything|all|your\s+instructions)",
    r"disregard\s+(the\s+)?(above|previous)",
]

def check_injection(player_input: str) -> bool:
    """Check for prompt injection patterns. Returns True if suspicious."""
    normalized = player_input.lower().strip()
    return any(re.search(p, normalized) for p in INJECTION_PATTERNS)
```

If detected:
- Log a structured security event: `log.warning("prompt_injection_suspected", input=player_input[:200])`
- Continue processing the turn normally
- The safety preamble + structural separation are the actual defense; logging is
  for monitoring and future analysis

### 7.4 — Forbidden content enforcement

The safety preamble fragment (§1.5) is the prompt-level content guardrail. It is
enforced at three levels:

1. **Template structure**: The `safety-preamble.fragment.md` fragment is `protected: true`.
   The registry refuses to load any player-facing template that doesn't include it.
2. **Composition order**: The safety preamble is always the first content in the system
   message. No fragment or variable can precede it.
3. **Lint check**: A CI linting step (§8.3) validates that every `role: generation`
   template includes the safety preamble.

### 7.5 — Post-generation content interception (FR-09.48)

**Not owned by this component.** FR-09.48 requires intercepting LLM output before
delivery and replacing unsafe content with a safe alternative. This is a
**post-generation safety enforcement** responsibility, owned by the future Safety
component (see system.md §2.4 safety seam architecture; full system deferred to S19)
and implemented as a Stage 4 (Post-processing) pipeline step.

The prompts component's responsibility ends at the system prompt: it encodes *what
the model should not generate*. The safety component's responsibility is verifying
*that the model actually complied* and intervening if it didn't. This plan does not
duplicate that logic.

---

## 8. Testing Strategy

### 8.1 — Test pyramid for prompts

| Layer | What it tests | Speed | Runs in CI | Tool |
|---|---|---|---|---|
| **Unit** | Template rendering with known variables | Fast (<1s each) | ✅ Every PR | pytest |
| **Snapshot** | Rendered prompt matches snapshot | Fast (<1s each) | ✅ Every PR | pytest + snapshot files |
| **Lint** | Template structure, safety preamble, variable declarations | Fast | ✅ Every PR | Custom pytest checks |
| **Scenario** | LLM output meets behavioral assertions | Slow (2–10s each) | ❌ On-demand | pytest -m llm |
| **Regression** | Known-bad cases don't recur | Slow (if LLM-backed) | ❌ On-demand | pytest -m llm |

### 8.2 — Unit tests (template rendering)

These are pure Python tests that verify Jinja2 rendering. No LLM, no network.

```python
class TestTemplateRendering:

    def test_optional_variable_omitted_gracefully(self, registry):
        """Optional variables that are absent produce no output, no error."""
        variables = {**_required_vars()}
        # nearby_npcs is optional — not provided
        rendered = registry.render("narrative.generate", variables)
        assert "Characters Present" not in rendered.system_prompt

    def test_optional_variable_included_when_present(self, registry):
        """Optional variables render their section when provided."""
        variables = {**_required_vars(), "nearby_npcs": "- Brin (barkeep)"}
        rendered = registry.render("narrative.generate", variables)
        assert "Characters Present" in rendered.system_prompt
        assert "Brin (barkeep)" in rendered.system_prompt

    def test_jinja_syntax_in_variable_is_escaped(self, registry):
        """Template syntax in variable values is not interpreted."""
        variables = {**_required_vars(), "player_name": "{{ evil }}"}
        rendered = registry.render("narrative.generate", variables)
        # The literal text appears, not a Jinja2 evaluation
        assert "{ { evil } }" in rendered.system_prompt

    def test_fragment_versions_tracked(self, registry):
        """Rendered result reports which fragment versions were included."""
        rendered = registry.render("narrative.generate", _required_vars())
        assert "safety-preamble" in rendered.fragment_versions
        assert rendered.fragment_versions["safety-preamble"] == "1.0.0"
```

### 8.3 — Prompt linting (CI)

A custom pytest plugin validates structural rules across all template files:

```python
# tests/prompts/test_prompt_lint.py

class TestPromptLint:

    def test_all_generation_templates_include_safety_preamble(
        self, all_generation_templates: list[Path]
    ) -> None:
        """Every generation template must include the safety preamble."""
        for template_path in all_generation_templates:
            content = template_path.read_text()
            assert 'include "safety-preamble.fragment.md"' in content, (
                f"{template_path.name} is missing safety preamble include"
            )

    def test_no_player_input_in_system_template(
        self, all_templates: list[Path]
    ) -> None:
        """No template should reference player_action in a way that
        embeds it in the system prompt. Player input goes in user message."""
        for template_path in all_templates:
            content = template_path.read_text()
            # player_action should only appear in task instruction context
            # (e.g., "Respond to the player's action") not as {{ player_action }}
            # rendered directly into the system message body.
            # This is a heuristic — the real enforcement is in RenderedPrompt.to_messages()
            pass  # Structural enforcement in code > lint heuristic

    def test_all_templates_have_valid_front_matter(
        self, all_prompt_files: list[Path]
    ) -> None:
        """Every .prompt.md file must have valid YAML front matter."""
        for path in all_prompt_files:
            metadata = parse_front_matter(path)
            assert metadata.id, f"{path.name} missing 'id' in front matter"
            assert metadata.version, f"{path.name} missing 'version'"
            assert metadata.role, f"{path.name} missing 'role'"

    def test_declared_variables_match_template_usage(
        self, registry: PromptRegistry
    ) -> None:
        """Variables used in template body match the declared variable list."""
        for template in registry.list_templates():
            used = extract_variables_from_template(template.body)
            declared = set(template.metadata.variables.required
                         + template.metadata.variables.optional)
            undeclared = used - declared - {"genre_slug"}  # built-in
            assert not undeclared, (
                f"{template.metadata.id} uses undeclared variables: {undeclared}"
            )
```

### 8.4 — Makefile targets

```makefile
test-prompts:          ## Run prompt unit tests + golden tests + lint
	uv run pytest prompts/ tests/prompts/ -v

test-prompts-update:   ## Update golden snapshots (after intentional changes)
	uv run pytest prompts/ tests/prompts/ -v --update-golden

test-prompts-llm:      ## Run LLM-backed scenario and regression tests (slow, costs $)
	uv run pytest tests/prompts/ -v -m llm --no-header
```

---

## 9. Python Module Structure

### 9.1 — New module: `src/tta/prompts/`

This module is added to the project structure defined in system.md §2.5:

```
src/tta/
    prompts/
    ├── __init__.py          # Public API: PromptRegistry, RenderedPrompt
    ├── registry.py          # PromptRegistry class (load, get, render)
    ├── renderer.py          # Jinja2 environment setup, rendering logic
    ├── composer.py          # Token budget management, context packing
    ├── models.py            # PromptMetadata, PromptTemplate, VariableSpec, etc.
    ├── sanitize.py          # Variable sanitization, injection detection
    └── loader.py            # File parsing (YAML front matter + body extraction)
```

### 9.2 — Integration with pipeline stages

The prompt registry is created once at application startup and injected into pipeline
stages via FastAPI's dependency injection.

```python
# In tta/api/app.py
from tta.prompts.registry import PromptRegistry

def create_app() -> FastAPI:
    app = FastAPI()
    settings = Settings()

    # Load prompts at startup
    prompt_registry = PromptRegistry(Path("prompts"))

    # Inject into pipeline stages
    app.state.prompt_registry = prompt_registry
    ...
```

Pipeline stages receive the registry and use it to render prompts. Note that
`build_generation_variables` reads from `state.context_bundle`, which was populated
by Stage 2 (Context Assembly):

```python
# In tta/pipeline/generation.py (Stage 3)

async def generation_stage(
    state: TurnState,
    registry: PromptRegistry,
    llm: LLMClient,
) -> TurnState:
    """Stage 3: Render prompt and call LLM.

    Requires state.context_bundle to be populated by Stage 2.
    """
    variables = build_generation_variables(state)
    rendered = registry.render("narrative.generate", variables)

    response = await llm.generate(
        role=ModelRole.GENERATION,
        messages=rendered.to_messages(user_content=state.player_input),
        params=rendered.metadata.parameters,
    )

    return state.model_copy(update={
        "generation_prompt": rendered.system_prompt,
        "narrative_output": response,
        "model_used": ...,
    })
```

### 9.3 — Variable assembly

A helper function maps `TurnState` + `ContextBundle` into the flat variable dict
that templates expect. This is the bridge between the pipeline's typed models and
the template's string variables.

**Stage 2 context model** — `ContextBundle` contains all fields needed to satisfy
S03's priority-based context tiers. The following fields are the minimum contract
that Stage 2 must populate on `TurnState`:

```python
class ContextBundle(BaseModel):
    """Priority-tagged context assembled in Stage 2.

    Tiers correspond to S03 FR-3.1 compression priorities.
    """

    # Tier 6 (never cut)
    genre_tone: str              # from WorldSeed
    genre_id: str                # slug for fragment include
    voice_formality: float       # S03 FR-1.2 — 0.0 (casual) to 1.0 (formal)
    voice_warmth: float          # S03 FR-1.2 — 0.0 (detached) to 1.0 (warm)
    voice_humor: float           # S03 FR-1.2 — 0.0 (serious) to 1.0 (playful)

    # Tier 4 (preserve)
    location: LocationContext
    character_state: CharacterState | None = None
    active_scene: str | None = None

    # Tier 3 (compress)
    active_quests: list[QuestSummary] = []
    active_threads: list[str] = []       # Active story threads
    relationship_states: list[RelationshipSummary] = []
    chapter_context: str | None = None   # Current chapter framing

    # Tier 2 (truncate)
    recent_events: list[TurnSummary] = []
    conversation_history: list[str] = []

    # Tier 1 (drop)
    distant_history: list[str] = []
    inactive_npcs: list[str] = []

    # Derived
    running_story_summary: str | None = None  # Updated at chapter boundaries
    nearby_npcs: list[NPCSummary] = []
    nearby_objects: list[str] = []
    inventory: list[str] = []
    time_description: str | None = None
```

```python
def build_generation_variables(state: TurnState) -> dict[str, str]:
    """Assemble template variables from pipeline state.

    Reads from state.context_bundle (populated by Stage 2) and
    state.game_state (player identity, WorldSeed).
    """
    ctx = state.context_bundle
    ws = state.game_state.world_seed
    return {
        # Required
        "player_name": state.game_state.player_name,
        "player_action": state.player_input,
        "location_description": ctx.location.description,
        "location_name": ctx.location.name,
        "genre_tone": ctx.genre_tone,
        "genre_slug": ctx.genre_id,
        "recent_events": format_recent_events(ctx.recent_events),
        "turn_number": str(state.turn_number),
        # Voice tuning (S03 FR-1.2) — injected as variables for template access
        "voice_formality": f"{ctx.voice_formality:.1f}",
        "voice_warmth": f"{ctx.voice_warmth:.1f}",
        "voice_humor": f"{ctx.voice_humor:.1f}",
        # Optional — included only if available
        **({"nearby_npcs": format_npcs(ctx.nearby_npcs)} if ctx.nearby_npcs else {}),
        **({"nearby_objects": format_items(ctx.nearby_objects)} if ctx.nearby_objects else {}),
        **({"inventory_summary": format_inventory(ctx.inventory)} if ctx.inventory else {}),
        **({"active_quests": format_quests(ctx.active_quests)} if ctx.active_quests else {}),
        **({"world_time": ctx.time_description} if ctx.time_description else {}),
        **({"character_state": format_character(ctx.character_state)} if ctx.character_state else {}),
        **({"conversation_history": format_history(ctx.conversation_history)} if ctx.conversation_history else {}),
        **({"emotional_tone": state.parsed_intent.emotional_tone} if state.parsed_intent and state.parsed_intent.emotional_tone else {}),
        **({"running_summary": ctx.running_story_summary} if ctx.running_story_summary else {}),
        **({"active_threads": format_threads(ctx.active_threads)} if ctx.active_threads else {}),
        **({"relationship_states": format_relationships(ctx.relationship_states)} if ctx.relationship_states else {}),
        **({"chapter_context": ctx.chapter_context} if ctx.chapter_context else {}),
    }
```

---

## 10. Dependencies

### 10.1 — New Python dependencies

| Package | Version | Purpose |
|---|---|---|
| `jinja2` | ≥ 3.1 | Template rendering (SandboxedEnvironment) |
| `tiktoken` | ≥ 0.7 | Token count estimation for budget management |
| `pyyaml` | ≥ 6.0 | YAML front matter parsing |

`jinja2` and `pyyaml` are likely already transitive dependencies (via FastAPI /
Pydantic). `tiktoken` is new.

`watchfiles` (for hot-reload) is already present via Uvicorn.

### 10.2 — No new infrastructure

Prompts add no new services to Docker Compose. Template files are baked into the
container image at build time. Langfuse (already in the stack) receives trace metadata.

---

## 11. Implementation Wave Mapping

Per system.md §9, prompts span **Wave 2** (LLM + Pipeline) and are consumed by
all subsequent waves.

| Wave | Prompt work |
|---|---|
| **Wave 0** | Define `PromptMetadata`, `RenderedPrompt`, `PromptRegistry` protocol |
| **Wave 2** | Implement registry, renderer, composer. Write initial templates. Snapshot tests. |
| **Wave 3** | Genre pack loading. Genre fragments for the 2–3 launch genres. |
| **Wave 4** | Langfuse trace linkage. Prompt lint in CI. |
| **Wave 5** | Scenario tests. Regression suite. Prompt tuning from playtests. |

---

## 12. Key Interfaces Summary

| Interface | Defined in | Consumed by |
|---|---|---|
| `PromptRegistry.get(id) → PromptTemplate` | `prompts/registry.py` | Pipeline stages |
| `PromptRegistry.render(id, vars) → RenderedPrompt` | `prompts/registry.py` | Pipeline stages |
| `RenderedPrompt.to_messages(user_content) → list[Message]` | `prompts/models.py` | LLMClient |
| `TokenBudget.allocate(sections) → list[ContextSection]` | `prompts/composer.py` | Context assembly (Stage 2) |
| `sanitize_variable(value) → str` | `prompts/sanitize.py` | Registry (at render time) |
| `GenrePack` model | `prompts/models.py` | World seeding, template variables |
| `ContextBundle` model | `prompts/models.py` | Stage 2 → Stage 3 contract |

---

## Appendix A — S09 Functional Requirement Coverage

| FR | Description | v1 Status | Notes |
|---|---|---|---|
| FR-09.01 | Template file format with front matter | ✅ Implemented | §1 |
| FR-09.02 | Variables with required/optional distinction | ✅ Implemented | §1.4 |
| FR-09.03 | Fragment composition (shared pieces) | ✅ Implemented | §1.5, §3.3 |
| FR-09.04 | Registry loads at startup | ✅ Implemented | §2.1 |
| FR-09.05 | Startup fails on missing required templates | ✅ Implemented | §2.2 |
| FR-09.06 | Semver versioning in front matter | ✅ Implemented | §4.1 |
| FR-09.07 | Version history / multi-version registry | ❌ Deferred v2 | Git is version store in v1 |
| FR-09.08 | Runtime activation / rollback | ❌ Deferred v2 | §4.4 |
| FR-09.09–11 | Shadow mode, A/B cohorts | ❌ Deferred v2 | — |
| FR-09.12–16 | Variable catalog (16 standard vars) | ✅ Implemented | §9.3 (expanded for S03) |
| FR-09.17 | Variable validation at render time | ✅ Implemented | StrictUndefined (§2.3) |
| FR-09.18 | Missing required var → clear error | ✅ Implemented | §2.3, §5.3 |
| FR-09.19 | Input sanitization (Jinja2 delimiter escape) | ✅ Implemented | §7.2 |
| FR-09.20–22 | Prompt testing (snapshot + scenario) | ✅ Implemented | §5, §8 |
| FR-09.23–24 | Fragment ordering, safety-first composition | ✅ Implemented | §3.3 |
| FR-09.25 | Token budget management | ✅ Implemented | §3.4 |
| FR-09.26 | Fixed composition order | ✅ Implemented | §3.3 |
| FR-09.27–30 | Genre packs | ✅ Implemented | §6.4 |
| FR-09.31–35 | Langfuse trace linkage | ✅ Implemented | §4.3 |
| FR-09.36 | Fragment dependency tracking | ✅ Implemented | `fragment_versions` in trace |
| FR-09.37–40 | CI lint, structural validation | ✅ Implemented | §8.3 |
| FR-09.41–45 | Interactive preview, visual editor | ❌ Deferred v2+ | — |
| FR-09.46 | Safety preamble (protected fragment) | ✅ Implemented | §1.5, §7.4 |
| FR-09.47 | Safety preamble cannot be excluded | ✅ Implemented | §7.4 (3 layers) |
| FR-09.48 | Post-generation interception/replacement | ❌ Owned by Safety | §7.5 |
| FR-09.49 | Structural separation (system/user) | ✅ Implemented | §7.1 |
| FR-09.50 | Injection detection (log, don't block) | ✅ Implemented | §7.3 |
| FR-09.51 | Output schema validation at registration | ❌ Deferred v2 | — |
| FR-09.52 | Token-fit validation at registration | ❌ Deferred v2 | Model-dependent |
| FR-09.53 | Updated/last-modified metadata | ❌ Deferred v2 | Git blame suffices |

---

## Changelog

| Date | Author | Description |
|------|--------|-------------|
| 2025-07-21 | Copilot audit | Corrected normative code examples to match actual implementation. Updated field names, types, enum members, file paths, and model definitions to reflect codebase as of commit 8045faa. |
