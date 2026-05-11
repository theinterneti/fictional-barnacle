# docs/backlog — Discovery Agent Output

This directory is the output of the nightly **Barnacle Discovery Agent** — an autonomous
cron job that surveys TTA, Dukat, Hindsight, and the web to surface the best features
to implement next in fictional-barnacle.

---

## Directory Structure

```
docs/backlog/
  README.md              ← this file
  queue.yaml             ← machine-readable pipeline contract (append-only)
  queue.yaml.dry-run     ← written instead of queue.yaml during testing mode
  stubs/                 ← long-term phase plans (not directly queueable)
  YYYY-MM-DD.md          ← nightly discovery reports (human-readable)
```

---

## queue.yaml Schema

Every entry in `queue` or `backlog` has this shape:

```yaml
- id: "FB-001"                          # Unique ID, never reused
  title: "S12 Persistence AC gaps"      # Human-readable name
  tier: 1                               # 1 = queue tonight, 2/3 = backlog
  score: 9.1                            # Weighted rubric score (0–10)
  horizon: short                        # short | mid | long
  specs: ["S12"]                        # Barnacle spec(s) this addresses
  acs: ["AC-12.03", "AC-12.05"]         # Specific ACs if known
  tta_evidence: "TTA/src/tta/persistence/"  # File path or doc ref in TTA
  dukat_evidence: ""                    # Doc ref in Dukat/ if Dukat-sourced
  barnacle_plan: "plans/ops.md"         # Relevant barnacle technical plan
  estimated_tasks: 3                    # Rough task count for pipeline
  status: queued                        # queued | in_progress | done | skipped
  source: barnacle_gap                  # barnacle_gap | tta_intel | dukat | hindsight | web
  discovered: "2026-05-04"             # Date first surfaced
```

---

## Status Lifecycle

```
queued → in_progress → done
                     → skipped
```

- **queued**: Ready for the pipeline to pick up
- **in_progress**: Pipeline has started work on this item
- **done**: PR merged, CI passing
- **skipped**: Deliberately deferred (reason in notes field)

**This file is append-only.** Never delete or overwrite existing entries.

---

## Rules for Agents

1. **Never modify** entries with `status != queued` — in_progress/done/skipped are frozen
2. **Never add duplicates** — check existing IDs and titles before appending
3. **Check for uncommitted changes** in barnacle before adding new `queued` entries — if
   `git status` shows unstaged changes, log a warning and skip queueing
4. **Stale queue guard** — if more than 3 entries have `status: queued` from a previous
   run, do NOT add new items; notify Adam instead
5. **Testing mode** — write to `queue.yaml.dry-run`, never `queue.yaml`, until graduation
   criteria are met and Adam explicitly enables production mode

---

## Stub Format

Stubs in `stubs/` are long-term phase plans for big ideas that can't be queued directly.
They capture the vision, phases, and prerequisites, and wait for Adam's approval before
Phase 1 gets chunked and queued.

See `stubs/STUB-EXAMPLE.md` for the full template.

---

## Discovery Modes

| Mode | queue.yaml | Notification |
|------|-----------|-------------|
| **Testing** | `queue.yaml.dry-run` only | Chill Telegram: "dry run complete" |
| **Production** | Real `queue.yaml` written | Chill Telegram: "N queued for tonight" |

Graduation from testing → production requires Adam's explicit sign-off after 3
calibration runs where the Tier 1 output feels correct.
