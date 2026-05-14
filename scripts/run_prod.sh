#!/usr/bin/env bash
# TTA API server wrapper — resolves all 1Password secrets
set -euo pipefail
cd /home/theinterneti/Repos/fictional-barnacle

# Resolve embedded secrets that op run can't handle
export TTA_DB_PASSWORD=$(op read "op://TTA/Postgres/password")
export TTA_NEO4J_PASSWORD=$(op read "op://TTA/TTA Neo4j/password")
export TTA_REDIS_PASSWORD=$(op read "op://TTA/TTA Redis/password")
export TTA_DATABASE_URL="postgresql+asyncpg://admin:${TTA_DB_PASSWORD}@localhost:5433/tta"

# Resolve remaining secrets via op run (uses process substitution to avoid subshell)
while IFS='=' read -r key value; do
    [ -z "$key" ] && continue
    case "$key" in
        TTA_DB_PASSWORD|TTA_NEO4J_PASSWORD|TTA_REDIS_PASSWORD|TTA_DATABASE_URL) ;;
        *) export "$key"="$value" ;;
    esac
done < <(op run --env-file=.env -- printenv)

exec uv run uvicorn tta.api.app:create_app --factory --host 0.0.0.0 --port 8000
