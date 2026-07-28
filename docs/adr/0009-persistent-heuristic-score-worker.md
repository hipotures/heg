# ADR 0009: Persistent Audited Heuristic Score Worker

- **Status:** Superseded by ADR 0013
- **Date:** 2026-07-26

## Context

Per-candidate profiling showed that bounded C16/C32/C64 DFS consumed almost
all search-loop time. SQLite, checkpoints, telemetry and live-frontier
publication were not the limiting components. Starting an executable for
each graph would replace DFS cost with process-startup and serialization cost.

## Decision

An Erdős–Gyárfás lane may own one persistent C++17 count-only worker. Python
passes compact adjacency bitsets through a bounded versioned protocol. The
worker has a separate memory limit and request timeout and returns counts,
completeness, node counts and timing only.

Python is the rollout oracle. Shadow mode compares every result. C++ mode
recounts every proposed global record and periodically audits ordinary
evaluations. A crash, timeout, malformed response or mismatch never becomes a
zero count: the lane retries once and then falls back to Python.

The worker is only a heuristic ranking accelerator. Candidate retention,
immutable snapshots, M4 verification and certification authority are
unchanged.

## Consequences

- One process startup is amortized over a lane.
- The lane resource envelope includes parent and child memory.
- Runtime provenance records the requested backend and worker binary hash.
- Exact accepted/search-record trajectories remain parity-testable.
- Deployment must build or install `sglab-score-worker`.

## Rejected alternatives

- Starting the exact verifier once per candidate.
- Treating a worker timeout as absence of a forbidden cycle.
- Letting C++ establish a global record without a Python recount.
- Incremental witness-set maintenance before the completeness gate passes.
