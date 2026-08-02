# Issue #21 — Director prompt and artifact retention

## Scope

This change is an implementation-only repair.  It does not change the
scientific target, lane algorithms, proposal-ranking identity, scorer, or M4
authority, and it does not start a paid Director run.

## Prompt boundary

The host keeps the complete continuity object and exact reference registries
for validation, but constructs a separate deterministic model projection.
Only current target/budget, active-lane telemetry, relevant candidate and
checkpoint summaries, verifier status counts, hypotheses, recent
interventions, and aliases are exposed.  Omitted target counts and per-top-
level section byte measurements are persisted in the context-budget report.
Repair requests reuse that same projection and carry validation paths only;
they do not embed a second copy of the full request.

A no-model in-memory history check with 10,000 candidate IDs, 5,000
checkpoint IDs, and 5,000 lane/checkpoint records produced a 10,570-byte
prompt and 65 aliases.  The complete host registry remained private.  The
bounded path completed in under one second in the local interpreter; no
benchmark or paid inference was run.

Snapshot publication applies the same deterministic history bound before the
256 KiB durable snapshot serializer.  Current executable checkpoint identity
remains host-owned; older history is recoverable from SQLite and immutable
artifacts.

## Artifact boundary

Director request/response/wire payloads use one SHA-256 content-addressed raw
object with compatibility hard-links.  Successful transport aliases are
eligible for a 64-turn rolling window; old JSONL payloads are gzip-compressed
before their disposable aliases are removed.  Failed, invalid, repair,
interrupted, and timed-out records remain raw and are never rotated.

Candidate and source artifacts are append-only.  Capsule-level JSON files are
metadata references; raw copies are created only for diagnostics that must be
retained.  `artifacts/source-index.json` maps discovered program/source IDs
to source paths and SHA-256 values.  `artifacts/workspace-artifact-manifest.json`
records non-credential artifact paths, sizes, allocation, hashes, classes, and
deduplicated allocation totals without deleting the first-pass workspace
contents.  The hot turn-completion path refreshes capsules but defers the full
byte/hash inventory to status, export, or explicit migration.

## Existing workspace

The existing `workspace/heg-ranked-001` campaign remains in place.  Its
SQLite database, generated Python files, candidate/checkpoint artifacts,
verifier records, and retained raw diagnostics are not rewritten or deleted
by this implementation task.  A normal operator Resume can run the bounded
projection and non-destructive migration in place.
