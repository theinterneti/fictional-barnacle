# S16 — Testing Infrastructure

> **Status**: 📝 Draft
> **Level**: 4 — Operations
> **Dependencies**: S00 (Testing Charter), S01 (Gameplay Loop), S14 (Deployment), S15 (Observability)
> **Last Updated**: 2026-04-07

## Overview

This spec defines the infrastructure, tooling, and automation that supports testing in TTA. It does NOT define testing philosophy, coverage targets, or test writing patterns — those live in S00 (Testing Charter). This spec answers: **what do tests run on, how are they triggered, and how do we handle the hard parts (LLM mocking, flaky tests, test data)?**

### Out of Scope

- **Test writing philosophy and coverage targets** — defined in S00 (Testing Charter), not here
- **Visual / screenshot regression testing** — no frontend UI in v1 backend — future frontend spec
- **Performance benchmarking harness** — load testing is documented as future (§7) — revisit at scale
- **Contract testing (Pact)** — single-service architecture in v1 makes contract tests unnecessary — future if microservices
- **Security / penetration test automation** — manual review for v1 — S17 (Data Privacy) covers policy
- **pytest-bdd for Gherkin execution** — Gherkin in specs is for human-readable ACs, not automated BDD test runner — may adopt later

> **Note**: Overridden by system.md §1.3 — pytest-bdd is included for v1 to enable executable Gherkin acceptance tests.

---

## 1. CI Pipeline

### 1.1 User Stories

- **US-16.1**: As a developer, every PR I open automatically runs the full quality gate and reports results within 10 minutes.
- **US-16.2**: As a maintainer, I can see which specific check failed on a PR without reading the full log.
- **US-16.3**: As a developer, I can run the same checks locally that CI runs, producing the same results.

### 1.2 Functional Requirements

#### PR Checks (on every push to a PR branch)

**FR-16.1**: The CI pipeline SHALL run the following jobs. Each job is independent and runs in parallel where possible:

| Job | Command | Gate |
|-----|---------|------|
| **Lint** | `uv run ruff check src/` | Zero errors |
| **Format** | `uv run ruff format --check src/` | Zero unformatted files |
| **Type check** | `uv run pyright src/` | Zero errors |
| **Unit tests** | `uv run pytest -m "not integration and not e2e" --cov` | All pass, coverage ≥ threshold |
| **Integration tests** | `uv run pytest -m integration` | All pass |
| **Build** | `docker build .` | Successful build |

**FR-16.2**: Static analysis jobs (lint, format, type check) SHALL run in parallel as a single "quality" job group. Tests SHALL run after quality passes. Build SHALL run after tests pass.

**FR-16.3**: If any job fails, the PR SHALL be marked as failing. The specific failed job SHALL be clearly identified in the GitHub checks UI.

#### Merge to Main

**FR-16.4**: On merge to `main`, CI SHALL additionally run:
- Full test suite including E2E tests (if any exist).
- Docker image build with version labels.
- Push image to GitHub Container Registry (ghcr.io).

#### Nightly (Optional)

**FR-16.5**: A nightly CI job MAY run extended tests:
- Full integration suite against real LLM APIs (with cost budget).
- Golden test comparison (see Section 5).
- Dependency vulnerability scan (`uv audit` or equivalent).

### 1.3 Edge Cases

- **EC-16.1**: If the CI runner runs out of disk space during Docker build, the job SHALL fail with a clear error (not a mysterious build failure).
- **EC-16.2**: If a new dependency is added to `pyproject.toml` but `uv.lock` is not updated, CI SHALL fail at the install step with a clear "lockfile out of date" error.

### 1.4 Acceptance Criteria

- [ ] A PR with a ruff error shows a failing "lint" check, not a failing "tests" check.
- [ ] A PR with all checks green merges without manual quality verification.
- [ ] CI completes in under 10 minutes for typical PRs.
- [ ] `make lint && make test` locally produces the same pass/fail result as CI.

---

## 2. Test Environments

### 2.1 User Stories

- **US-16.4**: As a developer, integration tests in CI run against real Neo4j and Redis instances, not just mocks.
- **US-16.5**: As a developer, I can run integration tests locally against Docker-hosted databases.

### 2.2 Functional Requirements

**FR-16.6**: CI integration tests SHALL use service containers (GitHub Actions services or equivalent):

| Service | Image | Purpose |
|---------|-------|---------|
| Neo4j | `neo4j:5-community` | Graph database for world state tests |
| Redis | `redis:7-alpine` | Session cache and pub/sub tests |
| PostgreSQL | `postgres:16-alpine` | Account and audit log tests |

**FR-16.7**: Service containers SHALL be started with test-specific configuration:
- Neo4j: no authentication (`NEO4J_AUTH=none`), community edition.
- Redis: no authentication, no persistence.
- PostgreSQL: test database, test user, no persistence.

**FR-16.8**: Test fixtures SHALL handle database setup and teardown:
- Before each test module: create required schema/constraints.
- After each test module: clean up test data.
- Tests SHALL NOT depend on data created by other tests.

**FR-16.9**: For local development, `docker compose -f docker-compose.test.yml up` SHALL start test infrastructure matching CI service containers.

### 2.3 Edge Cases

- **EC-16.3**: If a CI service container fails to start (e.g., Neo4j OOM), integration tests SHALL be skipped with a clear "infrastructure failure" annotation, not marked as test failures.
- **EC-16.4**: If tests leave dirty data in databases, subsequent test runs SHALL NOT be affected (each test module handles its own setup/teardown).

### 2.4 Acceptance Criteria

- [ ] Integration tests pass in CI with service containers.
- [ ] Integration tests pass locally against `docker-compose.test.yml` infrastructure.
- [ ] Tests do not depend on execution order.
- [ ] Test database state is clean at the start of each test module.

---

## 3. LLM Mock Strategy

### 3.1 User Stories

- **US-16.6**: As a developer, unit tests that involve LLM calls complete in milliseconds, not seconds.
- **US-16.7**: As a developer, I can write a test that verifies the prompt sent to the LLM without making a real API call.
- **US-16.8**: As a developer, I can test how the system handles LLM failures (timeouts, rate limits, malformed responses).

### 3.2 Functional Requirements

**FR-16.10**: All LLM interactions SHALL go through a client abstraction (e.g., `LLMClient` protocol/interface). This enables mock injection at the dependency level.

**FR-16.11**: The project SHALL provide a `MockLLMClient` that:
- Returns configured responses for given prompt patterns.
- Records all calls (prompt, model, parameters) for assertion.
- Supports simulating errors (timeout, rate limit, malformed response).
- Is deterministic — same input always produces same output.

**FR-16.12**: Mock configuration SHALL support:

```python
mock_llm = MockLLMClient()

# Fixed response for any input
mock_llm.set_default_response("A brave adventurer stands at the crossroads.")

# Pattern-matched responses
mock_llm.when_prompt_contains("forest").respond("The forest is dark and quiet.")
mock_llm.when_prompt_contains("combat").respond("The enemy strikes!")

# Error simulation
mock_llm.when_prompt_contains("timeout").raise_error(TimeoutError())
mock_llm.when_call_number(5).raise_error(RateLimitError())
```

**FR-16.13**: Tests SHALL NOT make real LLM API calls unless explicitly marked with `@pytest.mark.llm_live`. Live LLM tests:
- Are skipped in CI by default.
- Run in nightly builds with a cost budget.
- Require `TTA_LLM_API_KEY` to be set.

**FR-16.14**: The mock client SHALL track token counts using a simple approximation (word count × 1.3) so that cost-related tests can function without real tokenization.

### 3.3 Edge Cases

- **EC-16.5**: If a test needs a specific token count (e.g., testing context window limits), the mock SHALL support explicit token count override: `mock_llm.set_response("text", token_count=4096)`.
- **EC-16.6**: If a test needs streaming behavior, the mock SHALL support async iteration that yields chunks with configurable delay.

### 3.4 Acceptance Criteria

- [ ] Unit tests involving LLM calls complete in under 100ms each.
- [ ] `MockLLMClient` records all prompts for assertion.
- [ ] Error simulation (timeout, rate limit) is testable.
- [ ] No test outside of `@pytest.mark.llm_live` makes a real API call.

---

## 4. Test Fixtures & Data

### 4.1 User Stories

- **US-16.9**: As a developer, I can write a test with a fully populated world graph without manually constructing 50 nodes.
- **US-16.10**: As a developer, test fixtures are reusable across test modules.

### 4.2 Functional Requirements

**FR-16.15**: The project SHALL provide pytest fixtures for common test data:

| Fixture | Provides | Scope |
|---------|----------|-------|
| `player_data` | A valid player profile dict | Function |
| `session_data` | A valid session with history | Function |
| `world_graph` | A small but complete world graph (5-10 nodes) | Module |
| `turn_context` | A complete turn processing context | Function |
| `mock_llm` | Pre-configured `MockLLMClient` | Function |

**FR-16.16**: Fixtures SHALL be defined in `tests/conftest.py` (shared) or `tests/<category>/conftest.py` (category-specific). No test file SHALL define fixtures that other test files depend on.

**FR-16.17**: The project SHALL include a `tests/fixtures/` directory containing:
- `worlds/` — JSON or Cypher files defining test world graphs.
- `sessions/` — JSON files defining test session histories.
- `prompts/` — Example prompts and expected responses for golden tests.

**FR-16.18**: Test data factories SHALL be preferred over static fixtures for data that varies between tests:

```python
# Factory pattern
def make_player(**overrides) -> dict:
    defaults = {
        "id": f"player_{uuid4().hex[:8]}",
        "name": "Test Player",
        "created_at": datetime.utcnow(),
    }
    return {**defaults, **overrides}

# Usage in test
def test_player_with_custom_name():
    player = make_player(name="Alice")
    assert player["name"] == "Alice"
```

### 4.3 Acceptance Criteria

- [ ] Every test file uses fixtures from `conftest.py` or factories, not inline data construction.
- [ ] `tests/fixtures/` contains at least one world graph and one session history.
- [ ] Fixtures are documented with docstrings explaining what they provide.

---

## 5. Golden Tests (Narrative Snapshots)

### 5.1 User Stories

- **US-16.11**: As a developer, I can detect unintended changes to narrative output by comparing against approved snapshots.
- **US-16.12**: As a developer, I can update golden snapshots when intentional prompt changes alter output.

### 5.2 Functional Requirements

**FR-16.19**: Golden tests SHALL compare generated narrative output against approved snapshot files. The comparison is NOT exact string matching — it uses a similarity threshold.

**FR-16.20**: Golden test workflow:
1. A test sends a fixed input through the turn pipeline (with `MockLLMClient`).
2. The output is compared against a snapshot in `tests/fixtures/golden/`.
3. If the similarity score is below 0.9 (configurable), the test fails.
4. To update a snapshot: run `pytest --update-golden` which overwrites snapshot files.

**FR-16.21**: Similarity comparison SHALL use a simple metric:
- For mocked LLM tests: exact match (mock output is deterministic).
- For live LLM tests (nightly): structural similarity — same JSON schema, same narrative elements, similar length (±20%).

**FR-16.22**: Golden test files SHALL be stored in version control. Changes to golden files SHALL be reviewed in PRs like any other code change.

**FR-16.23**: Golden tests SHALL be marked with `@pytest.mark.golden` and can be run independently: `uv run pytest -m golden`.

### 5.3 Acceptance Criteria

- [ ] Changing a prompt template causes golden tests to fail.
- [ ] `pytest --update-golden` regenerates snapshot files.
- [ ] Golden test files are tracked in git.
- [ ] Golden tests pass when no prompt changes have been made.

---

## 6. Coverage Reporting

### 6.1 User Stories

- **US-16.13**: As a developer, I can see which lines of code are not covered by tests.
- **US-16.14**: As a maintainer, I can see coverage trends over time.

### 6.2 Functional Requirements

**FR-16.24**: Coverage SHALL be measured by `pytest-cov` using `coverage.py` under the hood.

**FR-16.25**: Coverage configuration:

```ini
[tool.coverage.run]
source = ["src"]
omit = ["src/**/migrations/*", "src/**/test_*"]
branch = true

[tool.coverage.report]
fail_under = 70
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.",
]
```

**FR-16.26**: CI SHALL produce:
- A coverage summary in the job output (percentage per module).
- An HTML coverage report as a CI artifact (downloadable).
- A coverage badge or comment on the PR (via Codecov, Coveralls, or built-in GitHub Actions).

**FR-16.27**: Coverage thresholds SHALL be enforced per component category (as defined in S00):
- Game-critical (turn pipeline, safety): ≥80%
- Platform (API, session management): ≥70%
- Infrastructure (database, config): ≥60%

**FR-16.28**: Coverage SHALL measure branch coverage, not just line coverage. An `if/else` with only the `if` branch tested shows as partially covered.

### 6.3 Acceptance Criteria

- [ ] CI reports coverage percentage and fails if below threshold.
- [ ] HTML coverage report is downloadable as a CI artifact.
- [ ] Coverage measures branches, not just lines.
- [ ] `pragma: no cover` is used sparingly and with justification.

---

## 7. Load Testing (Future)

### 7.1 Discussion

Load testing is out of scope for v1, but the approach is documented here so it can be implemented when needed.

### 7.2 Functional Requirements (FUTURE)

**FR-16.29 (FUTURE)**: Load testing SHALL use `locust` (Python-native, OSS) to simulate concurrent player sessions.

**FR-16.30 (FUTURE)**: Load test scenarios:

| Scenario | Description | Target |
|----------|-------------|--------|
| Steady state | 10 concurrent sessions, 1 turn/minute each | p95 < 5 seconds |
| Burst | 50 concurrent turns within 10 seconds | No 500 errors |
| Long session | Single session, 100 turns over 30 minutes | No memory leaks |

**FR-16.31 (FUTURE)**: Load tests SHALL use `MockLLMClient` to isolate application performance from LLM API performance. A separate LLM-inclusive load test MAY run against staging with real APIs.

**FR-16.32 (FUTURE)**: Load test results SHALL be stored as CI artifacts for trend comparison.

### 7.3 Acceptance Criteria (Future)

- [ ] A locustfile exists in `tests/load/` that defines the scenarios above.
- [ ] Load tests can run against local Docker Compose stack.
- [ ] Load test results include p50, p95, p99 latency and error rate.

---

## 8. Flaky Test Handling

### 8.1 User Stories

- **US-16.15**: As a developer, a flaky test does not block my PR from merging.
- **US-16.16**: As a maintainer, I can see which tests are flaky and prioritize fixing them.

### 8.2 Functional Requirements

**FR-16.33**: Tests SHALL be categorized by determinism:

| Category | Determinism | Example | Strategy |
|----------|-------------|---------|----------|
| Pure unit | 100% deterministic | Math, parsing, validation | Standard test |
| Mocked integration | 99%+ deterministic | LLM mock, DB mock | Standard test |
| Real integration | ~95% deterministic | Neo4j queries, Redis ops | Retry once on failure |
| Timing-sensitive | Variable | Timeout tests, async race conditions | Generous timeouts, retry |
| Live LLM | Non-deterministic | Real API calls | Run nightly, statistical pass/fail |

**FR-16.34**: Flaky tests SHALL be handled with a retry plugin (`pytest-rerunfailures`):
- Tests marked `@pytest.mark.flaky(reruns=2)` are retried up to 2 times.
- The test is considered passing if it passes on any attempt.
- Retries are logged for tracking.

**FR-16.35**: The project SHALL NOT abuse the flaky marker. A test is marked flaky as a temporary measure while the root cause is investigated. A test that has been flaky for more than 30 days SHALL be either fixed or deleted.

**FR-16.36**: CI SHALL report flaky test metrics:
- How many tests were retried in this run.
- Which tests were retried.
- This data SHALL be visible in CI logs (not buried).

**FR-16.37**: Tests involving real time (sleep, timeout) SHALL use `freezegun` or equivalent to control time. Tests SHALL NOT `time.sleep()` to wait for async operations — they SHALL use proper async waiting mechanisms (event, semaphore, polling with short intervals).

### 8.3 Edge Cases

- **EC-16.7**: If a test fails on retry too (fails all attempts), it is a real failure, not flaky.
- **EC-16.8**: If CI infrastructure causes a failure (Docker daemon crash, OOM), the entire job should be retried, not individual tests.

### 8.4 Acceptance Criteria

- [ ] A test marked `@pytest.mark.flaky(reruns=2)` that fails once but passes on retry shows as passing.
- [ ] CI logs show how many tests were retried.
- [ ] No test uses `time.sleep()` for synchronization.

---

## 9. Mutation Testing

### 9.1 Discussion

Mutation testing measures test quality by introducing small code changes (mutations) and checking if tests catch them. It answers: "if I introduce a bug, will my tests find it?"

### 9.2 Recommendation

**FR-16.38**: Mutation testing is NOT required for v1. Here's why:

| Consideration | Assessment |
|---------------|------------|
| Value | High — catches weak tests that have high coverage but low effectiveness |
| Cost | High — mutation runs are 10-100x slower than normal test runs |
| Maturity | TTA v1 has higher priorities (get tests written, then optimize them) |
| Tooling | `mutmut` or `cosmic-ray` for Python — mature but slow |

**FR-16.39**: When the test suite is stable and coverage exceeds 80% across game-critical code, mutation testing SHOULD be introduced:
- Start with the safety module (highest criticality).
- Run mutations nightly, not on every PR.
- Target a mutation score ≥ 75% for critical modules.

**FR-16.40**: If mutation testing is introduced, the configuration SHALL be stored in `pyproject.toml` and the mutation report SHALL be a CI artifact.

### 9.3 Acceptance Criteria

- [ ] A decision document exists explaining when mutation testing will be adopted.
- [ ] If adopted: mutation testing runs nightly and produces a report.
- [ ] If adopted: mutation score ≥ 75% for safety-critical modules.

---

## 10. Test Organization & Conventions

### 10.1 Functional Requirements

**FR-16.41**: Test directory structure SHALL mirror the source directory:

```
src/
├── turn_pipeline/
│   ├── ipa.py
│   └── nga.py
└── session/
    └── manager.py

tests/
├── unit/
│   ├── turn_pipeline/
│   │   ├── test_ipa.py
│   │   └── test_nga.py
│   └── session/
│       └── test_manager.py
├── integration/
│   ├── test_neo4j_world.py
│   └── test_redis_session.py
├── e2e/
│   └── test_full_turn.py
├── fixtures/
│   ├── worlds/
│   ├── sessions/
│   └── golden/
└── conftest.py
```

**FR-16.42**: Test files SHALL be named `test_<module>.py`. Test functions SHALL be named `test_<behavior_under_test>`.

**FR-16.43**: Test markers SHALL be registered in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: requires external services (Neo4j, Redis, PostgreSQL)",
    "e2e: end-to-end tests",
    "golden: golden/snapshot tests",
    "flaky: known flaky test (with reruns)",
    "llm_live: requires real LLM API key",
    "slow: takes more than 5 seconds",
]
```

**FR-16.44**: `conftest.py` SHALL auto-detect the test environment and configure accordingly:
- If `TTA_ENV=testing` or service containers are available: use real databases.
- Otherwise: skip integration tests with a clear message.

### 10.2 Acceptance Criteria

- [ ] Every test file has a corresponding source file.
- [ ] All custom markers are registered (no `PytestUnknownMarkWarning`).
- [ ] Running `uv run pytest -m "not integration"` skips all integration tests.
- [ ] Test directory structure mirrors source directory structure.

---

## Key Scenarios (Gherkin)

```gherkin
Scenario: CI blocks PR on lint failure
  Given a developer pushes a commit with a ruff lint error
  When the CI pipeline runs
  Then the "lint" job fails
  And the "unit tests" job does not execute
  And the PR status shows a failing "lint" check

Scenario: MockLLMClient returns deterministic responses
  Given a test configures MockLLMClient with a pattern "forest" → "The forest is dark."
  When the turn pipeline processes input containing "forest"
  Then the mock returns "The forest is dark." without making a real API call
  And the mock records the full prompt for assertion
  And the test completes in under 100ms

Scenario: Flaky test passes on retry
  Given a test is marked with @pytest.mark.flaky(reruns=2)
  And the test fails on the first attempt due to a transient timing issue
  When pytest retries the test
  Then the test passes on the second attempt
  And the overall test result is "passed"
  And the CI log shows "1 rerun" for that test

Scenario: Golden test detects prompt change
  Given golden snapshot files exist in tests/fixtures/golden/
  And a developer modifies a prompt template
  When the golden test suite runs with MockLLMClient
  Then at least one golden test fails with a similarity mismatch
  And running "pytest --update-golden" regenerates the snapshot files
  And re-running the golden tests passes with updated snapshots
```

---

## Appendix A: CI Pipeline Diagram

```
PR Push
  │
  ├── [parallel] Quality Gate
  │   ├── ruff check
  │   ├── ruff format --check
  │   └── pyright
  │
  ├── [after quality] Unit Tests + Coverage
  │
  ├── [after quality] Integration Tests (with service containers)
  │
  └── [after tests] Docker Build
       │
       └── All green → PR mergeable

Merge to Main
  │
  ├── Full test suite (unit + integration + e2e)
  ├── Docker build + tag
  └── Push to ghcr.io
```

## Appendix B: pytest.ini / pyproject.toml Test Config

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = [
    "-ra",
    "--strict-markers",
    "--tb=short",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html:artifacts/coverage",
]
filterwarnings = [
    "error",
    "ignore::DeprecationWarning:langfuse.*",
]
```
