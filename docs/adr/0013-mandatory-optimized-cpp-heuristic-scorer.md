# ADR 0013: Mandatory Optimized C++ Heuristic Scorer

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

The rollout design in ADR 0009 left Python, shadow and C++ heuristic backends
selectable through process environment. A recovered execution attempt could
therefore run the slow Python default even though the optimized worker binary
was present. That changed search throughput without changing the campaign
scientific contract or source revision.

## Decision

Production heuristic scoring has one implementation: the persistent optimized
C++ score worker. Conservative early exit and the fast duplicate key are the
fixed path for new work. The Python count-only heuristic scorer, shadow/audit
mode, backend environment switches and automatic Python fallback are removed.
The versioned worker request carries the target's reviewed cycle lengths, so
all installed targets use the same C++ implementation.

Each lane starts its worker before search. A protocol error, timeout, malformed
response or crash permits one worker restart. A repeated failure fails the lane
closed. Worker failure is never interpreted as an empty witness set.

M4 exact verification remains independent and unchanged. It is not a scoring
backend or fallback.

## Consequences

- A missing or broken score-worker deployment is visible immediately.
- Resume cannot silently select a slower heuristic implementation.
- Runtime provenance describes the fixed C++ implementation and binary.
- Lane memory below 128 MiB is rejected because the worker reservation is
  mandatory.
- Historical backend-selection fields remain only in immutable past evidence.

## Rejected alternatives

- Retaining Python as a hidden compatibility fallback.
- Retaining environment variables that select removed implementations.
- Continuing a lane after the worker fails twice.
- Treating the M4 reference verifier as a heuristic scoring substitute.
