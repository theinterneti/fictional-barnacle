# Stage 1: Builder
FROM python:3.12-slim AS builder

# Install uv (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies only (cache layer — no project install yet)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project

# Copy source and install the project package
COPY src/ src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

# Create non-root user
RUN groupadd -r tta && useradd -r -g tta -d /app -s /sbin/nologin tta

WORKDIR /app

# Copy venv and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Set PATH to use venv
ENV PATH="/app/.venv/bin:$PATH"

USER tta

EXPOSE 8000

CMD ["uvicorn", "tta.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
