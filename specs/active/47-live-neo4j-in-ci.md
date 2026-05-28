# S47 — Live Neo4j in CI

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ⚠️ Partial
> **Level**: 4 — Operations
> **Dependencies**: v1 S13 (World Graph Schema), v1 S16 (Testing Infrastructure)
> **Related**: S46 (Cloud Deployment), S49 (Horizontal Scaling)
> **Last Updated**: 2026-05-28

---

## 1. Purpose

The v1 closeout identified a gap in the test suite: integration tests covering
the Neo4j world graph (S13) rely on mocked drivers, not a live database.
This means schema mistakes, Cypher query bugs, and relationship-model
regressions can pass CI and only surface in staging.

S47 replaces the mocked Neo4j integration tests with **ephemeral live Neo4j
containers** in CI, defines canonical test-data fixtures, and specifies
setup/teardown cost targets.

---

## 2. User Stories

- **As a** developer, **I want** graph integration tests to run against live Neo4j, **so that** Cypher and schema regressions fail in CI instead of staging.
- **As a** reviewer, **I want** canonical graph fixtures, **so that** tests describe expected world-shape data instead of hiding it in mocks.
- **As an** operator, **I want** CI startup to fail quickly when Neo4j is unavailable, **so that** blocked builds are diagnosable.

## 3. Design Decisions

### 3.1 Ephemeral Container per CI Job

Each CI test job that exercises the world graph gets its own Neo4j container.
GitHub Actions `services:` block provides this at no extra configuration cost.
The container is thrown away at job end; no shared state between jobs.

### 3.2 Community Edition, No Auth in CI

Neo4j CE 5.x is the production target (S13). In CI, the container runs with
`NEO4J_AUTH=none` to eliminate credential setup overhead. Production always
requires credentials; CI tests are sandboxed to the Actions runner.

### 3.3 Fixture Strategy: Cypher Seed Files

Test-data fixtures are `.cypher` files committed to `tests/fixtures/neo4j/`.
The test framework applies them via the Neo4j Bolt driver at session setup.
This makes fixtures readable, diffable, and independent of Python ORM state.

---

## 4. Functional Requirements

### FR-47.01 — CI Service Container

The GitHub Actions workflow for integration tests SHALL include a `neo4j`
service container:

```yaml
services:
  neo4j:
    image: neo4j:5-community
    env:
      NEO4J_AUTH: none
    ports:
      - 7687:7687
    options: >-
      --health-cmd "cypher-shell 'RETURN 1' || exit 1"
      --health-interval 10s
      --health-timeout 5s
      --health-retries 10
```

Tests connect to `bolt://localhost:7687` with no credentials.

### FR-47.02 — Test Infrastructure Fixture

A pytest fixture `neo4j_session` (scope `function`) SHALL:
1. Open a Bolt session to the CI Neo4j instance
2. Load the appropriate seed file(s) from `tests/fixtures/neo4j/`
3. Yield the session
4. Execute `MATCH (n) DETACH DELETE n` after each test to reset state

A `neo4j_db` fixture (scope `session`) SHALL verify connectivity at the start
of the test run and skip all Neo4j tests with a clear message if the service
is unreachable (prevents hanging in dev environments without Docker).

### FR-47.03 — Canonical Fixture Files

The following seed files SHALL exist in `tests/fixtures/neo4j/`:

| File | Contents | Used by |
|---|---|---|
| `world_minimal.cypher` | 1 Universe, 1 Location, 1 Actor | Basic graph CRUD tests |
| `world_with_npcs.cypher` | 3 Locations, 2 NPCs, relationship edges | NPC presence tests |
| `world_full.cypher` | Full canonical test world (all node types from S13) | Schema validation, query tests |
| `empty.cypher` | No nodes (empty file / comment only) | Negative-path tests |
| `world_large.cypher` | Larger graph fixture for performance/read-only query tests | Session-scoped read-only tests and query budget checks |

Fixture files are plain Cypher; they MUST be valid against the S13 schema.
A CI step SHALL perform a dry-run import of each fixture file using the
`neo4j-driver` connection (established in FR-47.01) to validate Cypher syntax
and schema conformance before the full test suite runs.

### FR-47.04 — Replaced Mocked Tests

All integration test files in `tests/integration/` that import a mock Neo4j driver (e.g., `AsyncMock`, `MagicMock` for `AsyncDriver`) SHALL be replaced with live-driver equivalents using `neo4j_session`. Mock-based Neo4j integration tests are not permitted after S47 is merged. CI SHALL include a static scan that fails when `AsyncMock` or `MagicMock` is used with `AsyncDriver` in `tests/integration/`; unit tests remain exempt.

Unit tests MAY continue to mock Neo4j for pure query-construction or
transformation logic where no database interaction is tested.

### FR-47.05 — Startup Cost Budget

After the Neo4j image is available on the runner, the service container MUST be health-ready within **120 seconds**. Tests SHALL NOT begin until the health check passes. If the health check does not pass within 120 seconds after image pull/container start, the job fails with service logs.

The complete Neo4j-dependent integration test suite SHOULD run in under
**3 minutes** (excluding container startup). Tests exceeding this budget MUST
be documented with a justification comment.

### FR-47.06 — Local Development Support

Developers running `make test` locally without a running Neo4j instance MUST
see a clear skip message, not a hanging test or cryptic connection error.

The `neo4j_db` session fixture detects the missing service via a 2-second
connection timeout and calls `pytest.skip("Neo4j not available — skipping",
allow_module_level=True)` on all affected tests.

### FR-47.07 — Schema Version Gate

The `world_full.cypher` fixture includes a constraint set that mirrors the
S13-defined uniqueness constraints. The `neo4j_session` fixture verifies
these constraints are present before any test runs. If constraints are
missing or wrong, tests fail with `Neo4jSchemaError`, not silent wrong data.

---

## 5. Non-Functional Requirements

### NFR-47.01 — CI startup budget

**Category**: Performance

**Target**: Neo4j service health is established within 120 seconds after image availability/container start or CI fails with actionable logs.

### NFR-47.02 — Fixture readability

**Category**: Maintainability

**Target**: Canonical graph fixtures are committed as readable Cypher files, not hidden Python object mocks.

### NFR-47.03 — Local developer ergonomics

**Category**: Usability

**Target**: Developers without local Neo4j see a fast skip message rather than a hang or cryptic connection failure.

## 6. User Journeys

### Journey 1: CI validates graph behavior against live Neo4j

- **Trigger**: An integration-test workflow starts.
- **Steps**:
  1. CI starts an ephemeral Neo4j service container.
  2. Test infrastructure verifies connectivity and schema constraints.
  3. Canonical Cypher fixtures are loaded for each test.
  4. Tests run against the live driver and clean the graph after each test.
- **Happy path**: Schema/query regressions fail before merge.
- **Alternative paths**: Startup, fixture, or constraint failures stop the job with a specific cause.

### Journey 2: Developer runs tests without Neo4j

- **Trigger**: A developer runs the test suite locally without a graph service.
- **Steps**:
  1. The Neo4j fixture attempts a short connectivity check.
  2. Neo4j-dependent tests are skipped with a clear message.
  3. Non-Neo4j tests continue normally.
- **Happy path**: Local test runs stay fast and understandable.

## 7. Edge Cases & Failure Modes

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| E1 | Neo4j service container does not become healthy | CI fails within the configured startup budget with service logs. |
| E2 | A fixture contains invalid Cypher | Fixture validation fails before dependent tests run. |
| E3 | Local developer lacks Docker/Neo4j | Neo4j-dependent tests skip quickly with a clear message. |
| E4 | A test leaves graph state behind | Teardown deletes nodes and the next test starts empty; failure is logged if cleanup fails. |
| E5 | Integration test introduces a mocked Neo4j driver | CI/static scan fails the S47 mock-ban check. |
| E6 | Constraint setup differs from S13 | Schema version gate fails before query behavior is trusted. |

## 8. Acceptance Criteria (Gherkin)

```gherkin
Feature: Live Neo4j in CI

  Scenario: AC-47.01 — Neo4j service starts and is ready within 120s
    Given a GitHub Actions integration test job starts
    When the neo4j service container is launched after image availability
    Then the health check passes within 120 seconds
    And tests begin only after health check passes

  Scenario: AC-47.02 — Each test runs against a fresh graph
    Given test A writes nodes to the graph
    When test A ends
    Then MATCH (n) DETACH DELETE n is executed
    And test B starts with an empty database

  Scenario: AC-47.03 — No mock Neo4j drivers in integration tests
    Given the integration test directory is scanned
    When any test file is checked for AsyncMock or MagicMock on AsyncDriver
    Then zero files match (all Neo4j interaction uses the live driver)

  Scenario: AC-47.04 — Neo4j absent in dev does not hang
    Given Neo4j is not running locally
    When make test is run
    Then all Neo4j integration tests are skipped within 5 seconds
    And the skip message includes "Neo4j not available"

  Scenario: AC-47.05 — world_full.cypher validates against S13 schema
    Given world_full.cypher is loaded
    When a dry-run import is performed via neo4j-driver
    Then the file passes syntax validation
    And the uniqueness constraints from S13 are present
```

### Criteria Checklist

- [ ] **AC-47.01**: Neo4j service starts and is ready within 120s.
- [ ] **AC-47.02**: Each test runs against a fresh graph.
- [ ] **AC-47.03**: No mock Neo4j drivers in integration tests.
- [ ] **AC-47.04**: Neo4j absent in dev does not hang.
- [ ] **AC-47.05**: world_full.cypher validates against S13 schema.

---

## 9. Dependencies & Integration Boundaries

| Spec | Relationship | Contract |
|---|---|---|
| S13 | World graph schema | Fixtures and constraints must match the canonical graph model. |
| S16 | Testing infrastructure | CI integration-test workflow owns service-container execution. |
| S46 | Cloud deployment | Live graph CI reduces staging-only graph failures before production deploys. |
| S49 | Horizontal scaling | Multi-instance readiness depends on graph behavior being verified against a live store. |

## 10. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-47.01 | Which Cypher linter to use for fixture validation? | ✅ Resolved | **`neo4j-driver`'s built-in query validation** via `AsyncDriver.verify_connectivity()` plus a dry-run fixture import. No separate linter dependency required in v3. |

## 11. Out of Scope

- Live Neo4j in load/performance tests (those use synthetic data).
- Neo4j cluster testing (CE is single-instance; cluster deferred to v4+).
- Replacing unit-level Neo4j mocks (only integration tests are affected).

---
