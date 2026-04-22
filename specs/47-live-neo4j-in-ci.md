# S47 — Live Neo4j in CI

> **Status**: 📝 Draft
> **Release Baseline**: 🆕 v3
> **Implementation Fit**: ❌ Not Started
> **Level**: 4 — Operations
> **Dependencies**: v1 S13 (World Graph Schema), v1 S16 (Testing Infrastructure)
> **Related**: S46 (Cloud Deployment), S49 (Horizontal Scaling)
> **Last Updated**: 2026-04-21

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

## 2. Design Decisions

### 2.1 Ephemeral Container per CI Job

Each CI test job that exercises the world graph gets its own Neo4j container.
GitHub Actions `services:` block provides this at no extra configuration cost.
The container is thrown away at job end; no shared state between jobs.

### 2.2 Community Edition, No Auth in CI

Neo4j CE 5.x is the production target (S13). In CI, the container runs with
`NEO4J_AUTH=none` to eliminate credential setup overhead. Production always
requires credentials; CI tests are sandboxed to the Actions runner.

### 2.3 Fixture Strategy: Cypher Seed Files

Test-data fixtures are `.cypher` files committed to `tests/fixtures/neo4j/`.
The test framework applies them via the Neo4j Bolt driver at session setup.
This makes fixtures readable, diffable, and independent of Python ORM state.

---

## 3. Functional Requirements

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

Fixture files are plain Cypher; they MUST be valid against the S13 schema.
A CI step SHALL perform a dry-run import of each fixture file using the
`neo4j-driver` connection (established in FR-47.01) to validate Cypher syntax
and schema conformance before the full test suite runs.

### FR-47.04 — Replaced Mocked Tests

All integration test files in `tests/integration/` that import a mock Neo4j
driver (e.g., `AsyncMock`, `MagicMock` for `AsyncDriver`) SHALL be replaced
with live-driver equivalents using `neo4j_session`. Mock-based Neo4j tests
are not permitted after S47 is merged.

Unit tests MAY continue to mock Neo4j for pure query-construction or
transformation logic where no database interaction is tested.

### FR-47.05 — Startup Cost Budget

The Neo4j service container MUST be health-ready within **60 seconds** of
GitHub Actions job start. Tests SHALL NOT begin until the health check passes.
If the health check does not pass within 60 seconds, the job fails.

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

## 4. Acceptance Criteria (Gherkin)

```gherkin
Feature: Live Neo4j in CI

  Scenario: AC-47.01 — Neo4j service starts and is ready within 60s
    Given a GitHub Actions integration test job starts
    When the neo4j service container is launched
    Then the health check passes within 60 seconds
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

---

## 5. Out of Scope

- Live Neo4j in load/performance tests (those use synthetic data).
- Neo4j cluster testing (CE is single-instance; cluster deferred to v4+).
- Replacing unit-level Neo4j mocks (only integration tests are affected).

---

## 6. Open Questions

| ID | Question | Status | Resolution |
|---|----------|--------|------------|
| OQ-47.01 | Which Cypher linter to use for fixture validation? | ✅ Resolved | **`neo4j-driver`'s built-in query validation** via `AsyncDriver.verify_connectivity()` plus a dry-run fixture import. No separate linter dependency required in v3. |
