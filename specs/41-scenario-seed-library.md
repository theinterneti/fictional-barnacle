# S41 — Scenario Seed Library

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1
> **Implementation Fit**: ❌ Not Started
> **Level**: 2 — Content
> **Dependencies**: S39 (Universe Composition Model)
> **Related**: S40 (Genesis v2), S42 (LLM Playtester), S63 (Community, v5+)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S39 defines the composition schema for a universe — themes, tropes,
archetypes, genre-twists, prose, tone. S41 fills that schema with actual
content: a library of named, curated seeds that authors and players can
use as starting points.

A **scenario seed** is a complete, valid `UniverseComposition` value bundled
with metadata (name, description, tags, intended audience) and stored as a
YAML file under `data/seeds/`. The Genesis orchestrator (S40) can load a seed
by ID and apply it as the universe's composition config instead of asking the
player to build the world from scratch.

S41 defines:
- The YAML format for scenario seeds
- The canonical initial library (4 seeds from the old-TTA design heritage)
- The discovery registry and lookup contract
- Validation rules (extend S39's `CompositionValidator`)
- The authoring guide for adding new seeds

**User-generated seeds** are explicitly out of scope — that is S63 (Community).

---

## 2. Design Philosophy

### 2.1 Seeds Are Versioned Composition Values

A seed is not a world — it is a starting point. Two universes created from
the same seed with different random seeds will diverge from the first prompt.
Seeds guarantee *atmosphere*, not content.

### 2.2 YAML for Human Authoring

Seeds are edited by humans (content authors, narrative designers) who are not
necessarily engineers. YAML is readable, diff-friendly, and aligns with the
project's existing config conventions.

### 2.3 Open Registry, Closed Format

Any YAML file dropped into `data/seeds/` is discovered automatically. The
registry does not need manual registration. But the format is strict:
every seed is validated against the `SeedManifest` schema at load time.
Unknown composition names pass (S39 OQ-39.03 resolved), but schema
violations (wrong types, over-count limits) reject the file.

---

## 3. User Stories

> **US-41.1** — **As a** player who doesn't want to build a world from scratch,
> I can choose a named scenario ("The Strange Café") and begin immediately.

> **US-41.2** — **As a** universe author, I can reference a seed by ID in my
> universe config and know it will be validated and resolved at load time.

> **US-41.3** — **As a** narrative designer, I can add a new seed by dropping a
> YAML file into `data/seeds/` and running the validator — no code change needed.

> **US-41.4** — **As a** LLM playtester (S42), I can select a seed by tag
> (genre, difficulty, tone) to run diverse scenario coverage.

---

## 4. Data Contract — Seed Manifest

### 4.1 Top-Level Fields

```yaml
# data/seeds/<seed-id>.yaml
schema_version: "1.0"        # required; must be "1.0" in v2.1
id: bus-stop-shimmer          # required; unique slug; [a-z0-9-]+
name: "Bus Stop Shimmer"      # required; human display name
version: "1.0.0"             # required; semver; incremented on material changes
description: |               # required; 2-6 sentences
  A lonely bus stop on an ordinary evening. Time slips. The mundane
  becomes strange. A classic real-to-strange slip entry point.
tags:                         # required; 1-10 tags from the canonical tag list
  - strange-mundane
  - urban
  - slow-burn
  - beginner-friendly
intended_audience:            # optional; narrative hint, not enforced
  - first-time players
  - narrative explorers
composition:                  # required; a full UniverseComposition value (S39)
  primary_genre: urban_fantasy
  themes:
    - name: liminal_space
      weight: 0.9
    - name: mundane_mystery
      weight: 0.7
  tropes:
    - name: time_slip
      intensity: moderate
    - name: unreliable_narrator
      intensity: subtle
  archetypes:
    - name: the_witness
      role: protagonist
    - name: the_recurring_stranger
      role: guide
  genre_twists: []
  prose:
    voice: second_person
    tense: present
    register: literary
    paragraph_length: short
  tone:
    primary: melancholic
    secondary: wonder
    override: false
genesis_hints:                # optional; hints passed to the Genesis orchestrator
  slip_type: mundane          # sets config["genesis"]["slip_type"]
  starting_location: "A bus stop at dusk, Route 12."
  opening_mood: "Everything is ordinary. That is the problem."
```

### 4.2 Field Constraints

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `schema_version` | string | ✅ | Must be `"1.0"` in v2.1 |
| `id` | string | ✅ | `[a-z0-9-]+`; unique across all seeds in library; max 64 chars |
| `name` | string | ✅ | 3–80 chars; human-readable display name |
| `version` | string | ✅ | Semver: `MAJOR.MINOR.PATCH` |
| `description` | string | ✅ | 10–600 chars |
| `tags` | list[string] | ✅ | 1–10 tags; each tag `[a-z0-9-]+`; max 32 chars |
| `composition` | UniverseComposition | ✅ | Full S39 composition; validated by `CompositionValidator` |
| `genesis_hints` | object | ❌ | Forwarded to genesis orchestrator (S40); unknown keys logged, not rejected |
| `intended_audience` | list[string] | ❌ | Informational only |

### 4.3 Canonical Tag List

Tags from the list below are *recognized* (indexed for filtering). Unknown
tags are accepted but not indexed.

**Genre**: `fantasy`, `sci-fi`, `horror`, `mystery`, `romance`, `historical`,
`urban-fantasy`, `weird-fiction`, `fairy-tale`, `myth`

**Mood**: `dark`, `hopeful`, `melancholic`, `comedic`, `tense`, `wonder`,
`cozy`, `bleak`, `surreal`

**Entry Type**: `strange-mundane`, `portal`, `discovery`, `chase`, `ritual`,
`collapse`, `awakening`

**Difficulty**: `beginner-friendly`, `narrative-dense`, `mechanics-heavy`

**Setting**: `urban`, `rural`, `cosmic`, `subterranean`, `maritime`, `forest`

---

## 5. Canonical Initial Library

Four seeds ship with the v2.1 release. These are the TTA founding scenarios
from the old-TTA design heritage.

| Seed ID | Name | Heritage | Primary Genre | Tags |
|---------|------|----------|---------------|------|
| `bus-stop-shimmer` | Bus Stop Shimmer | old-TTA GDD | urban_fantasy | strange-mundane, urban, slow-burn, beginner-friendly |
| `cafe-with-strange-symbols` | The Café with Strange Symbols | old-TTA GDD | weird_fiction | strange-mundane, urban, mystery, wonder |
| `library-forbidden-book` | The Library with a Forbidden Book | old-TTA GDD | dark_fantasy | strange-mundane, discovery, narrative-dense |
| `dirty-frodo` | Dirty Frodo | old-TTA GDD | hardboiled_fantasy | portal, urban-fantasy, dark, mechanics-heavy |

### Dirty Frodo Notes

"Dirty Frodo" combines Tolkien-scale epic fantasy (themes, archetypes)
with hardboiled detective tropes and urban noir prose. The name is an
internal shorthand from the old-TTA GDD and is NOT surfaced to players
(the display name is "City of Thorns"). This seed demonstrates that
S39's composition vocabulary can express multi-genre combinations.

---

## 6. Functional Requirements

### FR-41.01 — File Layout

Seeds MUST live at `data/seeds/<id>.yaml`. The directory MUST be scanned
recursively; subdirectories are permitted for organization but do not affect IDs.

### FR-41.02 — Load and Validate at Startup

The `SeedRegistry` MUST load and validate all seeds at application startup
(FastAPI lifespan). Any seed that fails validation MUST log an ERROR and be
excluded from the registry. Startup MUST NOT fail due to an invalid seed;
only a WARNING is emitted (degraded-but-functional). If zero seeds load,
a CRITICAL log is emitted.

### FR-41.03 — Lookup by ID

`SeedRegistry.get(seed_id: str) -> SeedManifest | None`

Returns the seed or `None` if not found. No exception raised for missing seed.
Callers MUST handle `None`.

### FR-41.04 — List with Filter

`SeedRegistry.list(tags: list[str] | None = None,
                    genre: str | None = None) -> list[SeedManifest]`

Returns all loaded seeds, optionally filtered by tag intersection and/or
`primary_genre`. Empty filter returns all. Order: alphabetical by `id`.

### FR-41.05 — Composition Application

When a universe is created with a `seed_id` in its genesis config, the
Genesis orchestrator (S40) MUST call `SeedRegistry.get(seed_id)` and
apply `seed.composition` to the universe's `config["composition"]` block.
The `config["seed"]` (S39) is still auto-generated independently — the
scenario seed is NOT the universe's randomness seed.

### FR-41.06 — Immutable After Load

Seed manifests are read-only after the registry loads. Hot-reload of seeds
during runtime is out of scope. A restart is required to pick up new seeds.

### FR-41.07 — ID Collision Detection

If two seed files share the same `id`, the registry MUST reject both and
log an ERROR naming both file paths. Neither seed is available until the
collision is resolved.

### FR-41.08 — Versioning

When a seed file's `version` is bumped, existing universes that loaded a
prior version MUST NOT be affected. The seed version is stored in the
universe config at composition-apply time: `config["composition"]["seed_id"]`
and `config["composition"]["seed_version"]`. Future re-reads use the stored
snapshot, not the current library file.

---

## 7. SeedRegistry Contract

```python
@dataclass(frozen=True)
class SeedManifest:
    schema_version: str
    id: str
    name: str
    version: str
    description: str
    tags: list[str]
    composition: UniverseComposition  # S39
    genesis_hints: dict[str, Any]
    intended_audience: list[str]


class SeedRegistry:
    """Loaded at FastAPI lifespan start. Immutable after load."""

    def get(self, seed_id: str) -> SeedManifest | None: ...
    def list(
        self,
        tags: list[str] | None = None,
        genre: str | None = None,
    ) -> list[SeedManifest]: ...
    def loaded_count(self) -> int: ...
```

---

## 8. Validation Rules

`SeedValidator` extends `CompositionValidator` (S39) with seed-specific checks:

| Rule | Error class | Message |
|------|-------------|---------|
| `id` does not match `[a-z0-9-]+` | `SeedSchemaError` | "Seed ID must be lowercase alphanumeric with hyphens" |
| `id` longer than 64 chars | `SeedSchemaError` | "Seed ID exceeds 64-character limit" |
| `schema_version` != `"1.0"` | `SeedSchemaError` | "Unsupported schema_version: {value}" |
| `tags` empty | `SeedSchemaError` | "Seed must have at least one tag" |
| `tags` count > 10 | `SeedSchemaError` | "Seed exceeds 10-tag limit" |
| Composition invalid (S39 rules) | `CompositionValidationError` (re-raised) | S39 message |
| Duplicate `id` in registry | `SeedCollisionError` | "Duplicate seed id: {id} in {file1} and {file2}" |

---

## 9. Acceptance Criteria (Gherkin)

```gherkin
Feature: Scenario Seed Library

  Scenario: AC-41.01 — All canonical seeds load without error
    Given the data/seeds/ directory contains the 4 canonical seed files
    When the application starts
    Then SeedRegistry.loaded_count() == 4
    And no ERROR logs are emitted during seed loading

  Scenario: AC-41.02 — Lookup by ID returns correct seed
    Given the registry is loaded
    When SeedRegistry.get("bus-stop-shimmer") is called
    Then the returned SeedManifest has id = "bus-stop-shimmer"
    And composition.primary_genre = "urban_fantasy"

  Scenario: AC-41.03 — Filter by tag returns only matching seeds
    Given the registry is loaded with 4 seeds
    When SeedRegistry.list(tags=["strange-mundane"]) is called
    Then 3 seeds are returned (bus-stop-shimmer, cafe-with-strange-symbols, library-forbidden-book)
    And dirty-frodo is not in the result

  Scenario: AC-41.04 — Invalid seed file is excluded from registry
    Given a seed file with a missing required field (composition)
    When the application starts
    Then the invalid seed is excluded from the registry
    And an ERROR log is emitted naming the invalid file
    And all other valid seeds are still available

  Scenario: AC-41.05 — Duplicate seed ID rejects both
    Given two seed files share the same id
    When the application starts
    Then both seeds are excluded
    And an ERROR log names both file paths

  Scenario: AC-41.06 — Seed applied to universe composition at Genesis
    Given a universe config with genesis.seed_id = "bus-stop-shimmer"
    When Genesis Phase 2 begins
    Then config["composition"] is populated from the bus-stop-shimmer seed
    And config["composition"]["seed_id"] = "bus-stop-shimmer"
    And config["composition"]["seed_version"] = "1.0.0"
```

---

## 10. Out of Scope

- User-generated seeds — S63 (Community, v5+).
- Runtime seed editing or hot-reload.
- Seed recommendation / personalization.
- Seed marketplace, ratings, or social features.
- Procedurally generated seeds — seeds are curated, not generated.

---

## 11. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-41.01 | Scenario format — YAML, JSON, TOML? | ✅ Resolved | **YAML.** Human-editable, diff-friendly, consistent with project config conventions. Parsed by `pyyaml` at startup. |
| OQ-41.02 | Discovery — filesystem scan or registry file? | ✅ Resolved | **Filesystem scan** of `data/seeds/` at startup. No manual registry file needed. Recursive scan supports subdirectories for organization. |
| OQ-41.03 | Are seed IDs stable identifiers across versions? | ✅ Resolved | Yes. Seed IDs are stable; `version` field tracks revisions. Config snapshot at apply-time (FR-41.08) protects existing universes from library updates. |

---

## Appendix A — Canonical Seed Sketches

*(Non-normative. Full YAML files live in `data/seeds/`. These are author notes.)*

**bus-stop-shimmer**: Urban mundane. Evening. A city bus stop. The schedule
says the bus is due. It is always due. The player is waiting. They have
always been waiting. Themes: liminal space, mundane mystery. Tropes: time
slip, unreliable narrator. Prose: second-person present tense, literary.

**cafe-with-strange-symbols**: A café the player has been coming to for years.
Today the symbols in the menu are wrong. Or were they always like that?
Themes: hidden world, sacred ordinary. Tropes: occult signs, knowledge that
cannot be unknowed. Prose: intimate, first impressions, literary.

**library-forbidden-book**: A public library. A book that shouldn't be there.
The call number is wrong. The catalog doesn't show it. But the player can
hold it. Themes: forbidden knowledge, institutional uncanny. Tropes: cursed
object, the archivist who knows. Prose: deliberate, slightly formal, gothic.

**dirty-frodo** (display: "City of Thorns"): A city built on the ruins of an
ancient kingdom. Thieves, brokers of information, a corrupt ruling council.
The player is a fixer. Themes: moral ambiguity, fallen glory, loyalty.
Tropes: reluctant hero, corrupt institution, the one job that goes wrong.
Genre-twists: hardboiled-overlay (detective noir voice over epic-fantasy stakes).
Prose: hardboiled, short sentences, cynical register.
