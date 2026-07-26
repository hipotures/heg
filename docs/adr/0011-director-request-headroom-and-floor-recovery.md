# ADR 0011: Director Request Headroom and Safe-Floor Recovery

- **Status:** Superseded in part by ADR 0012
- **Date:** 2026-07-26

## Context

Long-running campaigns can remain just below the `DirectorStateV2` byte limit
while the complete request exceeds its client-owned token gate. A calculated
request-level state target may also land below the irreducible projection that
contains exact-verifier facts and current executable IDs. Treating that one
unattainable target as proof that no reduction is possible caused recurring
fail-closed stops.

The outer prompt also repeated the allowed action space and a growing list of
durable reserved action IDs already enforced by authoritative validation.

## Decision

- Target 15,000 estimated client-owned tokens before applying the 16,000-token
  hard gate.
- If the ideal state-byte target is infeasible, deterministically search for
  the tightest feasible safe state.
- Never remove exact-verifier facts or current executable IDs to meet either
  target.
- Refer to the action space in `DirectorStateV2` instead of copying it into the
  outer prompt.
- Submit the reserved-action-ID count and namespace rule, while leaving exact
  collision membership to durable workspace validation.
- Persist the requested targets, floor-search targets, recovered limit, and
  final soft/hard-gate measurements in the context-budget artifact.

## Consequences

- A single impossible intermediate target no longer causes a false terminal
  context fault.
- The hard gate remains fail-closed and is checked before inference.
- Prompt size no longer grows linearly with the recent reserved-action list.
- Action-ID collisions remain rejected transactionally.
- Exact-verifier truth and current executable targets remain reproducible.

## Rejected alternatives

- Raising or disabling the 16,000-token hard gate.
- Dropping current executable IDs or exact-verifier outcomes.
- Treating a failed ideal compaction target as proof that no smaller safe
  projection exists.
- Trusting the model to avoid action-ID collisions without durable validation.
