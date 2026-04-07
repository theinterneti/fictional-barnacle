# Stage 1: Builder
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (cache layer)
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev deps)
RUN uv sync --no-dev --frozen

# Copy source
COPY src/ src/

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
