# Skill: validate-sdd

## Purpose
Run the SDD (Spec-Driven Development) validators to check spec and plan quality.

## When to invoke
- Before committing changes to specs or plans
- After creating or modifying any spec (specs/*.md) or plan (plans/*.md)
- When asked to "validate", "check specs", or "check plans"

## How to invoke

Run these commands:

```bash
cd /home/theinterneti/Repos/fictional-barnacle
make validate-all
```

Or individually:
```bash
make validate-specs   # Check spec quality, dependencies, Gherkin coverage
make validate-plans   # Check plan quality, cross-references, spec coverage
```

## What to check in output
- ❌ errors = MUST fix before committing
- ⚠️ warnings = review and fix if reasonable
- Quality Scorecard = track percentages over time (aim for >80% across metrics)
