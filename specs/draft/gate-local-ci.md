# L1 Spec: make gate — Local CI Gate

**Status**: Draft
**Layer**: L1 (Spec Author — free model, manager-coordinated)

## Problem

Developers currently push to GitHub and wait ~90 seconds for CI to report
formatting/linting/test failures. This wastes Actions minutes and creates a
"push → fail → fix → push → fail" loop. The fix should be caught locally
before remote CI ever sees it.

## Scope

**In**: Two Makefile targets (`gate`, `gate-full`) that run the full local
CI pipeline: formatting check, linting, type checking, AC traceability
validation, spec/plan validation, and unit tests.

**Out**: Replacing GitHub CI. GitHub CI remains as backup confirmation.
Integration test orchestration (already covered by `test-integration`).
Docker/podman service management.

## Architecture Impact

- `Makefile`: add `gate` and `gate-full` targets, register in `.PHONY`
- No code changes. No spec changes. No new dependencies.

## ACs

| AC | Description | Testable? |
|----|-------------|-----------|
| AC-gate-01 | `make gate` runs check-format → lint → trace → validate-specs → validate-plans → test-unit, exits 0 on success | Yes: `make gate` in clean repo |
| AC-gate-02 | `make gate` exits non-zero if any step fails | Yes: introduce a lint error, run gate |
| AC-gate-03 | `make gate-full` includes test-integration after gate | Yes: `make gate-full` with test services |
| AC-gate-04 | Targets appear in `make help` output | Yes: `make help | grep gate` |

## Dependencies

- Existing Makefile targets: `check-format`, `lint`, `trace`, `validate-specs`, `validate-plans`, `test-unit`, `test-integration`
- `make help` self-documenting convention (already in Makefile)
