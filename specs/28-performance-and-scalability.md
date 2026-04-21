
---

## v1 Closeout (Non-normative)

> This section is retrospective and non-normative. It documents what shipped in the v1
> baseline, what was verified, what gaps were found, and what is deferred to v2.

### What Shipped

- **Turn latency budget** — AC-28.1 P95 < 30 s enforced via `test_s28_performance.py`
- **LLM concurrency semaphore** — `src/tta/llm/semaphore.py`; limits parallel LLM calls
  to `settings.max_concurrent_llm_calls` (AC-28.5)
- **Connection pool config** — PostgreSQL and Redis pool sizes set in `settings` and
  tested in `test_s28_performance.py`
- **Graceful degradation under load** — `test_s28_performance.py` verifies server stays
  responsive when semaphore is at capacity
- **Pool metrics** — `tests/unit/observability/test_pool_metrics.py` covers AC-28.4

### Evidence

- `tests/unit/performance/test_s28_performance.py` — 6 test classes:
  `TestS28LatencyBudgets`, `TestS28Semaphore`, `TestS28PoolConfig`,
  `TestS28GracefulDegradation`, `TestS28Shutdown`, `TestS28MemoryBounds`
- `tests/unit/observability/test_pool_metrics.py` — AC-28.4

### Gaps Found in v1

1. **No live load test** — all performance tests run against in-process mocks; no JMeter
   / k6 load test against a real server with PostgreSQL + Redis + Neo4j
2. **Multi-instance throughput untested** (AC-28.8 deferred) — horizontal scaling
   behaviour is unknown
3. **Memory bounds are soft** — `TestS28MemoryBounds` asserts no obvious leak in unit
   tests; no long-running soak test exists

### Deferred to v2

| Feature | Reason |
|---------|--------|
| Live load test (k6/JMeter) | Requires live infra environment |
| Multi-instance throughput (AC-28.8) | Requires container orchestration |
| Soak test for memory leaks | Requires long-running test environment |

### Lessons for v2

- The semaphore is the most important performance control we have; never remove it or
  make it optional
- Pool sizing is declarative and easy to tune; document recommended production values in
  the ops runbook
- P95 latency budget (30 s) is generous for v1; v2 should target P95 < 15 s with live
  infrastructure measurements
