# Context-screen failure revalidation

Date: **2026-07-24**

This is a deterministic follow-up to the aborted low-cost context-mode
screen. It made no model call, did not read or copy authentication, did not
start or resume the failed thread, did not execute S1 or S2, and did not run a
search batch. The original failure report, P1 response, rollout, and SQLite
snapshot retained their recorded SHA-256 hashes.

## P1 result

The preserved output remains schema-valid. Its original semantic result is
reported as:

```text
persistent_P1_schema_valid: true
persistent_P1_semantic_validation:
  indeterminate_due_to_validator_contract_mismatch
```

Both disputed references have the same value,
`snapshot-81a7b29a71684fd89f0d907163186711`. That value was present in the
exact post-compaction DirectorStateV2 at both:

```text
$.source_snapshot_id
$.artifact_references[0].id
```

The corrected canonical evidence registry therefore admits the reference.
Offline validation of the unchanged model output has no remaining issue:

```text
persistent_P1_semantic_revalidation: valid
```

The registry SHA-256 is
`690eae8fd1d6083576ea0aefc621f8c2992d8cd357a30ccfe6c651ca96ab8136`.
It is identical after canonical JSON round-trip and reconstruction.

## Canonical registry contract

`prepare_director_state_v2` now creates one registry from the final
post-compaction state. Each entry records an ID, its reviewed reference kinds,
and its exact JSON paths. The Director persists the registry beside each
request and records its artifact reference and SHA-256 in SQLite.

The semantic validator derives `evidence_ids`, candidate IDs, checkpoint IDs,
and hypothesis IDs from that registry. Identifiers present only elsewhere in
SQLite or the original full snapshot are not admitted. Unknown references
retain their exact decision JSON path in the validation issue.

## Incomplete-turn durability

SQLite schema v9 adds an explicit lifecycle and incremental correlation fields
to `app_server_turns`: request ID, authoritative turn ID, item IDs and types,
reasoning-item IDs, latest event sequence and timestamp, turn-start timestamp,
terminal reason, and evidence-registry reference/hash. Final answer and every
usage field remain nullable.

The installed 0.145.0 schema exposes `turn/interrupt` with `threadId` and
`turnId`. On timeout the client now:

1. records `timed_out`;
2. requests `turn/interrupt`;
3. drains bounded stdout/stderr and queued JSONL notifications;
4. upgrades the same row to `aborted` if a late interrupted completion arrives;
5. persists the bounded wire artifact before terminalizing the turn;
6. performs the existing bounded graceful shutdown.

Fake-server regression reproduces the exact preserved P2 turn ID and both
reasoning-item IDs. It retains null final answer and null usage across SQLite
reopen. Duplicate event updates do not create another row.

## Failure terminology

```text
persistent_P2_status: timed_out_after_inference
persistent_arm_completed: false
stateless_arm_completed: false
context_mode_comparison: inconclusive
```

The original P2 database is not retroactively changed because it is preserved
runtime evidence. Schema-v9 deterministic reproduction proves the corrected
future lifecycle shape.

## Verification

The focused evidence-registry, incomplete-turn, timeout/shutdown, late-abort,
nullable-usage, restart-inspection, and no-continuation tests pass. The full
safe suite passed twice (121 tests per pass). `make doctor`, `make check`,
`make benchmark-smoke`, and `make dashboard-smoke` also pass.

An SQLite Online Backup of the preserved v8 failure database had the recorded
SHA-256
`e121468da08aab95237592c2a774633bef6562cb251e67196dc82f29714937af`
and `integrity_check: ok`. Migration was performed only on that temporary
snapshot; it reached `user_version=9` with `integrity_check: ok`, retained two
turn rows, and kept the failed P2 usage fields null. The original failure
report, unchanged P1 response, and complete rollout still hash to the values
recorded below.

No model inference, auth access, app-server runtime start, or graph-search
batch occurred during this repair.

Machine-readable result:
`docs/reports/M6_CONTEXT_SCREEN_FAILURE_REVALIDATION.json`.
