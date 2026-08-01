# ADR 0016: Reviewed proposal-ranking seam remains explicitly opt-in

## Status

Implemented for issue #15; rollout is disabled by default.

## Decision

HEG may execute the frozen `mutation_forge_stage4r_v1` policy only when a lane
explicitly contains that catalog ID in `proposal_ranking`. The host creates and
validates a bounded `stage2b.pool.v1` legal k-switch pool, supplies the frozen
Stage 2B context/proposal fields, and applies only the worker's selected
rewrite. The policy worker runs behind the `stage2a.worker.v1` framed process
boundary with fixed packaged bytes, resource limits, process-group reaping,
and no fallback on failure.

The HEG C++ score remains the host's heuristic score and is used only on the
current/selected graph. The proposal worker cannot call the scorer, database,
filesystem, network, shell, or M4. M4 is still the sole counterexample
certification authority. Ranking identity is persisted with an additive lane
ledger and in checkpoints; Resume rejects any exact-identity mismatch.

## Consequences

- Existing lanes and checkpoints retain their prior behavior when the
  parameter is omitted.
- The parameter is trajectory-breaking and cannot be patched.
- Replay, red-team, migration, process-safety, and faithful E2E gates are
  recorded as evidence; a failed or unavailable gate yields `NO_GO` and does
  not enable a rollout.
- No Stage 7R issue is created by this change.
