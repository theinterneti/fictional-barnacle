# TTA — GitHub Copilot Instructions

## Project

**Therapeutic Text Adventure (TTA)** — AI-powered narrative game where players make
meaningful choices in richly simulated worlds.

This repository follows **Spec-Driven Development (SDD)**. All code is generated from,
reviewed against, and validated by written specifications.

## Methodology

1. **Specify** → Behavior-focused functional specs (no implementation details)
2. **Plan** → Technical direction, stack, architecture constraints
3. **Tasks** → Small, reviewable, testable chunks
4. **Implement & Validate** → Code against specs, fix deviations

## Rules

- **Specs are source of truth** — if code contradicts a spec, the code is wrong
- **Behavior over implementation** — specs describe *what*, not *how*
- **OSS-first** — use existing frameworks before building custom solutions
- **Sleek** — minimal custom implementation surface area
- Read the relevant spec before working on any feature
- Reference spec acceptance criteria when writing tests

## Spec Index

See `specs/README.md` for the complete spec inventory and dependency graph.

## Quality Gate

```bash
# TBD — will be defined during Plan phase
```

## Conventions

- Python 3.12+
- Conventional Commits
- Specs use the template at `specs/TEMPLATE.md`
