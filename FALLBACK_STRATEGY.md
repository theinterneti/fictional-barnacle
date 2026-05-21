# =============================================================================
# TTA — 1Password Fallback / Resolved .env Workflow
# =============================================================================
# Preferred pattern when you want a normal .env on disk:
#   1. cp .env.example .env
#   2. replace selected values with op:// references
#   3. op inject -i .env -o .env.resolved
#   4. mv .env.resolved .env
#   5. run commands normally (the app loads .env itself)
#
# `.env` stays gitignored. Agents should not inspect it.
#
# =============================================================================
# SITUATION: You need a resolved local .env instead of runtime op wrapping
# =============================================================================
#
# Step 1: Start from the committed example
# -----------------------------------------------------------------------------
#   cp .env.example .env
#
# Step 2: Swap placeholders for 1Password references where useful
# -----------------------------------------------------------------------------
# Example:
#   TTA_LANGFUSE_PUBLIC_KEY=op://TTA/Langfuse Public/credential
#   TTA_LANGFUSE_SECRET_KEY=op://TTA/Langfuse Secret/credential
#
# Step 3: Materialize a real .env once
# -----------------------------------------------------------------------------
#   op inject -i .env -o .env.resolved
#   mv .env.resolved .env
#
# Step 4: Run normally
# -----------------------------------------------------------------------------
#   python -m tta
#   uv run uvicorn tta.api.app:create_app --factory --reload --host 0.0.0.0 --port 8000
#   uv run pytest
#
# =============================================================================
# REGENERATING .env AFTER SECRET CHANGES
# =============================================================================
#
# Re-run:
#   op inject -i .env -o .env.resolved
#   mv .env.resolved .env
#
# =============================================================================
# IF 1PASSWORD CLI FAILS
# =============================================================================
#
# 1. Check 1Password Desktop is running
# 2. Run: op account list
# 3. Run: op vault list
# 4. If still failing, restart 1Password Desktop and retry inject
#
# =============================================================================
# QUICK REFERENCE
# =============================================================================
#
# Read a secret directly:
#   op read op://TTA/Groq/credential
#
# Materialize .env from references:
#   op inject -i .env -o .env.resolved && mv .env.resolved .env
#
# Verify a resolved .env without printing secrets:
#   python - <<'PY'
#   from tta.config import Settings
#   s = Settings()
#   print('database configured:', bool(s.database_url))
#   print('neo4j configured:', bool(s.neo4j_password))
#   PY
#
# =============================================================================
# CREATED: April 2026
# PURPOSE: TTA Project Secret Management
# =============================================================================
