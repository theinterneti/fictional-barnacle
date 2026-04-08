#!/usr/bin/env bash
# Launch TTA API with env vars from .env
set -a
source .env
set +a
exec uv run uvicorn tta.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000
