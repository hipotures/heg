# Campaign Scientific Memory

Scientific memory is a deterministic, bounded projection of durable campaign
records for the next stateless Director turn. It is not Codex conversation
compaction. Full raw records remain in SQLite and artifact storage.

## Default policy

- soft trigger: 24,576 canonical UTF-8 bytes;
- hard limit: 32,768 canonical UTF-8 bytes;
- periodic snapshot: every 5 completed valid scientific cycles;
- terminal snapshot: pause, stop, deadline/budget exhaustion, fault, and
  Resume;
- pre-inference compaction whenever the projected state would exceed the hard
  limit.

The exact canonical JSON byte count is authoritative. Estimated client-owned
tokens are persisted only for observability. Campaign plans fingerprint:

- `scientific_state_soft_limit_bytes`;
- `scientific_state_hard_limit_bytes`;
- `scientific_snapshot_interval_cycles`.

## Immutable snapshots

Schema v15 stores versioned immutable snapshots with:

- memory snapshot and campaign IDs;
- monotonically increasing version and optional parent;
- source high-water marks and source record counts;
- canonical JSON, byte size, estimated token count, and SHA-256;
- creation trigger and timestamp.

Every Director turn and execution attempt records the memory snapshot it used.
Resume starts from the latest terminal snapshot and bounded deltas after its
high-water marks rather than replaying every prompt or raw event.

## Preserved scientific content

The deterministic projection retains:

- the current hypothesis ledger and latest valid assessment;
- certified facts and all exact-verifier outcomes;
- retained/rejected candidate summaries and reasons;
- best-score progression;
- current executable candidate and checkpoint IDs;
- active/useful checkpoint and lane summaries;
- explored graph families, orders, and parameter regions;
- stagnant/exhausted basins and operator-yield summaries;
- unresolved scientific questions;
- recent outcomes required for continuity;
- infrastructure faults explicitly separated from scientific negative
  evidence;
- current attempt resources and checkpoint-restore results.

Old repetitive telemetry, equivalent parameter configurations, non-record
candidates, detailed per-evaluation traces, redundant ancestry, and old
operational events may be aggregated or bounded.

## Hard-size behavior

The compactor first emits the complete bounded projection and then applies a
documented deterministic secondary reduction of old/redundant detail. It
never silently drops exact-verifier facts or current executable IDs. If those
non-droppable facts cannot fit, the runner fails before inference with
`scientific_state_overflow`; no invalid or silently truncated state reaches
the Director.

Canonical input order and reduction rules make hashes reproducible for the
same source high-water marks. The source rows and artifacts are never deleted
by compaction.
