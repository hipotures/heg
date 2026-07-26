# Codex Development Guide

Codex should use the same architecture documentation as human maintainers.
This directory adds change procedures, not a second competing architecture.

## Before any change

1. Read root `AGENTS.md`.
2. Read the relevant architecture page.
3. Read [System Invariants](../architecture/invariants.md).
4. Inspect current code, migrations, tests, and Git state.
5. Identify historical workspaces/reports that must remain immutable.
6. Prefer deterministic tests before authenticated/model tests.

## Guides

- [Change map](change-map.md)
- [Testing matrix](testing-matrix.md)
- [Database migrations](database-migrations.md)
- [Adding a Director action](adding-an-action.md)
- [Adding a Director field](adding-a-director-field.md)
- [Adding a dashboard view](adding-a-dashboard-view.md)
- [Modifying Resume](modifying-resume.md)
- [Debugging production campaigns](debugging-production-campaigns.md)
- [Capturing screenshots](capturing-screenshots.md)

## Completion standard

A change is not complete when one code path works. It is complete when:

- persistence;
- recovery;
- CLI/API/UI;
- schema/semantic validation;
- security boundaries;
- tests;
- architecture/reference/user/operator docs;
- evidence report where needed

agree on the same contract.
