# S44 — Narrative Quality Evaluation

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v2.1
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: S42 (LLM Playtester Agent Harness), S43 (Human Playtester Program)
> **Related**: S45 (Evaluation Pipeline)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S44 defines how a TTA narrative session is **scored**: the quality categories,
what each means, how each is computed, and what thresholds indicate pass/fail.

Two sources feed S44:
- **Automated signal** (S42): LLM playtester commentary, turn metadata, API
  response times, error counts
- **Human signal** (S43): participant feedback form scores and qualitative text

S44 outputs a `NarrativeQualityReport` for each evaluated session. The S45
pipeline aggregates these across a run batch and computes release-level
verdicts.

---

## 2. Quality Categories

Six categories. Each is scored 0.0–1.0. The scoring rubric for each is in
Appendix A.

| ID | Category | Definition | Primary Source |
|----|----------|------------|----------------|
| QC-01 | **Coherence** | The narrative is internally consistent: references to earlier events are accurate; character names and traits are stable; world details do not contradict themselves. | Automated (S42 commentary + rule checks) |
| QC-02 | **Tension** | The narrative maintains narrative drive: choices feel consequential; scenes escalate or resolve with purpose; the player is pulled forward. | Mixed (S42 commentary + S43 `q_consequence`) |
| QC-03 | **Wonder** | At least one moment in the session produced surprise, delight, or emotional resonance beyond mechanical expectation. | Human primary (S43 `q_wonder`); LLM secondary (S42 commentary `surprise_level`) |
| QC-04 | **Character Depth** | The player's character feels specific and shaped by their choices. Traits from Genesis appear in gameplay narrative. | Automated (S40 first-turn seed check) + Human (S43 `q_character`) |
| QC-05 | **Genre Fidelity** | The narrative is consistent with the scenario seed's declared primary genre, themes, and tone. Hardboiled fantasy stays hardboiled; horror maintains dread. | Automated (LLM genre-fidelity scorer) |
| QC-06 | **Consequence Weight** | Choices made by the player produce observable changes in the world state. S36 consequence records exist and are referenced in later narrative. | Automated (S36 ConsequenceRecord presence) + Human (S43 `q_consequence`) |

---

## 3. Scoring Methods

### 3.1 Coherence (QC-01) — Automated

Computed from S42 playtester commentary:
- Average `coherence_rating` across all commentary objects in the transcript
- Penalized by: any narrative contradiction detected (character name mismatch,
  location referenced before established, trait used inconsistently)
- Contradiction detection: rule-based checks against genesis_state fields

Formula: `coherence = mean(commentary.coherence_rating) * (1 - contradiction_count * 0.15)`

Clamped to [0.0, 1.0].

### 3.2 Tension (QC-02) — Mixed

- Automated component (0.6 weight): mean `surprise_level` from S42 commentary
  (higher surprise with no confusion = tension). Penalized by `api_turn_p95_ms > 5000`
  (slow turns break immersion).
- Human component (0.4 weight): `q_consequence` score from S43, normalized to [0.0, 1.0]
  (score / 5).

Formula: `tension = 0.6 * auto_tension + 0.4 * human_tension`

### 3.3 Wonder (QC-03) — Human Primary

- Human component (0.7 weight): `q_wonder` from S43, normalized to [0.0, 1.0].
- Automated component (0.3 weight): mean `surprise_level` from S42 commentary.

Wonder has no automated fallback if S43 data is absent: if no human data
exists, QC-03 is marked `not_evaluated` and excluded from release score.

### 3.4 Character Depth (QC-04) — Mixed

- Automated (0.5 weight): Did the first gameplay turn contain the character
  name AND a trait phrase from genesis_state? Boolean → 0.0 or 1.0.
- Human (0.5 weight): `q_character` from S43, normalized.

### 3.5 Genre Fidelity (QC-05) — Automated

An LLM call (separate from the playtester) receives:
1. The scenario seed's declared `primary_genre`, `themes`, and `tone`
2. A random sample of 5 narrative fragments from the session

The evaluator LLM scores genre fidelity on a 1–5 scale and returns a brief
rationale. Score is normalized to [0.0, 1.0]. If the LLM call fails, QC-05
is retried once; if still failing, it is marked `not_evaluated`.

### 3.6 Consequence Weight (QC-06) — Mixed

- Automated (0.6 weight): count of `ConsequenceRecord` entries (S36) in the
  session / expected_count. `expected_count = max(1, turns_played // 3)` (one
  consequence every 3 turns is the baseline expectation).
  Clamped to [0.0, 1.0].
- Human (0.4 weight): `q_consequence` from S43, normalized.

---

## 4. NarrativeQualityReport

```python
@dataclass
class CategoryScore:
    category_id: str           # "QC-01" through "QC-06"
    score: float | None        # 0.0–1.0 or None if not_evaluated
    status: str                # "scored", "not_evaluated", "failed"
    sources: list[str]         # ["automated", "human"] — which sources contributed
    notes: str                 # brief rationale


@dataclass
class NarrativeQualityReport:
    report_id: str
    session_id: str
    run_id: str | None         # S42 run_id if automated; None if human-only
    scenario_seed_id: str
    evaluated_at: datetime
    categories: list[CategoryScore]
    composite_score: float     # weighted mean of evaluated categories
    verdict: str               # "pass", "fail", "inconclusive"
    fail_reasons: list[str]    # human-readable reasons for fail verdict
```

---

## 5. Composite Score and Verdicts

### 5.1 Weights

| Category | Weight |
|----------|--------|
| QC-01 Coherence | 0.25 |
| QC-02 Tension | 0.15 |
| QC-03 Wonder | 0.20 |
| QC-04 Character Depth | 0.20 |
| QC-05 Genre Fidelity | 0.10 |
| QC-06 Consequence Weight | 0.10 |

If a category is `not_evaluated`, its weight is redistributed proportionally
across the remaining evaluated categories.

### 5.2 Verdicts

| Verdict | Condition |
|---------|-----------|
| **pass** | `composite_score >= 0.65` AND no individual category score < 0.40 |
| **fail** | `composite_score < 0.65` OR any individual category score < 0.40 |
| **inconclusive** | Three or more categories are `not_evaluated` |

---

## 6. Acceptance Criteria (Gherkin)

```gherkin
Feature: Narrative Quality Evaluation

  Scenario: AC-44.01 — All 6 categories scored for a complete session
    Given a PlaytestReport (S42) AND a FeedbackRecord (S43)
    When NarrativeQualityEvaluator.evaluate(session_id) is called
    Then the report has 6 CategoryScore entries
    And none have status = "not_evaluated" when both sources are present

  Scenario: AC-44.02 — Wonder is not_evaluated without S43 data
    Given a PlaytestReport without a corresponding S43 FeedbackRecord
    When NarrativeQualityEvaluator.evaluate(session_id) is called
    Then QC-03 has status = "not_evaluated"
    And QC-03 weight is redistributed to remaining categories

  Scenario: AC-44.03 — Character depth fails if AC-2.3 enforcement missed
    Given the first gameplay turn does not contain the character name
    When QC-04 is computed
    Then the automated component contributes 0.0
    And CategoryScore.notes mentions "AC-2.3 enforcement miss"

  Scenario: AC-44.04 — Fail verdict when any category below 0.40
    Given a session where QC-01 coherence = 0.35
    When the composite score is computed
    Then verdict = "fail"
    And fail_reasons contains "QC-01 Coherence below threshold"

  Scenario: AC-44.05 — Inconclusive when 3+ categories not_evaluated
    Given a session with only S42 data (no S43 data)
    And QC-03 Wonder requires S43
    When evaluated
    Then 3 or more categories have status "not_evaluated"
    And verdict = "inconclusive"
```

---

## 7. Out of Scope

- Therapeutic outcome measurement — S18 (future stub).
- Automated A/B scoring of narrative variants (future).
- Cross-session longitudinal quality tracking (future).
- Bias or representation audits of narrative content.

---

## 8. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-44.01 | Scoring normalized 0–1 or categorical? | ✅ Resolved | **0.0–1.0 float** for all categories. Categorical thresholds (pass/fail) applied at verdict stage, not during scoring. This allows fine-grained regression tracking. |
| OQ-44.02 | Inter-rater reliability across LLM runs? | ✅ Resolved | For genre fidelity (QC-05): LLM scorer called with `temperature=0` for consistency; rationale stored for human review. Coherence (QC-01) is rule-based to maximize reproducibility. |
| OQ-44.03 | Weighting LLM vs human signal? | ✅ Resolved | Per-category weights defined in §5.1. Wonder (QC-03) and Character Depth (QC-04) weight human signal more heavily (0.7 and 0.5 respectively). Coherence (QC-01) is fully automated. |

---

## Appendix A — Scoring Rubric

*(Reference table for evaluators and LLM genre scorer prompt.)*

**QC-01 Coherence** — Score guide:
- 1.0: No contradictions; all references accurate; character consistent throughout
- 0.7: Minor inconsistency (e.g., location name varies slightly); no character contradiction
- 0.5: One notable contradiction player would notice
- 0.3: Multiple contradictions; character traits change without narrative reason
- 0.0: Session is incoherent; player unable to follow causal chain

**QC-03 Wonder** — Score guide (S43 q_wonder, 1–5 → 0.0–1.0):
- 5/1.0: "I felt genuinely surprised and delighted at least once."
- 4/0.8: "There was a moment that stood out, even if brief."
- 3/0.6: "The story was fine but nothing surprised me."
- 2/0.4: "It felt mechanical — I never forgot I was playing a game."
- 1/0.2: "I felt nothing. The narrative was empty."

**QC-05 Genre Fidelity** — Prompt fragment for LLM scorer:
```
You are evaluating a text adventure narrative for genre fidelity.
The declared genre is: {primary_genre}
The declared themes are: {themes}
The declared tone is: {tone}

Below are 5 sample narrative fragments from the session.
Score genre fidelity 1–5 where:
5 = All fragments are clearly and consistently in genre
4 = Mostly in genre; minor drift in one fragment
3 = Partially in genre; some elements feel out of place
2 = Genre is inconsistent; player would notice the drift
1 = Genre is absent or contradicted

Respond in JSON: {"score": <int>, "rationale": "<one sentence>"}
```
