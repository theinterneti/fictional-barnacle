#!/bin/bash

# PR Review Gate — Advisory Copilot CLI Hook
#
# Blocks `gh pr merge` commands in Copilot CLI sessions.
# Forces merges through the GitHub web UI where branch protection
# rulesets enforce review requirements (conversation resolution,
# required approvals, status checks).
#
# This is an ADVISORY guard for Copilot CLI only — the authoritative
# gate is the GitHub Ruleset on main. See scripts/merge-guard.sh for
# a manual pre-merge check tool.

set -euo pipefail

INPUT=$(cat)

TOOL_NAME=""
TOOL_INPUT=""

if command -v jq &>/dev/null; then
  TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.toolName // empty' 2>/dev/null || echo "")
  TOOL_INPUT=$(printf '%s' "$INPUT" | jq -r '.toolInput // empty' 2>/dev/null || echo "")
fi

if [[ -z "$TOOL_NAME" ]]; then
  TOOL_NAME=$(printf '%s' "$INPUT" | grep -oE '"toolName"\s*:\s*"[^"]*"' | head -1 | sed 's/.*"toolName"\s*:\s*"//;s/"//')
fi
if [[ -z "$TOOL_INPUT" ]]; then
  TOOL_INPUT=$(printf '%s' "$INPUT" | grep -oE '"toolInput"\s*:\s*"[^"]*"' | head -1 | sed 's/.*"toolInput"\s*:\s*"//;s/"//')
fi

COMBINED="${TOOL_NAME} ${TOOL_INPUT}"

# Only intercept bash/shell commands containing `gh pr merge`
if printf '%s\n' "$COMBINED" | grep -qiE 'gh\s+pr\s+merge'; then
  echo ""
  echo "🚫 PR Review Gate: Direct merging via CLI is blocked."
  echo ""
  echo "   Merges must go through the GitHub web UI where branch"
  echo "   protection enforces:"
  echo "     • All review conversations resolved"
  echo "     • Required status checks passed (CI)"
  echo ""
  echo "   Alternatives:"
  echo "     • make review-check PR=<n>  — check review status"
  echo "     • gh pr view <n> --web      — open PR in browser"
  echo ""
  exit 1
fi

exit 0
