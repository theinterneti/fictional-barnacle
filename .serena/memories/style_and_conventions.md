# Style & Conventions

## Python
- Python 3.12+ — use `str | None` not `Optional[str]`
- 88-char line length (Ruff)
- Ruff lint rules: E, W, F, I, B, C4, UP
- Pyright `standard` mode
- Type hints everywhere

## Testing
- AAA pattern (Arrange-Act-Assert)
- asyncio_mode="auto" (no manual @pytest.mark.asyncio needed)
- Markers: unit, integration, e2e, slow, neo4j, redis, postgres, bdd, hypothesis

## Git
- Conventional Commits (feat:, fix:, build:, test:, etc.)

## Project
- Specs are source of truth — read spec before implementing
- uv only (never pip)
- [dependency-groups] for dev deps (PEP 735)
