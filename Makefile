.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Self-documenting help — parses '## ' comments after targets
# ---------------------------------------------------------------------------
.PHONY: help validate-specs validate-plans validate-openapi validate-all regen-indexes \
	dashboard trace trace-html \
        lint format typecheck test test-unit test-integration test-watch \
        test-bdd test-hypothesis \
        test-up test-down quality check check-format \
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

regen-indexes: ## Regenerate spec and plan index files
	uv run python specs/index_specs.py
	uv run python plans/index_plans.py

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
# Testing
# ---------------------------------------------------------------------------
test: ## Run all tests with coverage
	uv run pytest --cov

test-unit: ## Run unit tests only (no external services needed)
	uv run pytest -m "not integration and not e2e"

test-integration: ## Run integration tests (starts/stops test services)
	docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for services to be ready..."
	@for i in $$(seq 1 30); do \
		pg_isready -h localhost -p 5433 -U tta_test >/dev/null 2>&1 && break; \
		sleep 1; \
	done
	uv run pytest tests/integration/ -v; \
	EXIT_CODE=$$?; \
	docker compose -f docker-compose.test.yml down; \
	exit $$EXIT_CODE

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
		pg_isready -h localhost -p 5433 -U tta_test >/dev/null 2>&1 && break; \
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
