# Task Completion Checklist

When a task is completed, run:

1. `uv run ruff check src/` — lint check
2. `uv run ruff format --check src/` — format check  
3. `uv run pytest tests/ -v` — all tests pass
4. `git add -A && git commit` — conventional commit message

For larger changes also run:
- `uv run pyright src/` — type checking
- `make validate-all` — spec/plan validation
