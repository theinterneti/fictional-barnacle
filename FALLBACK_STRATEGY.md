# =============================================================================
# 1Password Secret Injection - Fallback Strategy
# =============================================================================
# This document explains the fallback workflow if 1Password CLI fails
# or if agents have trouble with op run.
#
# =============================================================================
# SITUATION: op run fails or agents can't use 1Password
# =============================================================================
#
# Step 1: Create a local .env with actual values (not 1Password URIs)
# -----------------------------------------------------------------------------
# Copy .env.template to .env, then replace op:// URIs with actual keys
# You can read keys from 1Password directly:
#
#   op read op://TTA/Groq/credential
#   op read op://TTA/OpenRouter/credential
#   etc.
#
# Step 2: Keep .env in gitignore
# -----------------------------------------------------------------------------
# The .env file should NEVER be committed:
#   - It's already in .gitignore: .env
#   - Verify with: grep "\.env$" .gitignore
#
# Step 3: Run without 1Password
# -----------------------------------------------------------------------------
# Now you can run directly without op run:
#   python -m tta                          # fictional-barnacle
#   python src/main.py start               # TTA
#   uv run python -m ttadev.observability  # TTA.dev
#
# =============================================================================
# REESTABLISHING 1PASSWORD AFTER FALLBACK
# =============================================================================
#
# To return to 1Password workflow:
#
# 1. Delete the real values in .env
# 2. Replace with op:// URIs (copy from .env.template)
# 3. Run with op run again:
#    op run --env-file=.env -- python -m tta
#
# =============================================================================
# PREVENTION: If op run hangs
# =============================================================================
#
# If op run times out or hangs:
#
# 1. Check 1Password Desktop is running
# 2. Run: op account list  (should show your account)
# 3. Try: op vault list    (should show TTA vault)
# 4. If still failing, kill and restart 1Password Desktop
#
# =============================================================================
# DEBUGGING 1PASSWORD CLI ISSUES
# =============================================================================
#
# Common issues and fixes:
#
#-"Not signed in":
#   op signin my.1password.com
#
#-"Authorization prompt dismissed":
#   Unlock 1Password Desktop and try again
#   Or run: eval $(op signin --)
#
#-"Item not found":
#   op item list --vault TTA
#   Verify the item exists
#
# =============================================================================
# QUICK REFERENCE: Common Commands
# =============================================================================
#
# Read a secret:
#   op read op://TTA/Groq/credential
#
# List vault items:
#   op item list --vault TTA
#
# Run with secret injection:
#   op run --env-file=.env -- YOUR_COMMAND
#
# Test env file loads:
#   op run --env-file=.env -- printenv | grep KEY_NAME
#
# =============================================================================
# CREATED: April 2026
# PURPOSE: TTA Project Secret Management
# =============================================================================