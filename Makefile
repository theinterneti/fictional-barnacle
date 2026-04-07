.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Self-documenting help — parses '## ' comments after targets
# ---------------------------------------------------------------------------
.PHONY: help validate-specs validate-plans validate-all regen-indexes \
        lint format typecheck test test-unit test-integration test-watch \
        test-up test-down quality check \
        dev up down build logs shell \
        docker-up docker-down docker-langfuse \
        migrate migrate-neo4j clean

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Spec & plan validation
# ---------------------------------------------------------------------------
validate-specs: ## Run spec indexer with validation
	python3 specs/index_specs.py --validate

validate-plans: ## Run plan indexer with validation
	python3 specs/index_plans.py --validate

validate-all: validate-specs validate-plans ## Run both validators

regen-indexes: ## Regenerate spec and plan index files
	python3 specs/index_specs.py
	python3 specs/index_plans.py

# ---------------------------------------------------------------------------
# Code quality (once src/ exists)
# ---------------------------------------------------------------------------
lint: ## Run ruff linter + pyright type checker
	uv run ruff check src/
	uv run pyright src/

format: ## Run ruff formatter + auto-fix
	uv run ruff format src/
	uv run ruff check --fix src/

typecheck: ## Run pyright (standalone)
	uv run pyright src/

quality: lint format ## Run lint + format

# ---------------------------------------------------------------------------
# Testing (once tests/ exist)
# ---------------------------------------------------------------------------
test: ## Run all tests with coverage
	uv run pytest --cov

test-unit: ## Run unit tests only (no external services needed)
	uv run pytest -m "not integration and not e2e"

test-integration: ## Run integration tests (starts/stops test services)
	docker compose -f docker-compose.test.yml up -d --wait
	uv run pytest tests/integration/ -v; \
	EXIT_CODE=$$?; \
	docker compose -f docker-compose.test.yml down; \
	exit $$EXIT_CODE

test-watch: ## Continuous selective testing (reruns affected tests on save)
	uv run ptw . -- --testmon -x --tb=short

test-up: ## Start test service containers
	docker compose -f docker-compose.test.yml up -d --wait

test-down: ## Stop test service containers
	docker compose -f docker-compose.test.yml down

check: lint test ## Full CI gate (lint + test)

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev: ## Start dependency services and run API locally with reload
	docker compose up -d postgres neo4j redis
	uv run uvicorn tta.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000

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
	rm -rf .pytest_cache .ruff_cache .mypy_cache
