# SDD Work Items

This directory holds machine-readable work items for the fictional-barnacle SDD
state machine.

- Schema: `.barnacle/work/schema.json`
- Items: `.barnacle/work/items/FB-*.json`
- CLI: `uv run python scripts/workflow_state.py status|next|advance`

The state machine is deliberately conservative: agents may draft and review, but
automation refuses stage jumps that lack required spec, plan, gate, review, or
release metadata evidence.
