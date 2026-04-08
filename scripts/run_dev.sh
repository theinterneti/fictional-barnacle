#!/usr/bin/env bash
# Launch TTA API with env vars from .env
set -euo pipefail

if [ ! -f .env ]; then
    echo "ERROR: .env file not found. Copy .env.example and configure it." >&2
    exit 1
fi

set -a
source .env
set +a
exec uv run uvicorn tta.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000
