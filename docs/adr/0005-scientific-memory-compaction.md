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

Bounded continuity ledgers keep their source-window limits when merged with a
previous snapshot. Current entries take precedence and older entries fill only
unused capacity. In particular, the exact-verifier window contains the latest
32 outcomes; full older outcomes remain in SQLite and verifier artifacts.
The projection represents completed verifier facts by candidate ID and exact
result, and lane checkpoints by logical checkpoint ID. Durable artifact paths
and integrity hashes are not repeated in model context.

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
