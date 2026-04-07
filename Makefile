.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Self-documenting help — parses '## ' comments after targets
# ---------------------------------------------------------------------------
.PHONY: help validate-specs validate-plans validate-all regen-indexes \
        lint format typecheck test quality \
        docker-up docker-down docker-langfuse

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
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
lint: ## Run ruff linter
	uv run ruff check src/

format: ## Run ruff formatter
	uv run ruff format src/

typecheck: ## Run pyright
	uv run pyright src/

quality: lint format typecheck ## Run lint + format + typecheck

# ---------------------------------------------------------------------------
# Testing (once tests/ exist)
# ---------------------------------------------------------------------------
test: ## Run all tests
	uv run pytest

test-unit: ## Run unit tests only (no external services needed)
	uv run pytest -m "not integration and not e2e"

test-integration: ## Run integration tests (requires make test-up)
	uv run pytest -m integration

test-watch: ## Continuous selective testing (reruns affected tests on save)
	uv run ptw . -- --testmon -x --tb=short

test-up: ## Start test service containers
	docker compose -f docker-compose.test.yml up -d --wait

test-down: ## Stop test service containers
	docker compose -f docker-compose.test.yml down

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
docker-up: ## Start core infrastructure (postgres, neo4j, redis)
	docker compose up -d

docker-down: ## Stop infrastructure
	docker compose down

docker-langfuse: ## Start with Langfuse profile
	docker compose --profile langfuse up -d
