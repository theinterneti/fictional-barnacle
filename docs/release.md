# Release Discipline

fictional-barnacle uses local-first release checks so agents cannot claim a
professional change is ready without deterministic evidence.

## Version policy

- The application version lives in `pyproject.toml` under `[project].version`.
- Versions use SemVer: `MAJOR.MINOR.PATCH`.
- While the project is pre-1.0:
  - `0.MINOR.0` is for feature/spec waves or user-visible capability changes.
  - `0.MINOR.PATCH` is for fixes, tooling, docs, and release hygiene.
- Prompt template versions are separate from application versions.
- Spec numbers are governance identifiers, not release versions.

## Changelog policy

Every release-relevant PR needs either:

1. a non-placeholder bullet under `CHANGELOG.md` → `[Unreleased]`, or
2. a documented no-changelog rationale in the PR body.

Local automation enforces the common case:

```bash
make changelog-check
```

Release-relevant paths include `src/`, `scripts/`, `specs/`, `plans/`,
`prompts/`, `migrations/`, `tests/`, `Makefile`, `pyproject.toml`, and `uv.lock`.
Pure `docs/` changes do not require a changelog bullet by default.

## Release readiness

Before cutting a tag, move relevant `[Unreleased]` bullets under a versioned
section:

```markdown
## [0.2.0] - YYYY-MM-DD
```

Then run:

```bash
make release-check
```

The release check verifies:

- `pyproject.toml` version is valid SemVer.
- `CHANGELOG.md` contains a section for the current version.
- The normal local gate passes.

## Dry run

Use:

```bash
make release-dry-run
```

This prints current changelog/version status without creating tags or mutating
files. Tag creation and GitHub release publication remain deliberate human steps
until the release workflow is automated in a later phase.
