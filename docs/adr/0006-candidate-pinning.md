# ADR 0006: Candidate Pinning and Immutable Verification Snapshots

- **Status:** Accepted
- **Date:** 2026-07-26

## Context

A verification action once referenced a candidate that had already disappeared
from retained candidates, stopping the campaign after substantial work.

## Decision

Accepted candidate-target actions transactionally acquire a pin and immutable
candidate snapshot. Pruning/deletion is restricted while references are
active. M4 reads the snapshot.

## Consequences

- Accepted actions cannot lose their graph.
- Verification is reproducible.
- Pins release only after all references are terminal.
- Targets stale before acceptance become `stale_target` and trigger a bounded
  replan instead of a generic campaign fault.

## Rejected alternatives

- Looking up the candidate row only when M4 starts.
- Retaining every generated candidate forever.
