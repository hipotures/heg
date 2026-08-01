# ADR 0017: Exact optimization of the opt-in proposal-ranking seam

## Status

Implemented for issue #16; authoritative rollout remains disabled pending the
preregistered performance gates.

## Decision

Optimize only the frozen HEG proposal-ranking seam. Graph-local Stage 2B facts,
matching shapes, and copy-on-write local-risk adjacency may be reused when the
immutable current graph is unchanged. A bounded pool is sent to the reviewed
policy worker in one `stage2a.worker.batch.v1` frame; each returned priority is
still validated, tied by the frozen proposal ID rule, and fails closed on any
protocol/cardinality/finite-value error. The base worker protocol remains
`stage2a.worker.v1`, and the batch extension is bound into ranking checkpoint
identity so Resume cannot cross an implementation seam.

The host keeps the frozen 4–9 lengths, witness cap, budgets, k values,
selector weights, pool/retry/matching limits, source/AST/behavior hashes, lane
RNG contract, scorer authority, M4 authority, and default-disabled activation.
Missing score witness lengths are never converted to scientific zero; the
bounded host context is completed instead. A fixed-width in-memory profile is
emitted only when explicitly requested and never stores per-proposal history.

## Consequences

- Replay and red-team behavior remain compatible with the issue #15 corpus.
- Rejected proposals reuse graph facts; accepted moves, seed restarts, and
  checkpoint restores invalidate the graph cache.
- The worker crosses the process boundary once per pool, reducing framing
  overhead without granting new capabilities or adding fallback behavior.
- Fresh timing is serial and preregistered. A failed gate produces `NO_GO` or
  `INCONCLUSIVE_INFRASTRUCTURE_FAILURE`; it never enables rollout or creates a
  Stage 7R issue.
