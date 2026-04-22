# S39 — Universe Composition Model

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.0
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Simulation
> **Dependencies**: S29 (Universe as First-Class Entity)
> **Related**: S33 (Universe Persistence), S34 (Diegetic Time), S40 (Genesis v2), S41 (Scenario Seed Library, v2.1+)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

In v1, a "universe" is a session's implicit backdrop with no explicit content
identity — no themes, no genre, no stylistic fingerprint. Two sessions using the
same template are indistinguishable at the engine level; there is no schema
governing what content a universe is *supposed to contain*.

S29 introduced the `Universe` entity and reserved a `config` field (opaque JSON)
for future use. S33 provides the persistence mechanism. **S39 fills the `config`
field with a first-class content vocabulary.**

The Universe Composition Model defines:
- The JSON schema for `universes.config` (the four composition layers: themes,
  tropes, archetypes, genre-twists)
- The `UniverseComposition` type that the engine parses from `config`
- Seedability: deterministic universe generation given (seed, composition)
- Reserved config namespaces for S36, S37, S38, and S40 subsystems
- Validation rules enforced at creation and config update time

S39 is the primitive that makes parallel universes **distinctly identifiable**,
supports the Scenario Seed Library (S41, v2.1+), and is the foundation for the
Resonance Correlation Engine (S56, v4+).

---

## 2. Design Philosophy

### 2.1 S29 / S33 / S39 Are Orthogonal

Per the v2 design note in S29 §1:
- **S29** — *Identity*: a universe has an ID and boundary.
- **S33** — *Persistence*: a versioned envelope for storing universe state.
- **S39** — *Composition*: the content vocabulary that fills a universe.

S39's schema MAY evolve without requiring S33 schema migrations, because S29
stores `config` as an opaque JSON blob. S39 versions its own composition schema
using a `composition_version` key inside the blob.

### 2.2 Four Composition Layers

A universe composition is defined by four combinable layers:

| Layer | Description | Max Entries (default) |
|-------|-------------|----------------------|
| **Themes** | High-level tonal/thematic qualities | 5 |
| **Tropes** | Narrative patterns and plot primitives | 10 |
| **Archetypes** | Character role types the world supports | 8 |
| **Genre-twists** | Modifiers that bend the primary genre | 3 |

Layers are additive and composable. An empty layer is valid (defaults apply).

### 2.3 Determinism

Given the same `seed` + same composition config JSON, the universe MUST generate
the same world state deterministically. This enables:
- Playtester reproducibility (run the same scenario twice, compare results)
- Debugging (reproduce a specific world for inspection)
- Scenario Seed Library distribution (S41 bundles are seed + config pairs)

The `seed` is a 64-bit unsigned integer stored in `config["seed"]`. It is set
at universe creation (genesis, S40) and MUST NOT change after first session open.

### 2.4 Opaque Subsystem Namespaces

Config keys under reserved namespaces are consumed by specific subsystems:

| Namespace | Consumed By |
|-----------|-------------|
| `config["memory"]` | S37 (World Memory Model) |
| `config["propagation"]` | S36 (Consequence Propagation) |
| `config["social"]` | S38 (NPC Social) |
| `config["time"]` | S34 (Diegetic Time) |
| `config["autonomy"]` | S35 (NPC Autonomy) |
| `config["genesis"]` | S40 (Genesis v2) |
| `config["composition"]` | S39 (this spec) |

---

## 3. User Stories

> **US-39.1** — **As a** universe author, I can define a universe as a gothic horror
> story with themes of decay and redemption, the "corrupted_mentor" archetype,
> and a noir genre-twist — all in a single composable config.

> **US-39.2** — **As a** playtester, I can reproduce the exact universe I played
> yesterday by sharing the seed + config, guaranteeing the same generated world.

> **US-39.3** — **As a** developer, the engine validates a universe config at creation
> time, failing loudly if I specify an unknown theme or a trope weight outside
> the valid range.

> **US-39.4** — **As a** scenario author (S41), I can bundle a curated set of
> themes, tropes, archetypes, and genre-twists into a named scenario seed that
> other authors and players can use as a starting point.

> **US-39.5** — **As a** universe author, I can configure diegetic time, memory
> compression, and NPC gossip thresholds in the same config blob, keeping all
> universe-level settings in one place.

---

## 4. Functional Requirements

### FR-39.01 — UniverseComposition Type

The parsed, validated representation of a universe's `config["composition"]` block.
The deterministic universe seed is defined separately at top-level `config["seed"]`
and is not part of `UniverseComposition`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `composition_version` | str | `"1.0"` | Schema version for forward-compat migration. |
| `primary_genre` | str | `"fantasy"` | The baseline genre of the universe. |
| `themes` | list[ThemeSpec] | `[]` | Thematic qualities. Up to 5. |
| `tropes` | list[TropeSpec] | `[]` | Narrative patterns. Up to 10. |
| `archetypes` | list[ArchetypeSpec] | `[]` | Character role types. Up to 8. |
| `genre_twists` | list[GenreTwist] | `[]` | Genre modifiers. Up to 3. |
| `prose` | ProseConfig | default | Prose voice and style. |
| `tone` | ToneProfile | derived | Aggregated tone (derived from themes + genre_twists). |

### FR-39.02 — ThemeSpec Type

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Theme identifier (e.g., `"redemption"`, `"cosmic_horror"`). |
| `weight` | float [0.0, 1.0] | Narrative weight; higher = more pervasive. Default: `0.5`. |
| `description` | str or null | Optional human-readable label. |

### FR-39.03 — TropeSpec Type

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Trope identifier (e.g., `"chosen_one"`, `"betrayal_within"`). |
| `weight` | float [0.0, 1.0] | How often this trope manifests. Default: `0.5`. |
| `required` | bool | If true, this trope MUST manifest at least once in the narrative. |
| `description` | str or null | Optional human-readable label. |

### FR-39.04 — ArchetypeSpec Type

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Archetype identifier (e.g., `"trickster_guide"`, `"threshold_guardian"`). |
| `npc_tier` | str | The NPC tier that SHOULD embody this archetype: `"key"`, `"supporting"`. |
| `description` | str or null | Optional human-readable label. |

### FR-39.05 — GenreTwist Type

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Twist identifier (e.g., `"noir_fantasy"`, `"cozy_dark"`, `"mundane_cosmic"`). |
| `strength` | float [0.0, 1.0] | How strongly the twist colours the universe. Default: `0.5`. |
| `description` | str or null | Optional human-readable label. |

### FR-39.06 — ProseConfig Type

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `voice` | str | `"default"` | Prose voice identifier (e.g., `"hardboiled"`, `"lyrical"`, `"terse"`). |
| `pacing` | str | `"balanced"` | Pacing hint: `"slow"`, `"balanced"`, `"fast"`. |
| `description_density` | str | `"medium"` | Scene description density: `"sparse"`, `"medium"`, `"rich"`. |
| `second_person` | bool | `true` | Whether to narrate in second-person ("You enter…"). |

### FR-39.07 — ToneProfile Type

| Field | Type | Description |
|-------|------|-------------|
| `primary` | str | Dominant tone (e.g., `"dark"`, `"hopeful"`, `"comedic"`). |
| `secondary` | str or null | Secondary tone modifier. |
| `warmth` | float [0.0, 1.0] | 0.0 = cold/grim, 1.0 = warm/hopeful. Derived from themes. |
| `intensity` | float [0.0, 1.0] | 0.0 = gentle, 1.0 = intense. Derived from trope weights. |

- **FR-39.07a**: `ToneProfile` is derived from the rest of `UniverseComposition`.
  It is computed at load time, not stored. Universe authors MAY override `primary`
  and `secondary` directly; `warmth` and `intensity` are always computed.

### FR-39.08 — Config Namespace Schema

The full `universes.config` object has this top-level structure:

```json
{
  "composition": { ... },
  "seed": 12345678901234567,
  "memory": { "working_memory_size": 5, "compression_threshold_tokens": 4000, ... },
  "propagation": { "max_propagation_depth": 3, "min_propagation_severity": "notable", ... },
  "social": { "gossip_familiarity_threshold": 30, "max_gossip_hops": 2 },
  "time": { "ticks_per_turn": 1, "minutes_per_tick": 60, ... },
  "genesis": { "narrator_phase": "void", ... }
}
```

- **FR-39.08a**: The `seed` key lives at the top level of `config` (not inside
  `composition`), so it is accessible without parsing the composition block.
- **FR-39.08b**: All subsystem namespace keys (`memory`, `propagation`, `social`,
  `time`, `genesis`) are optional. Each subsystem uses its own defaults if the
  key is absent.
- **FR-39.08c**: Unknown top-level keys MUST be preserved and ignored
  (forward-compat rule inherited from S29 FR-29.08a).

### FR-39.09 — CompositionValidator

A `CompositionValidator` is called:
1. At universe creation (S40 genesis flow)
2. When `config` is updated via the admin API (S26)

Validation rules:
- `composition_version` MUST be a recognized version string.
- `themes` MUST have ≤ 5 entries (configurable via
  `universes.config["composition"]["max_themes"]`, default 5).
- `tropes` MUST have ≤ 10 entries (default max).
- `archetypes` MUST have ≤ 8 entries (default max).
- `genre_twists` MUST have ≤ 3 entries (default max).
- All `weight`/`strength` fields MUST be in [0.0, 1.0].
- `npc_tier` in ArchetypeSpec MUST be `"key"` or `"supporting"`.
- `pacing` MUST be one of `["slow", "balanced", "fast"]`.
- `description_density` MUST be one of `["sparse", "medium", "rich"]`.
- Theme/trope/archetype/genre-twist `name` values MUST be lowercase_underscore
  identifiers (regex: `^[a-z][a-z0-9_]*$`). Unknown names are allowed (open
  vocabulary) — S41 will define a canonical library.

Validation failure raises `CompositionValidationError` (a subclass of
`TemplateValidationError` from the v1 template registry).

### FR-39.10 — Composition Context Injection

At context assembly time (before generation), the `UniverseComposition` is
serialized to a concise prompt fragment injected as `"universe_composition"`
in the generation context. The fragment MUST include:
- Primary genre
- Active themes (name + weight ≥ 0.4)
- Required tropes (`required = true`)
- Prose voice and pacing
- Primary tone

The full composition is NOT injected verbatim — only the above subset.
Universe authors may set `prose.description_density = "rich"` to get more
detail injected (trope list, archetype list).

### FR-39.11 — Seed Immutability

The `seed` value in `universes.config` is set once at universe creation.
Any subsequent admin `PATCH /admin/universes/{id}` that attempts to change
the `seed` MUST be rejected with HTTP 409 and error category `state_conflict`.

### FR-39.12 — Empty Config Is Valid

An empty `config = {}` is always valid (S29 AC-29.11 requirement). When
`config["composition"]` is absent, a default `UniverseComposition` with
no themes, tropes, archetypes, or genre-twists is used. The `seed` is
automatically populated at first session open if absent.

---

## 5. Non-Functional Requirements

### NFR-39.01 — Validation Latency
`CompositionValidator.validate()` MUST complete in under 5 ms.

### NFR-39.02 — Parse Latency
Parsing `UniverseComposition` from `config` MUST complete in under 2 ms.

### NFR-39.03 — Observability
Every `CompositionValidator.validate()` call MUST emit a structlog event with
`universe_id`, `composition_version`, and `validation_result` (`ok` or `error`).

### NFR-39.04 — Test Coverage
Unit tests MUST cover: valid full composition, empty composition (defaults),
all validation error paths (each rule), seed immutability rejection,
ToneProfile derivation, and context injection fragment correctness.

---

## 6. User Journeys

### Journey 1: Author Creates a Gothic Horror Universe

Universe author POSTs to `POST /admin/universes` with:
```json
{
  "name": "The Hollow Court",
  "config": {
    "composition": {
      "composition_version": "1.0",
      "primary_genre": "gothic_horror",
      "themes": [
        {"name": "decay", "weight": 0.8},
        {"name": "redemption", "weight": 0.4}
      ],
      "tropes": [
        {"name": "corrupted_bloodline", "weight": 0.7, "required": true},
        {"name": "unreliable_narrator", "weight": 0.5}
      ],
      "archetypes": [
        {"name": "corrupted_mentor", "npc_tier": "key"},
        {"name": "threshold_guardian", "npc_tier": "supporting"}
      ],
      "genre_twists": [
        {"name": "cozy_dark", "strength": 0.3}
      ],
      "prose": {
        "voice": "lyrical",
        "pacing": "slow",
        "description_density": "rich"
      }
    },
    "memory": {"compression_threshold_tokens": 6000}
  }
}
```

1. `CompositionValidator.validate()` runs — all rules pass.
2. A random `seed` is generated and stored in `config["seed"]`.
3. `ToneProfile` is derived: `primary = "dark"`, `warmth = 0.25`, `intensity = 0.7`.
4. Universe persisted to Postgres. Config blob stored intact.

### Journey 2: Playtester Reproduces a Session

1. Playtester notes `seed = 9182736450` from their session's universe.
2. Admin creates a new universe with the same config blob + `seed = 9182736450`.
3. First session opened on this universe generates identical world state.
4. Playtester can compare narratives across two sessions with identical inputs.

### Journey 3: Context Assembly Injects Composition Fragment

At generation time, the context assembler calls `get_composition_context()`:

```
Genre: gothic_horror
Themes: decay (strong), redemption (mild)
Required tropes: corrupted_bloodline
Prose voice: lyrical | pacing: slow | description: rich
Tone: dark (warm=0.25, intensity=0.7)
```

This fragment is prepended to the generation system prompt, biasing the LLM
toward appropriate style and content.

---

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | `config["composition"]` is absent | Use default `UniverseComposition`; auto-generate seed at first session open |
| E2 | Theme count exceeds max (>5) | `CompositionValidationError` at creation/update |
| E3 | Unknown theme name | Allowed; logged DEBUG; open vocabulary |
| E4 | Admin attempts to change `seed` | HTTP 409 `state_conflict` |
| E5 | `pacing = "warp-speed"` (invalid) | `CompositionValidationError` |
| E6 | `weight = 1.5` (out of range) | `CompositionValidationError` |
| E7 | `config` is a JSON array (not object) | Rejected at S29 level (FR-29.08a requires object); `CompositionValidationError` |
| E8 | Empty `themes = []`, empty `tropes = []` | Valid; default composition with no thematic bias |

---

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Universe Composition Model

  Scenario: AC-39.01 — Full composition is validated and stored
    Given a valid universe creation payload with themes, tropes, archetypes, genre_twists
    When POST /admin/universes is called
    Then the universe is created with a seed populated in config
    And CompositionValidator emits a validation_result = "ok" log event

  Scenario: AC-39.02 — Empty config uses default composition
    Given a universe creation with config = {}
    When the first session is opened
    Then a seed is generated and stored in config["seed"]
    And composition defaults apply (no themes, no tropes, primary_genre = "fantasy")

  Scenario: AC-39.03 — Too many themes fails validation
    Given a composition with 6 theme entries
    When CompositionValidator.validate() is called
    Then a CompositionValidationError is raised
    And the error message references the max_themes limit

  Scenario: AC-39.04 — Weight out of range fails validation
    Given a theme with weight = 1.5
    When CompositionValidator.validate() is called
    Then a CompositionValidationError is raised

  Scenario: AC-39.05 — Seed is immutable after creation
    Given universe U1 with seed = 9182736450
    When admin attempts PATCH /admin/universes/U1 with config["seed"] = 99
    Then the response is HTTP 409
    And the error category is "state_conflict"

  Scenario: AC-39.06 — ToneProfile is derived from themes
    Given a composition with themes ["cosmic_horror" weight=0.9, "existential_dread" weight=0.8]
    When UniverseComposition is parsed
    Then ToneProfile.warmth is low (< 0.3)
    And ToneProfile.intensity is high (> 0.7)

  Scenario: AC-39.07 — Composition context fragment injected at generation time
    Given a universe with primary_genre = "gothic_horror" and prose.voice = "lyrical"
    When get_composition_context() is called
    Then the fragment includes "gothic_horror" and "lyrical"

  Scenario: AC-39.08 — Subsystem config namespaces are preserved
    Given a universe with config["memory"]["compression_threshold_tokens"] = 6000
    When the universe config is retrieved
    Then config["memory"]["compression_threshold_tokens"] equals 6000
```

---

## 9. Out of Scope

- Canonical theme/trope/archetype library — that is S41 (Scenario Seed Library, v2.1+).
- User-generated seeds and community sharing — deferred to S63 (v5+).
- Theme weighting affecting NPC trait generation — generation prompt concern.
- Resonance correlation between universes based on shared themes — S56 (v4+).
- Composition diff/merge tooling — admin tooling concern, future spec.

---

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-39.01 | Universe deterministic given (seed, config)? | ✅ Resolved | **Yes, deterministic.** `seed` is stored immutably at creation and governs all stochastic world generation. Enables playtester reproducibility and scenario seed sharing (S41). |
| OQ-39.02 | Where does `seed` live — inside `composition` or at `config` top-level? | ✅ Resolved | **Top-level** (`config["seed"]`), not inside `composition`. This makes seed accessible without parsing the composition block, and aligns with S29's intent. |
| OQ-39.03 | Theme/trope name validation — closed enum (must be in S41 library) or open vocabulary? | ✅ Resolved | **Open vocabulary** in v2.0. Unknown names are logged and allowed; S41 defines the canonical library. Closed-enum enforcement deferred to v2.1 when S41 exists. |
| OQ-29.01 | Does `config: {}` have semantic meaning ("use platform defaults"), or must S39 always pre-populate content? | ✅ Resolved (from S29) | Empty config is always valid. Defaults apply. Seed is auto-populated at first session open if absent. |

---

## Appendix A — UniverseComposition Dataclass Shape

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class ThemeSpec:
    name: str
    weight: float = 0.5         # [0.0, 1.0]
    description: str | None = None

@dataclass
class TropeSpec:
    name: str
    weight: float = 0.5         # [0.0, 1.0]
    required: bool = False
    description: str | None = None

@dataclass
class ArchetypeSpec:
    name: str
    npc_tier: Literal["key", "supporting"] = "supporting"
    description: str | None = None

@dataclass
class GenreTwist:
    name: str
    strength: float = 0.5       # [0.0, 1.0]
    description: str | None = None

@dataclass
class ProseConfig:
    voice: str = "default"
    pacing: Literal["slow", "balanced", "fast"] = "balanced"
    description_density: Literal["sparse", "medium", "rich"] = "medium"
    second_person: bool = True

@dataclass
class ToneProfile:
    primary: str = "neutral"
    secondary: str | None = None
    warmth: float = 0.5         # derived
    intensity: float = 0.5      # derived

@dataclass
class UniverseComposition:
    composition_version: str = "1.0"
    primary_genre: str = "fantasy"
    themes: list[ThemeSpec] = field(default_factory=list)
    tropes: list[TropeSpec] = field(default_factory=list)
    archetypes: list[ArchetypeSpec] = field(default_factory=list)
    genre_twists: list[GenreTwist] = field(default_factory=list)
    prose: ProseConfig = field(default_factory=ProseConfig)
    tone: ToneProfile = field(default_factory=ToneProfile)

    @classmethod
    def from_config(cls, config: dict) -> "UniverseComposition":
        comp = config.get("composition", {})
        # parse + validate; return instance or raise CompositionValidationError
        ...

    def get_context_fragment(self) -> str:
        """Returns the concise prompt fragment for context injection."""
        ...
```

## Appendix B — Config Namespace Reference

```
universes.config (top-level keys):

  seed                   uint64   Deterministic generation seed. Immutable.       [S39]
  composition            object   UniverseComposition schema.                      [S39]
  memory                 object   World Memory Model config.                       [S37]
    working_memory_size    int      Default: 5
    compression_threshold_tokens  int  Default: 4000
    compression_importance_threshold  float  Default: 0.5
    memory_half_life_ticks  int    Default: 50
  propagation            object   Consequence Propagation config.                  [S36]
    max_propagation_depth  int      Default: 3
    min_propagation_severity  str  Default: "notable"
  social                 object   NPC Social config.                               [S38]
    gossip_familiarity_threshold  int  Default: 30
    max_gossip_hops        int      Default: 2
  time                   object   Diegetic Time config.                            [S34]
    ticks_per_turn         int      Default: 1
    seconds_per_tick       int      Default: 3600
  genesis                object   Genesis v2 config.                               [S40]
    narrator_phase         str      Default: "void"
```

## Appendix C — Relationship to S41 (Scenario Seed Library)

S41 (v2.1) will define a library of named scenario seeds. Each seed is a
tuple of `(name, config_blob)` where `config_blob` contains a pre-filled
`composition` block (themes, tropes, archetypes, genre-twists) and subsystem
config overrides. S41 seeds are directly usable as `universes.config` values.

Example S41 seed (non-normative):
```json
{
  "seed": "dirty_frodo",
  "config": {
    "seed": 1234567890,
    "composition": {
      "primary_genre": "epic_fantasy",
      "themes": [{"name": "corruption_of_power", "weight": 0.9}],
      "genre_twists": [{"name": "noir_detective", "strength": 0.6}],
      "prose": {"voice": "hardboiled", "pacing": "balanced"}
    }
  }
}
```
