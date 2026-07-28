# No-LLM Passive Scheduler Acceptance

Date: 2026-07-28
Issue: #13

## Scope

This gate covers the versioned `balanced_v1` scheduler, schema-v17
persistence, no-credential startup, deterministic replay, shared
validation/dispatch, pause/Resume/stop continuity, mode provenance,
dashboard/API status, and unchanged M4 certification authority.

## Deterministic evidence

- Fixed campaign state, snapshot, seed, and policy produce identical reviewed
  action batches.
- The initial portfolio is bounded by `max_active_lanes` and draws only from
  random restart, simulated annealing, ILS, and ILS-tabu.
- Stagnation uses persisted per-lane counters and prefers a valid checkpoint.
- Review scheduling is evaluation-boundary based; wall-clock time is not a
  scientific decision input.
- Scheduler state and SHA-256 counter RNG lineage are committed atomically with
  the shared action batch.

## Runtime evidence

The bounded passive smoke must show:

- live lane evaluations;
- durable checkpoints;
- at least one passive scheduler decision;
- zero App Server sessions and turns;
- zero server tokens;
- Pause followed by a new Resume attempt and Stop;
- restored scheduler state/RNG lineage.

## Verification commands

All required gates passed against the final tree:

- `make doctor` — passed;
- `make test` — 316 tests passed;
- `make check` — passed;
- `make benchmark-smoke` — passed;
- `make dashboard-smoke` — passed.

The HTTP-dependent test and dashboard gates were repeated with loopback socket
access because the restricted evidence-worker sandbox denies `AF_INET`.
Focused passive tests also passed 9/9, and the protected dashboard/passive API
set passed 16/16.
