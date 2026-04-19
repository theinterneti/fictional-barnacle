#!/usr/bin/env bash
# S28 AC-28.04 — Run the locust load test in headless mode.
#
# Requirements:
#   - TTA server running at http://localhost:8000 with LLM_MOCK=true
#   - uv environment with locust installed (uv sync --extra dev)
#
# Usage:
#   bash scripts/load_test.sh           # defaults: 10 VU, 60 s
#   VU=20 DURATION=120s bash scripts/load_test.sh

set -euo pipefail

VU="${VU:-10}"
SPAWN_RATE="${SPAWN_RATE:-2}"
DURATION="${DURATION:-60s}"
HOST="${HOST:-http://localhost:8000}"
REPORTS_DIR="reports"

mkdir -p "${REPORTS_DIR}"

echo "==================================================================="
echo " TTA Load Test — S28 AC-28.04"
echo "   VUs: ${VU}  spawn-rate: ${SPAWN_RATE}/s  duration: ${DURATION}"
echo "   Host: ${HOST}"
echo "   Results → ${REPORTS_DIR}/load_test_*.csv"
echo "==================================================================="

# Run locust headless; exit code is set by the quitting listener in
# load_test.py if p95 or error rate thresholds are exceeded.
uv run locust \
    -f scripts/load_test.py \
    --headless \
    --users "${VU}" \
    --spawn-rate "${SPAWN_RATE}" \
    --run-time "${DURATION}" \
    --csv "${REPORTS_DIR}/load_test" \
    --html "${REPORTS_DIR}/load_test.html" \
    --host "${HOST}"

echo ""
echo "Reports written to ${REPORTS_DIR}/"
