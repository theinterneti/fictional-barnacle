# S[XX] — [Spec Title]

> **Status**: 📝 Draft | 🔍 Review | ✅ Approved | 🔄 Revised
> **Level**: [0-5] — [Level Name]
> **Dependencies**: [List of spec IDs this depends on]
> **Last Updated**: YYYY-MM-DD

---

## How to Read This Spec

This is a **functional specification** — it describes *what* the system does, not *how*
it's built. It is one half of a testable contract:

- **This spec** (the "what") defines behavior, acceptance criteria, and boundaries
- **The technical plan** (the "how") will define architecture, stack, and implementation
- **Tasks** will decompose both into small, reviewable chunks of work

Acceptance criteria use **Gherkin syntax** (Given/When/Then) so they can be directly
executed as automated BDD tests using frameworks like Behave or pytest-bdd.

---

## 1. Purpose

A one-paragraph statement of **what this spec covers and why it matters** to the player
or the system. Focus on the problem being solved, not the solution.

## 2. User Stories

Describe who benefits and what they need. Format:

- **As a** [role], **I want** [capability], **so that** [benefit].

Include stories for all relevant roles (player, author, operator, developer).

## 3. Functional Requirements

### FR-1: [Requirement Name]
**Description**: What the system must do.
**Behavior**: How it behaves from the user's perspective.
**Constraints**: Any limits or boundaries.

### FR-2: [Requirement Name]
...

## 4. Non-Functional Requirements

### NFR-1: [Requirement Name]
**Category**: Performance | Reliability | Scalability | Security | Usability
**Target**: Measurable threshold (e.g., "< 200ms p95 response time")

## 5. User Journeys

### Journey 1: [Name]
Step-by-step walkthrough of a complete user interaction. Include:
- **Trigger**: What starts this journey
- **Steps**: Numbered sequence of actions and system responses
- **Happy path**: Expected successful outcome
- **Alternative paths**: Branches and variations

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | [Description] | [What should happen] |
| E2 | [Description] | [What should happen] |

Include: error conditions, boundary values, concurrent access, missing data,
malformed input, timeout/unavailability, and recovery behavior.

## 7. Acceptance Criteria (Gherkin)

Acceptance criteria are written in **Gherkin format** for direct execution as BDD tests.
Each scenario is a testable contract — if code deviates from these, a test must fail.

```gherkin
Feature: [Spec Title]

  Scenario: [AC-1 name]
    Given [initial context]
    When [action or event]
    Then [expected outcome]

  Scenario: [AC-2 name]
    Given [initial context]
    And [additional context]
    When [action or event]
    Then [expected outcome]
    And [additional assertion]

  Scenario Outline: [AC-3 parameterized]
    Given [context with <variable>]
    When [action with <input>]
    Then [outcome with <expected>]

    Examples:
      | variable | input | expected |
      | value1   | x     | y        |
      | value2   | a     | b        |
```

### Criteria Checklist
- [ ] **AC-1**: [Brief description]
- [ ] **AC-2**: [Brief description]
- ...

These criteria are the **definition of done** for implementation.

## 8. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|------|-------------|----------|
| S[XX] | [How this spec relates] | [What data/events cross the boundary] |

For each dependency, define:
- What this spec **requires** from the dependency (inputs)
- What this spec **provides** to dependents (outputs)
- What **invariants** must hold across the boundary

## 9. Open Questions

Questions that need answers before or during implementation. Each question should
indicate its **impact** (blocking, high, moderate) and **who** can answer it.

1. [Question]? — *Impact: [blocking/high/moderate]* — *Owner: [who]*
2. [Question]? — *Impact: [blocking/high/moderate]* — *Owner: [who]*

## 10. Out of Scope

Explicit list of what this spec does **not** cover, to prevent scope creep.
Each exclusion explains *why* it's excluded and *where* it's handled (if anywhere):

- [Thing excluded] — [Why] — [Handled in S[XX] / deferred / not planned]
- [Thing excluded] — [Why] — [Handled in S[XX] / deferred / not planned]

## Appendix

### A. Glossary
Key terms defined for this spec's domain.

### B. References
Links to research, prior art, or related documents.

### C. Structural Notes

This spec intentionally separates concerns:
- **Sections 1-7**: Functional specification ("what") — behavior-focused, no tech choices
- **Section 8**: Integration boundaries — contracts between specs
- **Sections 9-10**: Scope management — what's unknown, what's excluded

The technical plan ("how") and task breakdown are separate documents generated
during the Plan and Tasks phases of the SDD workflow.
