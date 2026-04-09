#!/bin/bash

# ============================================================================
# merge-guard.sh — Enforce Copilot code review before merging PRs
#
# Checks that a PR has:
#   1. At least one completed review (any reviewer)
#   2. Zero unresolved review conversation threads
#
# Usage:
#   ./scripts/merge-guard.sh <PR_NUMBER>       # check only
#   ./scripts/merge-guard.sh --merge <PR_NUM>  # check then merge
#   make merge PR=42                           # via Makefile
# ============================================================================

set -euo pipefail

readonly SCRIPT_NAME="$(basename "$0")"
readonly REPO="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "unknown/unknown")}"
readonly OWNER="${REPO%%/*}"
readonly NAME="${REPO##*/}"

usage() {
    echo "Usage: $SCRIPT_NAME [--merge] [PR_NUMBER] [-- merge-flags...]"
    echo ""
    echo "Checks that a GitHub PR has reviews and all comments are resolved."
    echo ""
    echo "Modes:"
    echo "  $SCRIPT_NAME 42           Check PR #42 review status"
    echo "  $SCRIPT_NAME --merge 42   Check then merge PR #42"
    echo "  $SCRIPT_NAME              Auto-detect PR from current branch"
    echo ""
    echo "Merge flags after -- are passed through to gh pr merge."
    exit 0
}

get_pr_number() {
    local pr_num="${1:-}"
    if [[ -n "$pr_num" ]]; then
        echo "$pr_num"
        return
    fi

    local branch
    branch="$(git branch --show-current 2>/dev/null || true)"
    if [[ -z "$branch" || "$branch" == "main" ]]; then
        echo "Error: No PR number provided and not on a feature branch." >&2
        echo "Usage: $SCRIPT_NAME <PR_NUMBER>" >&2
        exit 1
    fi

    local detected
    detected="$(gh pr view "$branch" --json number -q .number 2>/dev/null || true)"
    if [[ -z "$detected" ]]; then
        echo "Error: No open PR found for branch '$branch'." >&2
        exit 1
    fi
    echo "$detected"
}

check_reviews_and_threads() {
    local pr_num="$1"

    echo "============================================================================"
    echo "  Merge Guard — PR #$pr_num ($OWNER/$NAME)"
    echo "============================================================================"

    local response
    response="$(gh api graphql -f query='
    query($owner: String!, $name: String!, $pr: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $pr) {
          title
          state
          reviewThreads(first: 100) {
            totalCount
            nodes {
              isResolved
              isOutdated
              comments(first: 1) {
                nodes {
                  author { login }
                  body
                }
              }
            }
          }
          reviews(first: 20) {
            nodes {
              author { login }
              state
            }
          }
        }
      }
    }
    ' -f owner="$OWNER" -f name="$NAME" -F pr="$pr_num")"

    local state title
    state="$(echo "$response" | jq -r '.data.repository.pullRequest.state')"
    title="$(echo "$response" | jq -r '.data.repository.pullRequest.title')"

    echo "  Title: $title"
    echo "  State: $state"
    echo ""

    local total_threads unresolved_threads
    total_threads="$(echo "$response" | jq '.data.repository.pullRequest.reviewThreads.totalCount')"
    unresolved_threads="$(echo "$response" | jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false and .isOutdated == false)] | length')"

    echo "  Review threads: $total_threads total, $unresolved_threads unresolved"

    if [[ "$unresolved_threads" -gt 0 ]]; then
        echo ""
        echo "  Unresolved comments:"
        echo "$response" | jq -r '
            .data.repository.pullRequest.reviewThreads.nodes[]
            | select(.isResolved == false and .isOutdated == false)
            | "    [\(.comments.nodes[0].author.login)] \(.comments.nodes[0].body | split("\n")[0] | .[0:100])"
        ' 2>/dev/null || true
    fi

    local review_count
    review_count="$(echo "$response" | jq '[.data.repository.pullRequest.reviews.nodes[]] | length')"

    echo ""
    echo "  Reviews: $review_count total"

    echo ""
    echo "============================================================================"
    local failed=false

    if [[ "$review_count" -eq 0 ]]; then
        echo "  ❌ BLOCKED: No reviews found. Wait for Copilot code review."
        failed=true
    fi

    if [[ "$unresolved_threads" -gt 0 ]]; then
        echo "  ❌ BLOCKED: $unresolved_threads unresolved review comment(s)."
        echo "     Resolve all review threads before merging."
        failed=true
    fi

    if [[ "$failed" == "true" ]]; then
        echo "============================================================================"
        echo ""
        echo "  To resolve: gh pr view $pr_num --web"
        return 1
    fi

    echo "  ✅ CLEAR: All review comments resolved. Safe to merge."
    echo "============================================================================"
    return 0
}

# Parse arguments
MERGE_MODE=false
MERGE_FLAGS=()
PR_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            ;;
        --merge)
            MERGE_MODE=true
            shift
            ;;
        --)
            shift
            MERGE_FLAGS=("$@")
            break
            ;;
        *)
            PR_ARG="$1"
            shift
            ;;
    esac
done

PR_NUM="$(get_pr_number "$PR_ARG")"

if [[ "$MERGE_MODE" == "true" ]]; then
    if check_reviews_and_threads "$PR_NUM"; then
        echo ""
        echo "Proceeding with merge..."
        gh pr merge "$PR_NUM" "${MERGE_FLAGS[@]}"
    else
        echo ""
        echo "Merge blocked. Resolve review comments first."
        exit 1
    fi
else
    check_reviews_and_threads "$PR_NUM"
fi
