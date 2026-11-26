# AGENTS.md — Structural Graph Conjecture Lab

This file is the entry point for Codex and other coding agents working in this
repository.

## Mission

Maintain a reproducible, bounded graph-research system in which:

- one durable campaign represents one scientific experiment;
- every process start or Resume creates an immutable execution attempt;
- the AI Director may choose only reviewed actions;
- invalid decisions are persisted and never executed;
- search results remain heuristic until the M4 verifier certifies them;
- raw scientific history is preserved even when Director context is compacted;
- workspaces remain isolated unless an explicit import or fork is requested.

## Required reading by change type

| Change area | Read before editing |
|---|---|
| Campaign lifecycle or Resume | `docs/architecture/campaign-runtime.md`, `docs/architecture/invariants.md`, `docs/codex/modifying-resume.md` |
| Director prompt/schema/validation | `docs/architecture/director-loop.md`, `docs/reference/director-schema.md`, `docs/codex/adding-a-director-field.md` |
| Candidate retention or verification | `docs/architecture/candidate-lifecycle.md`, `docs/architecture/m4-verification.md` |
| Search lanes/checkpoints | `docs/architecture/search-lanes.md`, `docs/reference/state-machines.md` |
| SQLite migration | `docs/architecture/persistence.md`, `docs/codex/database-migrations.md` |
| Dashboard/API | `docs/architecture/web-control-plane.md`, `docs/codex/adding-a-dashboard-view.md` |
| App Server integration | `docs/architecture/app-server-integration.md`, `docs/operator/authentication.md` |
| Comparison system | `docs/architecture/comparison-system.md`, `docs/reference/cli-comparisons.md` |

## Non-negotiable invariants

1. A Director decision is durably committed before any action is dispatched.
2. Invalid, stale, schema-invalid, or semantic-invalid actions are never
   executed.
3. M4 is the only authority that may certify a counterexample.
4. A candidate targeted by an accepted action is pinned and represented by an
   immutable snapshot.
5. Resume keeps the campaign ID and creates a new execution attempt.
6. Resume never silently changes the target, Director model, effort, context
   mode, or scientific prompt contract.
7. Distinct fresh campaigns do not inherit scientific knowledge automatically.
8. Scientific-memory compaction never deletes raw history and never drops
   exact-verifier facts or current executable IDs.
9. Credential contents never enter SQLite, reports, logs, manifests, prompts,
   or browser responses.
10. A byte-quota failure may be emitted only when the measured numeric
    inequality is true.
11. No model tool, shell command, file path, or executable is accepted from a
    Director response.
12. Historical runtime records, fingerprints, and evidence artifacts are
    append-only evidence.

The detailed matrix is in `docs/architecture/invariants.md`.

## Worktree discipline

- Inspect `git status` before editing.
- Preserve unrelated user files.
- Do not reset, clean, or overwrite existing work unless explicitly requested.
- Do not rewrite historical workspace data to make a test pass.
- Use temporary or copied workspaces for migration and recovery tests.
- Treat `docs/reports/` as evidence; do not silently rewrite old reports.

## Database changes

- Use additive, versioned migrations.
- Test the previous production schema to the new schema through SQLite Online
  Backup.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
- Preserve historical fingerprints and canonical hashes.
- Never use the physical SQLite main-file hash as a scientific identity while
  WAL mode is active.

## Runtime testing

Prefer this order:

1. focused unit tests;
2. deterministic fake/replay state-machine tests;
3. short real-kernel tests without model access;
4. loopback HTTP and Playwright checks;
5. authenticated tests only after an exact authorization boundary.

Never consume real auth or model turns when a deterministic test can prove the
same property.

## Standard gates

```bash
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

Also run focused tests, migration checks, loopback HTTP tests, and process
orphan checks appropriate to the changed subsystem.

## Documentation obligations

A behavior change must update:

- the relevant user or operator workflow;
- the architecture document;
- the reference document;
- `docs/architecture/invariants.md` when an invariant changes;
- an ADR when the change introduces a durable architectural decision;
- `docs/IMPLEMENTATION_STATUS.md` as the chronological ledger;
- a report under `docs/reports/` when the change has an explicit acceptance
  gate.

Do not document future behavior as implemented.

# GitHub access

- After each completed cycle of changes, commit and push to the current branch's upstream. Never force-push; if the push is rejected, stop and report.
- For any GitHub repository, issue, pull request, commit, release, or `github.com` URL, use the GitHub CLI (`gh`) as the primary interface.
- Do not use web search or a browser to read GitHub content when `gh` can access it.
- For GitHub issues, prefer the REST API via:
  `gh api repos/<owner>/<repo>/issues/<number> --jq '"# " + .title + "\n\n" + .body'`
- If issue comments are needed, fetch them separately with:
  `gh api repos/<owner>/<repo>/issues/<number>/comments --jq '.[].body'`
- Do not use the comments endpoint as a substitute for reading the issue body.
- Avoid `gh issue view` when it fails because of deprecated Projects Classic GraphQL fields; fall back to `gh api`.
- For pull requests, use `gh pr view` when it works; otherwise use the corresponding `gh api` REST endpoint.
- For repository or API data, use `gh repo view` or `gh api`.
- Use web access for GitHub only if `gh` cannot retrieve the required information, and state why.
