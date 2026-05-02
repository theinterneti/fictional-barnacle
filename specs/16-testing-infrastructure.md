# S16 — Testing Infrastructure

> **Status**: ✅ Approved
> **Release Baseline**: 🔒 v1 Closed
> **Implementation Fit**: ⚠️ Partial
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
- **pytest-bdd for Gherkin execution** — Gherkin in specs is for human-readable ACs, not automated BDD test runner. pytest-bdd 8.x does not support async step functions (issue #223, open since 2017), making it a poor fit for a heavily-async FastAPI app. May adopt later for HTTP-level acceptance tests via sync TestClient.

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

## 3. Anti-Mock Realism Gate

### 3.1 Problem Statement

The most common cause of "tests pass but things don't work" is **over-mocking**: unit tests verify that mocks behave correctly, but never verify that real services interact correctly. High coverage with aggressive mocking produces false confidence.

### 3.2 User Stories

- **US-16.A1**: As a developer, if I break a Neo4j query, an integration test fails — not just a unit test against a mock.
- **US-16.A2**: As a developer, integration tests clearly SKIP when services are unavailable, never silently degrade to mocks.
- **US-16.A3**: As a maintainer, I can identify which tests hit real services vs mocks at a glance.

### 3.3 Functional Requirements

**FR-16.A1**: Tests SHALL be classified into exactly one realism tier:

| Tier | Mock Policy | When to Use |
|------|-------------|-------------|
| **Unit** | Full mocking allowed | Business logic, data transforms, validation |
| **Integration** | Real services required | Database queries, cache ops, API calls |
| **E2E** | Real services required | Full turn pipeline |

**FR-16.A2**: Integration tests SHALL **fail or skip** when a required service is unavailable. They SHALL NOT silently fall back to a mock. The mechanism:

```python
@pytest.fixture(scope="session")
def neo4j_driver():
    """Real Neo4j driver — skips if unavailable."""
    try:
        driver = AsyncGraphDatabase.driver("bolt://localhost:7687")
        # Verify connectivity
        driver.verify_connectivity()
        yield driver
        driver.close()
    except Exception:
        pytest.skip("Neo4j not available — run `make test-up` first")
```

**FR-16.A3**: The `conftest.py` SHALL NOT contain "automatic mock fallback" fixtures that silently substitute mocks for real services. If a fixture cannot connect, it MUST call `pytest.skip()`.

**FR-16.A4**: Every module that interacts with an external service (Neo4j, Redis, PostgreSQL, LLM API) SHALL have at least one integration test that hits the real service. These are the **realism gates**.

**FR-16.A5**: CI SHALL run integration tests with real service containers (GitHub Actions services). The integration test suite is a **merge gate** — PRs cannot merge if integration tests fail.

**FR-16.A6**: Unit tests MAY mock external services, but SHALL clearly document what is mocked and why. The `MockLLMClient` (§4) is the only approved mock for LLM calls.

### 3.4 Acceptance Criteria

- [ ] No fixture in `conftest.py` silently falls back to a mock when a real service is unavailable.
- [ ] Running `uv run pytest -m integration` without Docker services results in tests being **skipped**, not **passed**.
- [ ] Every service-touching module has at least one integration test.
- [ ] CI runs integration tests against real containers and blocks merge on failure.

---

## 4. LLM Mock Strategy

### 4.1 User Stories

- **US-16.6**: As a developer, unit tests that involve LLM calls complete in milliseconds, not seconds.
- **US-16.7**: As a developer, I can write a test that verifies the prompt sent to the LLM without making a real API call.
- **US-16.8**: As a developer, I can test how the system handles LLM failures (timeouts, rate limits, malformed responses).

### 4.2 Functional Requirements

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

### 4.3 Edge Cases

- **EC-16.5**: If a test needs a specific token count (e.g., testing context window limits), the mock SHALL support explicit token count override: `mock_llm.set_response("text", token_count=4096)`.
- **EC-16.6**: If a test needs streaming behavior, the mock SHALL support async iteration that yields chunks with configurable delay.

### 4.4 Acceptance Criteria

- [ ] Unit tests involving LLM calls complete in under 100ms each.
- [ ] `MockLLMClient` records all prompts for assertion.
- [ ] Error simulation (timeout, rate limit) is testable.
- [ ] No test outside of `@pytest.mark.llm_live` makes a real API call.

---

## 5. Test Fixtures & Data

### 5.1 User Stories

- **US-16.9**: As a developer, I can write a test with a fully populated world graph without manually constructing 50 nodes.
- **US-16.10**: As a developer, test fixtures are reusable across test modules.

### 5.2 Functional Requirements

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

### 5.3 Acceptance Criteria

- [ ] Every test file uses fixtures from `conftest.py` or factories, not inline data construction.
- [ ] `tests/fixtures/` contains at least one world graph and one session history.
- [ ] Fixtures are documented with docstrings explaining what they provide.

---

## 6. Golden Tests (Narrative Snapshots)

### 6.1 User Stories

- **US-16.11**: As a developer, I can detect unintended changes to narrative output by comparing against approved snapshots.
- **US-16.12**: As a developer, I can update golden snapshots when intentional prompt changes alter output.

### 6.2 Functional Requirements

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

### 6.3 Acceptance Criteria

- [ ] Changing a prompt template causes golden tests to fail.
- [ ] `pytest --update-golden` regenerates snapshot files.
- [ ] Golden test files are tracked in git.
- [ ] Golden tests pass when no prompt changes have been made.

---

## 7. Coverage Reporting

### 7.1 User Stories

- **US-16.13**: As a developer, I can see which lines of code are not covered by tests.
- **US-16.14**: As a maintainer, I can see coverage trends over time.

### 7.2 Functional Requirements

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

### 7.3 Acceptance Criteria

- [ ] CI reports coverage percentage and fails if below threshold.
- [ ] HTML coverage report is downloadable as a CI artifact.
- [ ] Coverage measures branches, not just lines.
- [ ] `pragma: no cover` is used sparingly and with justification.

---

## 8. Load Testing (Future)

### 8.1 Discussion

Load testing is out of scope for v1, but the approach is documented here so it can be implemented when needed.

### 8.2 Functional Requirements (FUTURE)

**FR-16.29 (FUTURE)**: Load testing SHALL use `locust` (Python-native, OSS) to simulate concurrent player sessions.

**FR-16.30 (FUTURE)**: Load test scenarios:

| Scenario | Description | Target |
|----------|-------------|--------|
| Steady state | 10 concurrent sessions, 1 turn/minute each | p95 < 5 seconds |
| Burst | 50 concurrent turns within 10 seconds | No 500 errors |
| Long session | Single session, 100 turns over 30 minutes | No memory leaks |

**FR-16.31 (FUTURE)**: Load tests SHALL use `MockLLMClient` to isolate application performance from LLM API performance. A separate LLM-inclusive load test MAY run against staging with real APIs.

**FR-16.32 (FUTURE)**: Load test results SHALL be stored as CI artifacts for trend comparison.

### 8.3 Acceptance Criteria (Future)

- [ ] A locustfile exists in `tests/load/` that defines the scenarios above.
- [ ] Load tests can run against local Docker Compose stack.
- [ ] Load test results include p50, p95, p99 latency and error rate.

---

## 9. Flaky Test Handling

### 9.1 User Stories

- **US-16.15**: As a developer, a flaky test does not block my PR from merging.
- **US-16.16**: As a maintainer, I can see which tests are flaky and prioritize fixing them.

### 9.2 Functional Requirements

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

### 9.3 Edge Cases

- **EC-16.7**: If a test fails on retry too (fails all attempts), it is a real failure, not flaky.
- **EC-16.8**: If CI infrastructure causes a failure (Docker daemon crash, OOM), the entire job should be retried, not individual tests.

### 9.4 Acceptance Criteria

- [ ] A test marked `@pytest.mark.flaky(reruns=2)` that fails once but passes on retry shows as passing.
- [ ] CI logs show how many tests were retried.
- [ ] No test uses `time.sleep()` for synchronization.

---

## 10. Property-Based Testing (Hypothesis)

### 10.1 Discussion

Property-based testing auto-generates thousands of inputs to verify that code invariants hold. Instead of writing specific test cases, you define properties ("for any valid player name, creating a player never raises") and the framework finds counterexamples. This catches edge cases that manual test data misses.

### 10.2 User Stories

- **US-16.P1**: As a developer, data model validation is tested against thousands of generated inputs, not just 3-4 handwritten examples.
- **US-16.P2**: As a developer, when Hypothesis finds a failing input, it shrinks it to the minimal reproduction case.

### 10.3 Functional Requirements

**FR-16.P1**: The project SHALL include `hypothesis` as a dev dependency for property-based testing.

**FR-16.P2**: Hypothesis SHALL be used for testing:
- Pydantic model validation (valid and invalid inputs).
- Data transformation functions (serialization roundtrips).
- API input validation (request schema edge cases).
- Pure functions with clearly defined invariants.

**FR-16.P3**: Hypothesis SHALL NOT be used for:
- Async function testing (Hypothesis is synchronous only — wrap async calls in `asyncio.run()` if needed).
- Tests requiring real external services (use integration tests instead).
- Tests where execution order matters (Hypothesis randomizes inputs).

**FR-16.P4**: Hypothesis profiles SHALL be configured in `conftest.py`:

```python
from hypothesis import settings, Phase

# Fast local development
settings.register_profile("dev", max_examples=10)

# Default
settings.register_profile("default", max_examples=100)

# Thorough CI runs
settings.register_profile("ci", max_examples=500, deriving=settings.get_profile("default"))

# Load profile from environment
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))
```

**FR-16.P5**: Tests using Hypothesis SHALL be marked with `@pytest.mark.hypothesis` and can be run independently: `uv run pytest -m hypothesis`.

**FR-16.P6**: Example usage pattern:

```python
from hypothesis import given
from hypothesis import strategies as st
from src.models import PlayerCreate

@given(
    name=st.text(min_size=1, max_size=100),
    handle=st.from_regex(r"[a-z][a-z0-9_]{2,19}", fullmatch=True),
)
def test_player_create_accepts_valid_input(name: str, handle: str):
    player = PlayerCreate(name=name, handle=handle)
    assert player.name == name
    assert player.handle == handle

@given(name=st.text(max_size=0))
def test_player_create_rejects_empty_name(name: str):
    with pytest.raises(ValidationError):
        PlayerCreate(name=name, handle="valid_handle")
```

### 10.4 Acceptance Criteria

- [ ] Hypothesis is a dev dependency in `pyproject.toml`.
- [ ] At least one property-based test exists for each Pydantic model.
- [ ] Hypothesis profiles are configured (dev, default, ci).
- [ ] `@pytest.mark.hypothesis` is registered and tests are runnable in isolation.

---

## 11. Continuous Testing (Developer Experience)

### 11.1 Discussion

Continuous testing runs affected tests automatically when files change, providing instant feedback during development. This is a **local DX tool**, not a CI requirement.

### 11.2 User Stories

- **US-16.C1**: As a developer, when I save a file, only the tests affected by my change run automatically.
- **US-16.C2**: As a developer, I get test feedback within seconds of saving, not minutes.

### 11.3 Functional Requirements

**FR-16.C1**: The project SHALL include `pytest-testmon` as an **optional** dev dependency for selective test execution. Testmon tracks which tests are affected by code changes using coverage data.

**FR-16.C2**: The project SHALL include `pytest-watcher` as an **optional** dev dependency for file-change-triggered test runs.

**FR-16.C3**: A Makefile target SHALL combine both tools:

```makefile
test-watch: ## Continuous selective testing (saves → runs affected tests)
	uv run ptw . -- --testmon -x --tb=short
```

**FR-16.C4**: Testmon's database (`.testmondata`) SHALL be listed in `.gitignore`. It is a local cache, not a shared artifact.

**FR-16.C5**: Continuous testing is NOT a CI requirement. CI always runs the full test suite. Testmon is purely for local development speed.

**FR-16.C6**: If `pytest-testmon` produces false negatives (misses an affected test), running `uv run pytest --testmon-forceselect` SHALL clear its cache and rerun everything.

### 11.4 Acceptance Criteria

- [ ] `make test-watch` starts a file watcher that reruns affected tests on save.
- [ ] `.testmondata` is in `.gitignore`.
- [ ] Testmon correctly identifies affected tests when a source file changes.
- [ ] CI does NOT use testmon — it runs the full suite.

---

## 12. Mutation Testing

### 12.1 Discussion

Mutation testing measures test quality by introducing small code changes (mutations) and checking if tests catch them. It answers: "if I introduce a bug, will my tests find it?"

### 12.2 Recommendation

**FR-16.38**: Mutation testing is NOT required for v1. Here's why:

| Consideration | Assessment |
|---------------|------------|
| Value | High — catches weak tests that have high coverage but low effectiveness |
| Cost | High — mutation runs are 10-100x slower than normal test runs |
| Maturity | TTA v1 has higher priorities (get tests written, then optimize them) |
| Tooling | `mutmut` 3.5.0 — Python 3.12+ compatible, JSON output, incremental runs |

**FR-16.39**: When the test suite is stable and coverage exceeds 80% across game-critical code, mutation testing SHOULD be introduced:
- Use `mutmut` 3.5.0+ (actively maintained, Python 3.12+ support, async fixes in v3.5.0).
- Scope to critical modules first: `paths_to_mutate = ["src/turn_pipeline/"]`.
- Run mutations nightly, not on every PR (typical run: 30-120 minutes).
- Target a mutation score ≥ 75% for critical modules.

**FR-16.40**: When adopted, the configuration SHALL be:

```toml
# pyproject.toml
[tool.mutmut]
paths_to_mutate = ["src/turn_pipeline/", "src/session/"]
tests_dir = "tests/"
```

```makefile
# Makefile
test-mutate: ## Run mutation testing (slow — nightly only)
	uv run mutmut run
	uv run mutmut results
```

Mutmut produces `mutants/mutmut-stats.json` for CI integration.

### 12.3 Acceptance Criteria

- [ ] A decision document exists explaining when mutation testing will be adopted.
- [ ] If adopted: mutation testing runs nightly and produces a JSON report.
- [ ] If adopted: mutation score ≥ 75% for game-critical modules.

---

## 13. Test Organization & Conventions

### 13.1 Functional Requirements

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
    "hypothesis: property-based test (Hypothesis)",
]
```

**FR-16.44**: `conftest.py` SHALL auto-detect the test environment and configure accordingly:
- If service containers are available: use real databases for integration tests.
- Otherwise: **skip** integration tests with a clear message (never silently mock — see §3).

### 13.2 Acceptance Criteria

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

Scenario: Integration tests skip without services, not pass
  Given test services (Neo4j, Redis, PostgreSQL) are NOT running
  When a developer runs "uv run pytest -m integration"
  Then all integration tests are SKIPPED with message "service not available"
  And zero integration tests show as PASSED
  And the developer sees a clear instruction to run "make test-up"

Scenario: Integration tests fail on real service errors
  Given test services are running via "make test-up"
  And a developer introduces a broken Neo4j query
  When the integration test suite runs
  Then the test with the broken query FAILS (not skips)
  And the failure message includes the actual Neo4j error

Scenario: MockLLMClient returns deterministic responses
  Given a test configures MockLLMClient with a pattern "forest" → "The forest is dark."
  When the turn pipeline processes input containing "forest"
  Then the mock returns "The forest is dark." without making a real API call
  And the mock records the full prompt for assertion
  And the test completes in under 100ms

Scenario: Hypothesis finds edge case in model validation
  Given a Pydantic model has a field with constraints (min_length=1, max_length=100)
  When Hypothesis generates 100 random inputs
  Then all valid inputs produce a valid model instance
  And all invalid inputs raise ValidationError
  And if a failing case is found, Hypothesis reports the minimal reproduction

Scenario: Continuous testing reruns affected tests on save
  Given pytest-testmon has a warm cache from a previous test run
  And pytest-watcher is running via "make test-watch"
  When a developer saves changes to src/session/manager.py
  Then only tests that depend on session/manager.py are rerun
  And tests for unrelated modules are NOT rerun
  And feedback appears within seconds

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

---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.

### What Shipped

- **167 test files** across `tests/unit/`, `tests/integration/`, and `tests/bdd/`
- **2 268 unit tests** (approximate, at wave 38 merge) — pytest suite with full
  `make test` execution in CI
- **BDD suite** — Gherkin feature files in `tests/bdd/features/` with step
  implementations; `TestClient` + `AsyncMock` pattern for sync BDD execution
- **AC compliance tests** — dedicated `test_s*_ac_compliance.py` files for S11, S15, S17,
  S23, S24, S25, S26, S27, S28
- **Sim harness** — `scripts/sim/` with scenario YAML files; 11/11 v1 sim turns passed
  (PR #161)
- **`pyproject.toml`** — pytest config with `asyncio_mode = "auto"`, coverage, and
  test-path discovery
- **`docker-compose.test.yml`** — isolated postgres/redis/neo4j for integration tests

### Evidence

- `make test` green across all v1 PRs (waves 30–38)
- `tests/bdd/features/` contains feature files for all major v1 flows
- Sim PR #161 passed 11/11 scenarios

### Gaps Found in v1

1. **No live Neo4j integration tests in CI** — Neo4j degrades gracefully; graph path
   never exercised against a real instance in CI
2. **No mutation testing** — coverage metric only; fault detection quality unknown
3. **No performance benchmark suite in CI** — `test_s28_performance.py` asserts latency
   budgets but against in-memory mocks, not real infra
4. **Sim harness is single-session** — does not test multi-player concurrency

### Deferred to v2

| Feature | Reason |
|---------|--------|
| Live Neo4j integration tests | Requires docker-compose.test.yml update |
| Mutation testing (mutmut) | v2 quality uplift |
| Real-infra perf benchmarks | v2 staging environment needed |
| Multi-session sim scenarios | v2 concurrency validation |

### Lessons for v2

- The AAA test pattern and BDD-first compliance tests are a strong foundation — keep both
- AC compliance test files are the clearest coupling between spec ACs and code; add one
  per new spec in v2
- Integration test conftest skips DB setup when Postgres is unavailable; add a CI matrix
  job with live services so the integration path is always exercised
