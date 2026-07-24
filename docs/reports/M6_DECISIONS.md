# M6 Active Director Decision Ledger

Entries are append-only.

## D-001 — 2026-07-24 — map onto `sglab`

Decision: implement the Active Director additively under `src/sglab/research`
and preserve the existing `sglab run` engine as a legacy deterministic
baseline. Rationale: the planning package's `gilab` M5 AI modules do not exist
in the authoritative repository.

## D-002 — 2026-07-24 — installed schema wins

Decision: omit environment/dynamic-tool/runtime-root RPC fields that are absent
from the installed 0.145.0 schemas, and enforce those isolation properties
through process flags, configuration overrides, private directories, and
discovered-skill disabling. Rationale: sending example-only fields would
violate the generated protocol contract.

## D-003 — 2026-07-24 — dual schema hashes

Decision: retain exact byte hashes and canonical sorted-JSON hashes for
generated protocol schemas. Rationale: repeated 0.145.0 generation preserves
individual schema bytes but can reorder definitions in the v2 aggregate.

## D-004 — 2026-07-24 — direct additive v1→v7 migration

Decision: preserve every existing v1 table and migrate directly to user
version 7, rather than inventing absent v2–v6 application history. Rationale:
the planning package's schema v6 is not present in the authoritative
repository; pretending otherwise would make recovery and audit claims false.

## D-005 — 2026-07-24 — dependency-free semantic validation

Decision: generate the model output schema from the reviewed Python catalog
and independently enforce strict semantic validation with standard-library
code. Rationale: this keeps the project dependency-free while adding checks
that JSON Schema alone cannot express, including admissible evidence IDs,
current lane versions, algorithm-specific parameters, and global resource
shares.

## D-006 — 2026-07-24 — one bounded process per active lane

Decision: represent each scientific lane as one long-lived spawned Python
process and map its reviewed resource share to bounded duty-cycle time, under
a global active-lane limit and a per-process address-space limit. Rationale:
this supplies real concurrent stateful control without adding a distributed
framework or obscuring deterministic checkpoint boundaries. More internal
workers may only be added after profiling and a benchmark gate.

## D-007 — 2026-07-24 — immutable order within a lane

Decision: exclude graph order from hot patches and forks while allowing the
Director to choose order when starting a new lane. Rationale: changing order
cannot preserve the current graph state; requiring a new lane keeps patch
semantics honest and checkpoint replay exact.

## D-008 — 2026-07-24 — snapshots pin admissible checkpoints

Decision: pin every checkpoint ID exposed as admissible evidence before
starting its Director turn, using the separately bounded pinned-checkpoint
retention. Rationale: ordinary micro-batch rotation must not invalidate an
exact fork/restart reference while app-server inference is still running.

## D-009 — 2026-07-24 — inference wait remains an event pump

Decision: await the persistent provider in an asyncio task while repeatedly
draining bounded lane queues, persisting telemetry, applying already committed
actions, and evaluating completed interventions. Rationale: worker processes
search independently, but an undrained bounded event queue would eventually
back-pressure them and violate the active-control requirement.

## D-010 — 2026-07-24 — retain graph bodies outside Director snapshots

Decision: store at most 256 ordinary retained candidates as hashed graph6
artifacts and database rows, while exposing only stable IDs and bounded
structural summaries to the Director. Rationale: the model may choose among
admissible scientific objects but must never supply graph bodies or file paths
to the verifier.

## D-011 — 2026-07-24 — M4 manifest is the sole success capability

Decision: only the bounded production M4 broker may call the terminal
transaction, and only after re-reading a persisted manifest containing both
complete expected independent implementations. Rationale: no Director action
type includes campaign success, and heuristic scores, prose, single-verifier
results, timeouts, malformed output, and disagreements remain non-terminal.

## D-012 — 2026-07-24 — checkpoint precedes matching telemetry

Decision: after each micro-batch, enqueue and persist its exact checkpoint
before the aggregate telemetry window for that same high-water. Rationale: a
crash between the old telemetry-first events could leave SQLite one batch
ahead of durable RNG state and force ambiguous replay.

## D-013 — 2026-07-24 — export database only through Online Backup

Decision: create campaign export databases with SQLite Online Backup API into
a temporary snapshot, run `PRAGMA integrity_check`, and only then add them to
the bounded deterministic archive. Rationale: copying the main file can omit
committed WAL state and produce a scientifically incomplete bundle.
