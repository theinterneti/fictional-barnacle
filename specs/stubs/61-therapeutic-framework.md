# S61 — Therapeutic Framework

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v5+
> **Implementation Fit**: ❌ Not Started
> **Level**: 1 — Core Game
> **Dependencies**: S60 (Crisis Safety — required gate), S08 (Turn Pipeline), S09 (Prompt Management), S37 (Memory Records)
> **Related**: S62 (Story Sharing), S56 (Resonance Correlation)
> **Last Updated**: 2026-04-21

---

## 1. Purpose

S61 defines TTA's optional therapeutic enrichment layer: evidence-informed
techniques woven into the narrative by the LLM to support emotional wellbeing.

**Critical framing**: TTA is a *game*, not a therapy product. S61 adds
therapeutic-informed narrative techniques (drawn from CBT and Mindfulness)
to deepen emotional resonance and support self-reflection. It does NOT
diagnose, prescribe, or replace professional mental health care.

S61 is gated on S60 (crisis safety must be active). A player may opt out
of therapeutic enrichment at any time.

---

## 2. Techniques in MVP Scope

Two modalities are in scope for v5 MVP:

| Modality | Source | Application in TTA |
|---|---|---|
| **Cognitive Reframing** (CBT-informed) | Cognitive Behavioral Therapy | LLM offers alternative perspectives on a character's interpretations of events; "What if the stranger's silence meant something other than rejection?" |
| **Grounding Anchors** (Mindfulness-informed) | Mindfulness-Based Stress Reduction | LLM occasionally invites the player to notice a sensory detail in the narrative, anchoring attention to the present |

These are woven into narrative naturally by the LLM — not presented as clinical
exercises. A player may not consciously recognize them as techniques.

**Out of scope for MVP**: Exposure therapy patterns, motivational interviewing,
grief work, trauma-informed techniques (all require higher clinical oversight).

---

## 3. Annotation Hook

S61 introduces a `TurnAnnotations` model that the turn pipeline (S08) emits as
part of its output. S08 defines the hook point; S61 supplies the schema and
populates it when a technique is applied:

```python
class TurnAnnotations(BaseModel):
    therapeutic_technique: str | None  # e.g. "cognitive_reframing", "grounding"
    emotional_tone: str | None
    arc_phase: str | None
```

S61 populates `therapeutic_technique` when a technique is applied in a turn.
This annotation is used by S45 (evaluation) to measure technique frequency
and by S62 (story sharing) to contextualize exported stories.

---

## 4. Functional Requirements

### FR-61.01 — Opt-In / Opt-Out

Therapeutic enrichment is opt-in at the player level. A `therapeutic_enrichment`
preference field is added to the player profile (default: false). Players can
toggle this in session settings. When false, the therapeutic technique prompt
hints are omitted from LLM context.

### FR-61.02 — Technique Prompt Injection

When enrichment is enabled, the turn pipeline injects a technique hint into the
LLM context. The hint is a short directive registered in S09 as one of:
- `therapeutic_cognitive_reframing_hint`
- `therapeutic_grounding_anchor_hint`

The technique is selected based on the current narrative arc phase and
emotional tone annotation from the previous turn.

### FR-61.03 — Frequency Cap

A therapeutic technique is applied at most once per 3 turns (to avoid over-
saturation). The frequency cap is enforced by the pipeline, not the LLM.

### FR-61.04 — Clinical Review Requirement

All therapeutic technique prompt templates (FR-61.02) MUST be reviewed and
approved by a licensed mental health professional before v5 deployment.
This is a non-negotiable gate requirement alongside S60.

### FR-61.05 — No Clinical Claims

Player-facing copy (onboarding, settings, marketing) MUST NOT claim that TTA
provides therapy, treats mental health conditions, or replaces professional care.
Copy is reviewed by legal and clinical before publication.

---

## 5. Acceptance Criteria (Gherkin)

```gherkin
Feature: Therapeutic Framework

  Scenario: AC-61.01 — Enrichment disabled skips technique injection
    Given a player with therapeutic_enrichment = false
    When a turn is processed
    Then no therapeutic technique hint is in the LLM context
    And turn_annotation.therapeutic_technique is null

  Scenario: AC-61.02 — Enrichment enabled injects a technique
    Given a player with therapeutic_enrichment = true
    And the narrative arc is in a reflective phase
    When a turn is processed
    Then a therapeutic technique hint is injected into LLM context
    And turn_annotation.therapeutic_technique is set

  Scenario: AC-61.03 — Frequency cap limits techniques to 1 per 3 turns
    Given a player with therapeutic_enrichment = true
    When 3 consecutive turns are processed
    Then at most 1 turn has a therapeutic technique annotation

  Scenario: AC-61.04 — S60 inactive blocks S61 from loading
    Given crisis_safety_enabled = false
    When the application starts
    Then a ConfigurationError is raised
    And S61 module is not initialized
```

---

## 6. Out of Scope

- Diagnosis, clinical assessment, or treatment recommendations.
- Therapeutic modalities beyond CBT-informed and Mindfulness-informed techniques.
- Mandatory therapeutic content (always opt-in).
- Progress tracking or therapeutic outcome measurement.

---

## 7. Open Questions

| ID | Question | Status |
|---|----------|--------|
| OQ-61.01 | Which licensed MHP will review prompt templates? | 🔓 Open — external clinical partnership required. |
| OQ-61.02 | Should the player be informed a technique was used, post-turn? | 🔓 Open — transparency vs. narrative immersion tradeoff; deferred to v5 UX research. |
| OQ-61.03 | Is CBT-informed sufficient, or do we need a clinical advisory board? | 🔓 Open — legal/ethics review required before v5. |
