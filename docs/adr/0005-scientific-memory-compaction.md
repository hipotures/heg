# ADR 0005: Deterministic Scientific-Memory Compaction

- **Status:** Accepted
- **Date:** 2026-07-26

## Context

Long campaigns accumulate telemetry, candidates, outcomes, and prompts. Sending
all history to every model turn is expensive and eventually exceeds context
budgets.

## Decision

Build deterministic, immutable scientific-memory snapshots from durable
records. Use a 24,576-byte soft trigger, 32,768-byte hard limit, periodic
snapshot every five valid cycles, and boundary snapshots at pause/stop/fault/
budget/Resume.

No separate LLM call is required for compaction.

## Consequences

- Full raw history remains available.
- Director input is bounded and reproducible.
- Exact-verifier facts and current executable IDs are non-droppable.
- Old repetitive detail may be aggregated.
- Overflow stops before inference rather than silently truncating truth.

## Rejected alternatives

- Replaying all prompts/events.
- Using only model-generated summaries.
- Deleting old raw records.
