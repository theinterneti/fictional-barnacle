.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Self-documenting help — parses '## ' comments after targets
# ---------------------------------------------------------------------------
.PHONY: help validate-specs validate-plans validate-openapi validate-all regen-indexes \
	dashboard trace trace-html \
        lint format typecheck test test-unit test-integration test-persistence test-watch \
        test-bdd test-hypothesis \
        test-up test-down quality check check-format gate gate-full \
        doctor status changed-tests gate-changed \
        changelog-check version-check release-check release-dry-run \
        work-status work-next work-advance \
        tdd-check spec-check complete-check \
        pr-prep pr-check release-workflow-check \
        practical-gate \
        dev play playtest playtest-web up down build logs shell \
        docker-up docker-down docker-langfuse \
        migrate migrate-neo4j clean load-test sim sim-quick

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Spec & plan validation
# ---------------------------------------------------------------------------
validate-specs: ## Run spec indexer with validation
	uv run python specs/index_specs.py --validate

validate-plans: ## Run plan indexer with validation
	uv run python plans/index_plans.py --validate

validate-openapi: ## Validate OpenAPI spec passes openapi-spec-validator
	uv run pytest tests/unit/api/test_s10_ac_compliance.py::TestAC1002OpenAPIValidity -v

validate-all: validate-specs validate-plans validate-openapi trace ## Run all validators including AC traceability

regen-indexes: ## Regenerate spec and plan index files (writes specs/index.{md,json} + plans/index.{md,json})
	uv run python specs/index_specs.py --out specs/index
	uv run python plans/index_plans.py --out plans/index

trace: ## Validate AC traceability (exit 1 on orphan citations)
	uv run python specs/trace_acs.py --validate

trace-html: ## Generate specs/trace.html AC traceability dashboard
	uv run python specs/trace_acs.py --html

dashboard: ## Generate specs/index.html completeness visualization
	uv run python specs/index_specs.py --html --out index && mv index.html specs/index.html

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
lint: ## Run ruff linter + pyright type checker
	uv run ruff check
	uv run pyright

format: ## Auto-format and auto-fix code
	uv run ruff format
	uv run ruff check --fix

typecheck: ## Run pyright (standalone)
	uv run pyright

quality: format lint ## Format, then lint + type-check

check-format: ## Verify formatting (CI-style, no mutations)
	uv run ruff format --check

# ---------------------------------------------------------------------------
# Local pre-push gate (run BEFORE pushing to remote)
# ---------------------------------------------------------------------------
gate: check-format lint trace validate-specs validate-plans validate-openapi test-unit ## Full pre-push gate — run before every push

gate-full: gate test-integration ## Pre-push gate + integration tests (requires test services)

# ---------------------------------------------------------------------------
# Deterministic local workflow helpers
# ---------------------------------------------------------------------------
doctor: ## Check local developer workflow prerequisites
	uv run python scripts/dev_workflow.py doctor

status: ## Show deterministic repo workflow status
	uv run python scripts/dev_workflow.py status

changed-tests: ## Plan targeted checks for changed files
	uv run python scripts/changed_tests.py

gate-changed: ## Run targeted changed-file local gate
	uv run python scripts/dev_workflow.py gate-changed

# ---------------------------------------------------------------------------
# Change and release metadata
# ---------------------------------------------------------------------------
changelog-check: ## Validate unreleased changelog coverage for changed files
	uv run python scripts/changelog_check.py

version-check: ## Validate pyproject version and release changelog section
	uv run python scripts/version_check.py --release

release-check: changelog-check version-check gate ## Run release readiness checks without mutating state

release-dry-run: ## Preview release gate and current version metadata
	uv run python scripts/changelog_check.py --json
	uv run python scripts/version_check.py --json

# ---------------------------------------------------------------------------
# SDD work-item state machine
# ---------------------------------------------------------------------------
work-status: ## Show SDD work-item state summary
	uv run python scripts/workflow_state.py status

work-next: ## Show the next non-terminal SDD work item
	uv run python scripts/workflow_state.py next

work-advance: ## Advance a work item after deterministic evidence is present
	uv run python scripts/workflow_state.py advance $(ITEM) $(STAGE)

# ---------------------------------------------------------------------------
# SDD/TDD completion checks
# ---------------------------------------------------------------------------
tdd-check: ## Validate changed production files include test evidence
	uv run python scripts/tdd_guard.py

spec-check: ## Validate a spec is ready for approved implementation (SPEC=<path>)
	uv run python scripts/spec_lifecycle.py $(SPEC)

complete-check: ## Run deterministic completion gate for current changed slice
	uv run python scripts/completion_check.py

# ---------------------------------------------------------------------------
# PR and release automation
# ---------------------------------------------------------------------------
pr-prep: ## Generate a deterministic PR body from local evidence
	uv run python scripts/pr_prep.py --body

pr-check: ## Validate branch and changed-file readiness for PR creation
	uv run python scripts/pr_prep.py

release-workflow-check: ## Validate GitHub release workflow wiring
	uv run pytest tests/unit/scripts/test_release_workflow.py -q

# ---------------------------------------------------------------------------
# Practical application evidence
# ---------------------------------------------------------------------------
practical-gate: ## Validate practical application evidence files
	uv run python scripts/practical_gate.py

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test: ## Run all tests with coverage
	uv run pytest --cov

test-unit: ## Run unit tests only (no external services needed)
	uv run pytest tests/unit tests/bdd -m "not integration and not e2e"

test-integration: ## Run integration tests (starts/stops test services)
	docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for services to be ready..."
	@for i in $$(seq 1 30); do \
		pg_isready -h localhost -p 5434 -U tta_test >/dev/null 2>&1 && break; \
		sleep 1; \
	done
	uv run pytest tests/integration/ -v; \
	EXIT_CODE=$$?; \
	docker compose -f docker-compose.test.yml down; \
	exit $$EXIT_CODE

test-persistence: ## Run persistence gate (S12/S13/S28) with structured report
	@echo "=== Persistence Gate ==="
	@echo "S12: PostgreSQL + Redis + GDPR"
	@echo "S13: Neo4j world graph"
	@echo "S28: Performance benchmarks"
	@echo ""
	docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for PostgreSQL..."
	@for i in $$(seq 1 30); do \
		pg_isready -h localhost -p 5434 -U tta_test >/dev/null 2>&1 && break; \
		sleep 1; \
		test $$i -eq 30 && echo "ERROR: PostgreSQL did not become ready" && exit 1; \
	done
	@echo "Waiting for Neo4j..."
	@for i in $$(seq 1 10); do \
		curl -sf http://localhost:7474 >/dev/null 2>&1 && break; \
		sleep 2; \
		test $$i -eq 10 && echo "ERROR: Neo4j did not become ready" && exit 1; \
	done
	@echo ""
	@echo "--- Running S12 persistence tests ---"
	uv run pytest tests/integration/test_s12_persistence_integration.py -v --tb=short 2>&1 | tee /tmp/s12-$$$$.txt; S12_EXIT=$${PIPESTATUS[0]}
	@echo ""
	@echo "--- Running S13 Neo4j tests ---"
	uv run pytest tests/integration/test_s13_neo4j_integration.py -v --tb=short 2>&1 | tee /tmp/s13-$$$$.txt; S13_EXIT=$${PIPESTATUS[0]}
	@echo ""
	@echo "--- Running S28 performance tests ---"
	PERF=1 uv run pytest tests/integration/test_s28_performance.py -v --tb=short 2>&1 | tee /tmp/s28-$$$$.txt; S28_EXIT=$${PIPESTATUS[0]}
	@echo ""
	@echo "=== Gate Summary ==="
	@python3 -c "\nimport re, os\nfrom pathlib import Path\npid = os.getpid()\nsections = {\n    'S12': f'/tmp/s12-{pid}.txt',\n    'S13': f'/tmp/s13-{pid}.txt',\n    'S28': f'/tmp/s28-{pid}.txt',\n}\nexit_code = 0\nfor name, path in sections.items():\n    if not Path(path).exists():\n        print(f'{name}: SKIPPED (no results)')\n        continue\n    text = Path(path).read_text()\n    passed = len(re.findall(r'PASSED', text))\n    failed = len(re.findall(r'FAILED', text))\n    skipped = len(re.findall(r'SKIPPED', text))\n    if failed > 0:\n        exit_code = 1\n        status = 'FAIL'\n    elif passed > 0:\n        status = 'PASS'\n    else:\n        status = 'SKIP'\n    print(f'{name}: {status} ({passed} passed, {failed} failed, {skipped} skipped)')\nimport sys; sys.exit(exit_code)\n"
	docker compose -f docker-compose.test.yml down

test-watch: ## Continuous selective testing (reruns affected tests on save)
	uv run ptw . -- --testmon -x --tb=short

test-bdd: ## Run BDD acceptance tests only
	uv run pytest tests/bdd/ -v

test-hypothesis: ## Run Hypothesis property-based tests only
	uv run pytest -m hypothesis -v

test-up: ## Start test service containers
	docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for services to be ready..."
	@for i in $$(seq 1 30); do \
		pg_isready -h localhost -p 5434 -U tta_test >/dev/null 2>&1 && break; \
		sleep 1; \
	done

test-down: ## Stop test service containers
	docker compose -f docker-compose.test.yml down

check: ## Full CI gate (mirrors CI quality + test jobs)
	uv run ruff check
	uv run ruff format --check
	uv run pyright
	uv run pytest --cov

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev: ## Start dependency services and run API locally with reload
	docker compose up -d postgres neo4j redis
	uv run uvicorn tta.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000

play: ## Interactive CLI playtest (server must be running via 'make dev')
	uv run python scripts/playtest.py

playtest: ## Run automated LLM playtester + evaluation pipeline (server must be running via 'make dev')
	uv run python -m tta.eval --mode local --api-base-url "$${TTA_API_BASE_URL:-http://localhost:8000}" --output-dir data/eval_output

playtest-web: ## Serve web playtest client on http://localhost:8080 (server must be running via 'make dev')
	@echo "Open http://localhost:8080/playtest.html in your browser"
	@echo "Make sure 'make dev' is running and TTA_CORS_ORIGINS includes http://localhost:8080"
	python -m http.server 8080 -d static

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
up: ## Start infrastructure (docker compose up)
	docker compose up -d

down: ## Stop infrastructure (docker compose down)
	docker compose down

build: ## Build Docker images
	docker compose build

logs: ## Follow container logs
	docker compose logs -f

shell: ## Open a shell in the API container
	docker compose exec tta-api bash

docker-up: up ## (alias) Start infrastructure
docker-down: down ## (alias) Stop infrastructure

docker-langfuse: ## Start with Langfuse profile
	docker compose --profile langfuse up -d

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
migrate: ## Run Alembic database migrations
	uv run alembic upgrade head

migrate-neo4j: ## Run Neo4j graph migrations
	uv run python -m tta.world.migrate

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml

# ---------------------------------------------------------------------------
# PR Workflow
# ---------------------------------------------------------------------------
review-check: ## Check if PR review comments are resolved (PR=<number>)
	@./scripts/merge-guard.sh $(PR)

merge: ## Merge PR after verifying review comments (PR=<number>)
	@./scripts/merge-guard.sh --merge $(PR) -- --squash --delete-branch

# ---------------------------------------------------------------------------
# Load testing
# ---------------------------------------------------------------------------
load-test: ## Run load test (10 VU, 60s; requires server with LLM_MOCK=true)
	bash scripts/load_test.sh

sim: ## Run v1 multi-scenario simulation (requires live server with LLM)
	uv run python scripts/sim_runner.py --verbose

sim-quick: ## Run single-turn smoke check via sim runner
	uv run python scripts/sim_runner.py --quick --verbose
