# v2.1 Evaluation & Playtesting — Component Technical Plan

> **Phase**: SDD Phase 2 — Component Technical Plan
> **Scope**: Scenario Seed Library, LLM Playtester Harness, Human Playtester
>   Program, Narrative Quality Evaluation, Evaluation Pipeline
> **Input specs**: S41, S42, S43, S44, S45
> **Parent plan**: `plans/system.md` (authoritative)
> **Depends on**: `plans/v2-universe-and-simulation.md` (v2.0 must ship first —
>   fulfilled; v2.0 merged 2026-05-12)
> **Status**: ✅ Approved (promoted from stub 2026-05-13)
> **Last Updated**: 2026-05-13

---

## 0. Resolved Conflicts and Normative Decisions

These decisions are **locked** for v2.1. Component code must comply.

| # | Decision |
|---|----------|
| 0.1 | v2.1 is a **CLI pipeline**, not an API server feature. Entry point: `python -m tta.eval`. No routes, no SSE, no streaming. |
| 0.2 | PlaytesterAgent communicates with TTA via the **public HTTP API** (`POST /api/v1/games`, `POST .../turns`, `GET .../stream`). It does not import pipeline internals. |
| 0.3 | Langfuse is the **metrics destination** for eval results. Each batch run produces trace with tag `playtester_run_id`. S45 ships per-category scores as Langfuse scores. |
| 0.4 | Category weights are **locked** at: Coherence 0.25, Tension 0.15, Wonder 0.20, Character Depth 0.20, Genre Fidelity 0.10, Consequence Weight 0.10. These are OQ-v2.1-01 resolved. |
| 0.5 | S43 human feedback is stored in a **separate directory tree** (`data/human_feedback/`), not in the game session database. PII-adjacent per S17 retention policy. |
| 0.6 | Taste profiles use **±15% jitter** on float fields per persona instantiation. Jitter is deterministic given the `persona_jitter_seed`. |
| 0.7 | The 5 built-in personas are canonical and versioned in code. Custom personas can be added as YAML files under `data/personas/`. |
| 0.8 | CI mode runs 20 sessions (4 seeds × 5 personas × 1 rep). Full mode allows override. Regression threshold: 0.10 delta triggers CI failure (OQ-v2.1-02 resolved). |
| 0.9 | Human playtester intake is a **module in the main app** (not a separate service). OQ-v2.1-06 resolved. |
| 0.10 | Compensation model is a gift card (~$15–25 USD equivalent). Final amount TBD by ops; plan locks the mechanism, not the dollar value. OQ-v2.1-03 resolved. |

---

## 0-bis. Architecture Review Decisions (v2.1 Gate)

These decisions from `plans/v2_1-architecture-review.md` (completed 2026-05-14)
are **locked** and affect v2.1 evaluation/playtesting implementation:

| AR # | Decision | Impact on this plan |
|------|----------|---------------------|
| #5 | Structured output: prompt + Pydantic validation | Quality evaluators (`quality/evaluator.py`) use strong prompt template with JSON example, Pydantic `model_validate()`, 1 retry. No instructor/pydantic-ai. |
| #6 | arq workers for background tasks | Playtester sessions run in arq workers, not the API process. `EvaluationPipeline` enqueues `run_playtester_session` jobs. NPC autonomy fire-and-forget after turns. |
| #8 | htmx UI | Playtester feedback intake uses htmx-enhanced `static/index.html` with SSE streaming + choice buttons. No SPA framework. |
| #12 | Rate-limit budget | Playtester sessions use HIGH tier (cap: 3 concurrent). Quality evaluation LLM calls use HIGH tier. Player turns use CRITICAL tier (never throttled). Spec: `specs/50-rate-limit-budget.md`. |
| #13 | ttadev dependency | `ttadev>=0.1.0-alpha` from GitHub release. RetryPrimitive wraps LLM calls in playtester sessions. CachePrimitive caches scenario seeds and Genesis phase outputs. |

### Task routing (Decision #6)

| Task | Process | Priority tier |
|------|---------|---------------|
| Player turn pipeline | API process (in-process) | CRITICAL |
| Playtester sessions | arq worker | HIGH (cap: 3) |
| Quality evaluation (per-session) | arq worker | HIGH |
| NPC autonomy | arq worker (fire-and-forget) | LOW (cap: 2) |
| Consequence propagation | arq worker (after NPC autonomy) | LOW |
| Scenario seed loading | In-process (on-demand) | N/A (cached) |

## 1. Module Layout

```
src/tta/
  seeds/                    # S41 — Scenario Seed Library
    __init__.py             # Re-exports: SeedManifest, SeedRegistry, SeedValidator
    manifest.py             # SeedManifest dataclass + YAML parsing
    registry.py             # SeedRegistry: load, get, list, filter
    validator.py            # SeedValidator: schema + composition validation

  playtest/                 # S42 — LLM Playtester Agent Harness
    __init__.py             # Re-exports: PlaytesterAgent, TasteProfile, PlaytestReport
    agent.py                # PlaytesterAgent: session lifecycle (create → play → report)
    profile.py              # TasteProfile dataclass + BUILTIN_PERSONAS + from_template()
    report.py               # PlaytestReport, TurnRecord, Commentary, RunStatus

  playtester/               # S43 — Human Playtester Program
    __init__.py             # Re-exports
    models.py               # HumanFeedbackRecord, consent models
    consent.py              # Consent gate check, withdrawal logic
    aggregate.py            # Feedback aggregation, NOT_VALIDATED_THRESHOLD

  quality/                  # S44 — Narrative Quality Evaluation
    __init__.py             # Re-exports: NarrativeQualityEvaluator, ...
    models.py               # CategoryScore, NarrativeQualityReport, Verdict, thresholds
    evaluator.py            # NarrativeQualityEvaluator: 6-category scoring
    feedback.py             # FeedbackRecord (human feedback wrapper)

  eval/                     # S45 — Evaluation Pipeline
    __init__.py
    __main__.py             # CLI: python -m tta.eval [--mode ci|local|full]
    models.py               # BatchConfig, PlannedRun, RunResult, RegressionResult, BatchEvalResult
    pipeline.py             # EvaluationPipeline: 9-step orchestrator
```

### 1.1 — Data Directories

```
data/
  seeds/                    # S41 canonical seeds (YAML)
    bus-stop-shimmer.yaml
    cafe-with-strange-symbols.yaml
    dirty-frodo.yaml
    library-forbidden-book.yaml
  personas/                 # S42 taste profile templates (YAML)
    curious-explorer.yaml
    verbose-narrator.yaml
    terse-minimalist.yaml
    impulsive-actor.yaml
    disengaged-skeptic.yaml
  eval_baseline.json        # S45 regression baseline
  eval_output/              # S45 batch output directory
  human_feedback/           # S43 consent + feedback records
```

---

## 2. Seed Library (S41)

### 2.1 — SeedManifest Schema

```python
@dataclass
class SeedManifest:
    id: str                    # Machine ID (kebab-case)
    name: str                  # Human-readable title
    description: str           # 1–3 sentence teaser
    version: str               # Semver ("1.0.0")
    author: str                # Author attribution
    tags: list[str]            # Discovery tags
    audience: str              # "general" | "mature" | "young_adult"
    created_at: str            # ISO 8601
    composition: UniverseComposition  # S39 composition blob
```

### 2.2 — SeedRegistry Contract

```python
class SeedRegistry:
    def __init__(self, seeds_dir: Path) -> None:
        """Load all *.yaml files from seeds_dir. Invalid files are skipped
        with error-level log. Duplicate IDs reject both (AC-41.05)."""

    def get(self, seed_id: str) -> SeedManifest | None: ...

    def list(self, tags: list[str] | None = None,
             genre: str | None = None) -> list[SeedManifest]:
        """Returns seeds sorted alphabetically by ID (AC-41.03)."""

    def loaded_count(self) -> int: ...
```

### 2.3 — Genesis Integration (AC-41.06)

Genesis v2 (`src/tta/genesis/genesis_v2.py`) imports `SeedRegistry` and calls
`registry.get(seed_id)` to load a seed's `UniverseComposition` during universe
creation. When no seed_id is provided, Genesis prompts the player to build the
world from scratch (v1 S02 compat path).

---

## 3. Playtester Agent Harness (S42)

### 3.1 — TasteProfile

```python
@dataclass(frozen=True)
class TasteProfile:
    verbosity: float           # 0.0 terse – 1.0 verbose
    boldness: float            # 0.0 cautious – 1.0 impulsive
    curiosity: float           # 0.0 passive – 1.0 probing
    genre_affinity: str        # e.g. "horror", "comedy"
    tone_affinity: str         # e.g. "dark", "hopeful"
    trope_affinity: tuple[str, ...]  # 0–3 tropes
    attention_span: float      # 0.0 disengages fast – 1.0 full session
    meta_awareness: float      # 0.0 in-world – 1.0 game-mechanics commentary
```

5 built-in personas: `curious-explorer`, `verbose-narrator`, `terse-minimalist`,
`impulsive-actor`, `disengaged-skeptic`. Each is a YAML file under `data/personas/`.

Jitter: float fields receive ±15% random nudge using `persona_jitter_seed` at
instantiation time. Clamped to [0.0, 1.0].

### 3.2 — PlaytesterAgent Contract

```python
class PlaytesterAgent:
    def __init__(self, api_base_url: str, llm_client: LLMClient,
                 llm_model: str | None = None, api_key: str | None = None) -> None: ...

    async def run_session(
        self, scenario_seed_id: str, persona_id: str,
        run_seed: int, persona_jitter_seed: int = 0
    ) -> PlaytestReport:
        """Full lifecycle: create game → play Genesis → 5+ turns → commentary.
        AC-42.01: complete session. AC-42.02: commentary on every turn.
        AC-42.03: reproducible given same seeds.
        AC-42.04: terse persona exercises AC-2.8 path.
        AC-42.05: 3 consecutive timeouts → abandoned status."""

    def _build_persona_prompt(self, current_turn: TurnRecord) -> str:
        """Generate the next player response using profile-tuned LLM call.
        Terse persona produces single-word/one-line responses (AC-42.04)."""

    def _produce_commentary(self, turn: TurnRecord) -> Commentary:
        """Agent-side commentary: what it intended, what surprised it,
        whether it felt the narrative was coherent."""

    def _check_abandonment(self) -> bool:
        """3 consecutive API timeouts → abandoned status (AC-42.05)."""
```

### 3.3 — PlaytestReport

```python
@dataclass
class PlaytestReport:
    run_id: str
    scenario_seed_id: str
    persona_id: str
    run_seed: int
    status: RunStatus            # "complete" | "abandoned" | "error"
    turns: list[TurnRecord]
    genesis_character_name: str
    genesis_traits: list[str]
    total_turns: int
    started_at: str
    finished_at: str

@dataclass
class TurnRecord:
    turn_number: int
    player_input: str
    narrative_output: str
    commentary: Commentary

@dataclass
class Commentary:
    intent: str                  # What the agent intended to do
    surprise: str                # What surprised it
    coherence: str               # Coherence assessment
```

---

## 4. Human Playtester Program (S43)

### 4.1 — HumanFeedbackRecord

```python
@dataclass
class HumanFeedbackRecord:
    feedback_id: str             # ULID
    playtester_id: str           # Anonymized participant ID
    session_id: str              # TTA game session ID
    scenario_seed_id: str
    submitted_at: datetime

    # Structured scores (1–5 Likert)
    coherence_score: int
    pacing_score: int
    character_depth_score: int
    choice_impact_score: int
    wonder_score: int
    genre_fidelity_score: int

    # Free-text
    best_moment: str
    worst_moment: str
    suggestions: str

    # Metadata
    consent_granted: bool
    consent_withdrawn: bool      # AC-43.03: triggers data deletion
    completed_full_session: bool
```

### 4.2 — Consent Gate

`playtester/consent.py` provides `check_consent_gate(record) -> bool`.
When `consent_withdrawn` is True, the record is excluded from aggregation
and flagged for deletion (AC-43.03).

### 4.3 — Aggregation

`playtester/aggregate.py` aggregates Likert scores across playtesters.
`NOT_VALIDATED_THRESHOLD = 3.0` — median below this value triggers
NOT VALIDATED signal (AC-43.04).

### 4.4 — Process

S43 is a **manual process** with programmatic support:
1. Coordinator recruits playtesters, distributes access tokens
2. Playtesters play a scenario and submit the feedback form
3. Feedback JSON files are stored in `data/human_feedback/`
4. S45 release mode ingests feedback files for combined scoring

---

## 5. Narrative Quality Evaluation (S44)

### 5.1 — Six Quality Categories

| ID | Category | Scoring Source | Weight |
|----|----------|---------------|--------|
| QC-01 | Coherence | Automated (commentary sentiment + continuity checks) | 0.25 |
| QC-02 | Tension | Automated (turn pacing, choice density) | 0.15 |
| QC-03 | Wonder | Human feedback only (S43) | 0.20 |
| QC-04 | Character Depth | Automated (character trait diversity, arc detection) | 0.20 |
| QC-05 | Genre Fidelity | LLM-assisted (compares output to seed's genre/tropes) | 0.10 |
| QC-06 | Consequence Weight | Automated (consequence count, propagation depth) | 0.10 |

### 5.2 — NarrativeQualityEvaluator Contract

```python
class NarrativeQualityEvaluator:
    def __init__(self, llm_client: LLMClient | None = None) -> None: ...

    async def evaluate(
        self,
        report: PlaytestReport,
        *,
        feedback: FeedbackRecord | None = None,
        seed: SeedManifest | None = None,
        genesis_character_name: str = "",
        genesis_traits: list[str] | None = None,
        consequence_count: int = 0,
        expected_consequence_turns: int | None = None,
    ) -> NarrativeQualityReport:
        """Score all 6 categories (AC-44.01).
        QC-03 marked not_evaluated when no human feedback (AC-44.02).
        Character depth fails if trait diversity below threshold (AC-44.03).
        Fail verdict when any category below 0.40 (AC-44.04).
        Inconclusive when 3+ categories not_evaluated (AC-44.05)."""
```

### 5.3 — Verdict Logic

```python
def _compute_verdict(categories: list[CategoryScore]) -> Verdict:
    scored = [c for c in categories if c.status == "scored"]

    if any(c.status == "failed" and (c.score or 0) < FAIL_INDIVIDUAL_THRESHOLD
           for c in scored):
        return "fail"                             # AC-44.04

    not_evaluated = sum(1 for c in categories
                        if c.status == "not_evaluated")
    if not_evaluated >= INCONCLUSIVE_MIN_NOT_EVALUATED:
        return "inconclusive"                     # AC-44.05

    composite = sum(
        c.score * CATEGORY_WEIGHTS.get(c.category_id, 0)
        for c in scored
    )
    return "pass" if composite >= PASS_COMPOSITE_THRESHOLD else "fail"
```

---

## 6. Evaluation Pipeline (S45)

### 6.1 — CLI Interface

```bash
python -m tta.eval --mode ci --api-base-url http://localhost:8000
```

| Flag | Default | Description |
|------|---------|-------------|
| `--mode` | `ci` | `ci` (20 runs), `local` (configurable), `full` (includes human feedback) |
| `--api-base-url` | `""` | TTA API base URL |
| `--api-key` | `None` | TTA API key |
| `--baseline` | `data/eval_baseline.json` | Baseline scores for regression detection |
| `--output-dir` | `data/eval_output` | Output directory for reports |
| `--human-feedback-dir` | `None` | Human feedback JSON files (release mode) |

### 6.2 — Pipeline Steps

```python
class EvaluationPipeline:
    async def run(self) -> tuple[BatchEvalResult, int]:
        """9-step pipeline:

        1. plan_runs()        → list[PlannedRun]           (seeds × personas × reps)
        2. run_llm_playtesters() → list[RunResult]         (parallel, bounded)
        3. score_sessions()   → list[NarrativeQualityReport]
        4. compute_medians()  → dict[category, float]
        5. check_regressions() → list[RegressionResult]
        6. ingest_human_feedback() → dict[category, HumanFeedbackRecord]  (full mode only)
        7. emit_langfuse()    → ships scores to Langfuse
        8. write_report()     → JSON to output_dir
        9. emit_verdict()     → exit code (0=pass, 1=fail/regression, 2=error_rate)

        AC-45.01: CI mode runs 20 sessions, produces verdict.
        AC-45.02: Category regression <-0.10 triggers CI failure.
        AC-45.03: All sessions logged to Langfuse.
        AC-45.04: >25% error runs → abort.
        AC-45.05: Release mode ingests human feedback.
        """
```

### 6.3 — CI Integration

The test at `tests/unit/eval/test_s45_ac_compliance.py` covers all 5 S45 ACs.
The pipeline is designed to be called from a GitHub Actions workflow:

```yaml
- name: Evaluation Pipeline
  run: |
    op run -- python -m tta.eval --mode ci --api-base-url "$TTA_API_URL"
```

---

## 7. Settings

No new settings in `src/tta/config.py` for v2.1 — configuration is CLI-driven
via `BatchConfig`. Environment variables:

| Variable | Default | Used By |
|----------|---------|---------|
| `PLAYTEST_TURN_TIMEOUT` | 60 | PlaytesterAgent: max seconds per turn |
| `PLAYTEST_MIN_TURNS` | 5 | PlaytesterAgent: minimum gameplay turns |
| `PLAYTEST_LLM_MODEL` | `gpt-4o-mini` | PlaytesterAgent: LLM model for persona responses |
| `TTA_API_URL` | — | CI: TTA API endpoint for playtesting |

---

## 8. Testing Strategy

### 8.1 — Unit Tests (All ACs Covered)

| Module | Test file | ACs | Tests |
|--------|-----------|-----|-------|
| `seeds/` | `tests/unit/seeds/test_s41_ac_compliance.py` | AC-41.01–06 | 16 |
| `playtest/` | `tests/unit/playtest/test_s42_ac_compliance.py` | AC-42.01–05 | 5 |
| `playtester/` | `tests/unit/playtester/test_s43_ac_compliance.py` | AC-43.01–04 | 16 |
| `quality/` | `tests/unit/quality/test_s44_ac_compliance.py` | AC-44.01–05 | 15 |
| `eval/` | `tests/unit/eval/test_s45_ac_compliance.py` | AC-45.01–05 | 24 |

**Total**: 76 tests, 25/25 ACs, 0 skips, 100% pass rate.

All tests carry `@pytest.mark.spec("AC-NN.MM")` markers per the AC traceability
standard in `AGENTS.md`.

### 8.2 — Integration Tests

Future work (not blocking v2.1 ship):
- `tests/integration/eval/test_pipeline_e2e.py` — full pipeline run against live TTA
- `tests/integration/playtest/test_agent_live.py` — PlaytesterAgent against live API

These require a running TTA instance and are deferred until CI infrastructure
exists to spin one up in the eval workflow.

### 8.3 — BDD Tests

No Gherkin scenarios for v2.1 — the specs carry Given/When/Then scenarios but
the pipeline is a CLI tool, not a user-facing feature. BDD is reserved for
player-facing features (S01–S06, S10, S27).

---

## 9. Compatibility

| Source | Interaction |
|--------|------------|
| v1 `plans/system.md` | No conflicts. v2.1 adds no new database tables. Human feedback stored in filesystem. |
| v1 `plans/ops.md` | Langfuse already integrated. S45 adds tagged traces with scores. No infra changes. |
| v1 `plans/llm-and-pipeline.md` | PlaytesterAgent consumes the public API — no changes to TurnState or pipeline internals. |
| v2 `plans/v2-universe-and-simulation.md` | S41 seeds consume S39 UniverseComposition (locked by v2 §0.8). S42 consumes S40 Genesis flow. No overlap in locked sections. |
| v1 S17 (Privacy) | Human feedback records stored separately from game session DB. Consent withdrawal triggers deletion per S17 retention policy. |

---

## 10. Wave Implementation Order

### Completed Waves

| Wave | Specs | Deliverables | Status |
|------|-------|-------------|--------|
| v2.1-Wave-01 | S41 | `SeedRegistry`, `SeedValidator`, `SeedManifest`, 4 canonical seeds, 16 tests | ✅ Done |
| v2.1-Wave-02 | S42 | `PlaytesterAgent`, 5 taste profiles, `TasteProfile.from_template()`, `PlaytestReport`, 5 tests | ✅ Done |
| v2.1-Wave-03 | S44 | `NarrativeQualityEvaluator`, 6-category scoring, `CategoryScore`, `NarrativeQualityReport`, verdict logic, 15 tests | ✅ Done |
| v2.1-Wave-04 | S45 | `EvaluationPipeline`, 9-step orchestrator, CLI entry point, `BatchConfig`, regression detection, Langfuse shipping, 24 tests | ✅ Done |

### Remaining Work

| Wave | Specs | Deliverables |
|------|-------|-------------|
| v2.1-Wave-05 | S43 | Human intake form schema, consent templates, coordinator tooling, `data/human_feedback/` storage |
| v2.1-Wave-06 | S44 (extend) | Human-signal evaluators; combined automated+human rubric weighting |
| v2.1-Wave-07 | S45 (extend) | Release mode with human feedback ingestion; release-level verdict |

Waves 05–07 are gated on operational decisions (recruitment, legal review of
consent text, compensation mechanism) rather than engineering work. The
engineering surface for S43 exists (models, consent gate, aggregation); the
remaining work is process + deployment.

---

## 11. Open Questions — Resolution

| ID | Question | Resolution |
|----|----------|-----------|
| OQ-v2.1-01 | Rubric category weights | Locked at §0.4. Weights from `quality/models.py`. |
| OQ-v2.1-02 | CI threshold | Regression delta of 0.10 triggers CI failure (§0.8). |
| OQ-v2.1-03 | Human playtester compensation | Gift card model (§0.10). Exact amount TBD by ops. |
| OQ-v2.1-04 | Taste-profile distribution | Stratified: all 5 personas × all 4 seeds × 1 rep in CI mode (§0.8). |
| OQ-v2.1-05 | S45 CI mode gates deployment? | Flags only in v2.1. Gating deployment is a v3 decision. |
| OQ-v2.1-06 | S43 intake: separate service? | Module in main app (§0.9). No separate FastAPI service. |

---

## 12. Cross-References

### Specs Covered

S41, S42, S43, S44, S45

### Normative Sections

The following sections of this plan are **locked**:

- **§0** — Resolved Conflicts and Normative Decisions
- **§2.1** — SeedManifest schema
- **§3.1** — TasteProfile fields and jitter magnitude
- **§4.1** — HumanFeedbackRecord schema
- **§5.1** — Quality category weights and verdict thresholds
- **§6.1** — CLI interface contract
- **§8.1** — Test coverage assertions

### Compatibility with Other Plans

| Plan | Sections Affected |
|------|------------------|
| `system.md` | No changes. v2.1 adds no new infrastructure. |
| `v2-universe-and-simulation.md` | §2.3 (Genesis consumes SeedRegistry). No locked decisions changed. |
| `llm-and-pipeline.md` | No changes. PlaytesterAgent is an API consumer, not a pipeline stage. |
| `ops.md` | No changes. Langfuse traces added; no new services. |
| `prompts.md` | No changes. PlaytesterAgent uses its own prompt templates for persona simulation. |
