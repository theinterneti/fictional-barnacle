# S65 — Local CI Gate

> **Status**: ✅ Approved
> **Layer**: Process / Developer Tooling
> **Dependencies**: Makefile targets `check-format`, `lint`, `trace`, `validate-specs`, `validate-plans`, `validate-openapi`, `test-unit`, `test-integration`
> **Last Updated**: 2026-05-26

---

## 1. Purpose

Developers need a local pre-push gate that mirrors the high-signal parts of GitHub CI before a branch is pushed. The goal is to catch formatting, linting, type-checking, AC traceability, spec/plan validation, OpenAPI contract drift, and unit-test failures locally, reducing failed remote runs and keeping PR iteration tight.

## 2. User Stories

- **As a** developer, **I want** one local command for the normal pre-push gate, **so that** I can catch CI-style failures before pushing.
- **As a** developer, **I want** an extended gate that includes integration tests, **so that** I can opt into slower service-backed validation before high-risk pushes.
- **As a** reviewer, **I want** gate commands to appear in `make help`, **so that** contributors can discover the expected workflow without reading CI YAML.

## 3. Functional Requirements

### FR-1: Standard local gate

**Description**: The Makefile exposes `make gate` as the standard local pre-push command.

**Behavior**: `make gate` executes, in order: `check-format`, `lint`, `trace`, `validate-specs`, `validate-plans`, `validate-openapi`, and `test-unit`.

**Constraints**: The target must not auto-format, mutate source files, start service containers, or run integration tests.

### FR-2: Extended local gate

**Description**: The Makefile exposes `make gate-full` for slower, service-backed validation.

**Behavior**: `make gate-full` executes `make gate` and then `test-integration`.

**Constraints**: Integration service orchestration remains delegated to the existing `test-integration` target.

### FR-3: Discoverability

**Description**: Both gate targets are self-documenting.

**Behavior**: `make help` lists `gate` and `gate-full` with clear descriptions.

**Constraints**: The targets must follow the existing `##` Makefile help-comment convention.

## 4. Non-Functional Requirements

### NFR-1: Fail-fast reliability

**Category**: Reliability

**Target**: Any failed prerequisite target causes the invoked gate target to exit non-zero without continuing to later prerequisites.

### NFR-2: Local/CI alignment

**Category**: Developer Experience

**Target**: `make gate` includes the checks most likely to fail GitHub CI for ordinary code/spec/plan/API PRs, while keeping integration tests opt-in via `gate-full`.

## 5. User Journeys

### Journey 1: Normal pre-push validation

- **Trigger**: A developer finishes a code or spec change.
- **Steps**:
  1. Developer runs `make gate`.
  2. Make runs formatting check, lint/type-check, AC traceability, spec validation, plan validation, OpenAPI validation, and unit tests.
  3. If all pass, the developer pushes the branch.
- **Happy path**: Remote CI has fewer avoidable formatting/lint/API/unit failures.
- **Alternative paths**: If a prerequisite fails, Make exits non-zero and the developer fixes that local failure before pushing.

### Journey 2: High-risk pre-push validation

- **Trigger**: A developer changes code that touches persistence, service-backed integration, or runtime boundaries.
- **Steps**:
  1. Developer runs `make gate-full`.
  2. Make runs the standard gate.
  3. Make runs `test-integration`.
- **Happy path**: The branch has both local unit validation and service-backed integration evidence.
- **Alternative paths**: If test services are unavailable, `test-integration` fails through its existing behavior.

## 6. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | `ruff format --check` detects formatting drift | `make gate` exits non-zero before lint/type-check |
| E2 | `pyright` fails inside `lint` | `make gate` exits non-zero before trace/spec/unit stages |
| E3 | Spec index validation emits warnings but exits zero | `make gate` continues, because the validator command succeeded |
| E4 | OpenAPI validation fails | `make gate` exits non-zero before unit tests |
| E5 | Unit tests fail | `make gate` exits non-zero and remote push should be delayed |
| E6 | Integration services are unavailable | `make gate` is unaffected; `make gate-full` fails through `test-integration` |

## 7. Acceptance Criteria (Gherkin)

```gherkin
Feature: Local CI gate

  Scenario: AC-65.01 make gate runs the standard local CI sequence
    Given the Makefile defines existing targets check-format, lint, trace, validate-specs, validate-plans, validate-openapi, and test-unit
    When a developer runs `make gate`
    Then Make invokes check-format before lint
    And Make invokes lint before trace
    And Make invokes trace before validate-specs
    And Make invokes validate-specs before validate-plans
    And Make invokes validate-plans before validate-openapi
    And Make invokes validate-openapi before test-unit

  Scenario: AC-65.02 make gate fails when a prerequisite fails
    Given any prerequisite target in the make gate sequence exits non-zero
    When a developer runs `make gate`
    Then `make gate` exits non-zero
    And later prerequisite targets are not required to run

  Scenario: AC-65.03 make gate-full includes integration tests after gate
    Given the Makefile defines `gate` and `test-integration`
    When a developer runs `make gate-full`
    Then Make runs `gate`
    And Make runs `test-integration` after `gate` succeeds

  Scenario: AC-65.04 gate targets are discoverable
    Given the Makefile uses `##` comments for self-documenting help
    When a developer runs `make help`
    Then the output includes `gate`
    And the output includes `gate-full`
```

### Criteria Checklist

- [x] **AC-65.01**: `make gate` runs the standard local CI sequence.
- [x] **AC-65.02**: `make gate` exits non-zero when any prerequisite fails.
- [x] **AC-65.03**: `make gate-full` includes `test-integration` after `gate`.
- [x] **AC-65.04**: Both targets appear in `make help`.

## 8. Dependencies & Integration Boundaries

| Dependency | Relationship | Contract |
|------------|--------------|----------|
| Makefile `check-format` | Required gate prerequisite | Must perform CI-style formatting check without mutating files |
| Makefile `lint` | Required gate prerequisite | Must run ruff lint and pyright type checking |
| Makefile `trace` | Required gate prerequisite | Must validate AC traceability |
| Makefile `validate-specs` | Required gate prerequisite | Must validate spec index and dependencies |
| Makefile `validate-plans` | Required gate prerequisite | Must validate plan index and references |
| Makefile `validate-openapi` | Required gate prerequisite | Must validate generated OpenAPI contract |
| Makefile `test-unit` | Required gate prerequisite | Must run the non-integration/e2e unit suite |
| Makefile `test-integration` | `gate-full` only | Must own service-backed integration orchestration |

## 9. Open Questions

None blocking.

## 10. Out of Scope

- Replacing GitHub CI — remote CI remains the merge confirmation gate.
- Starting/stopping Docker or Podman services in `make gate` — handled by existing integration targets.
- Auto-formatting or auto-fixing source files — handled by `make format`, not by the pre-push gate.
- Adding new dependencies — this gate composes existing targets only.
