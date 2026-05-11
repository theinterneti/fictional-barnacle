# Langfuse Canary Checklist

## Pre-flight
- [ ] Prompt version published in Langfuse
- [ ] Label assignment ready (staging first)
- [ ] Rollback target documented
- [ ] Non-critical canary task set selected

## Canary execution
- [ ] Run on staging label only
- [ ] Use representative task mix (feature/bug/refactor/ops)
- [ ] Collect at least N=10 tasks (or agreed minimum)

## Acceptance thresholds
- [ ] No increase in crash/timed_out rate
- [ ] Retry rate not worse than baseline by >X%
- [ ] Blocked rate not worse than baseline by >X%
- [ ] Output contract compliance >= baseline
- [ ] CI pass rate >= baseline

## Promotion gate
- [ ] Reviewer signoff
- [ ] Orchestrator signoff
- [ ] Promote label to production
- [ ] Announce change window complete

## Rollback trigger (instant)
Rollback if any occur:
- [ ] Critical gate bypass observed
- [ ] Major spike in retries/failures
- [ ] Wrong board/task routing
- [ ] False "done" reporting

## Rollback steps
1. Repoint production label to prior version
2. Re-run failed canary sample
3. Confirm metrics normalize
4. Open incident note with root-cause follow-up
