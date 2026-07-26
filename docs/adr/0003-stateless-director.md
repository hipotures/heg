# ADR 0003: Stateless Production Director

- **Status:** Accepted
- **Date:** 2026-07-25

## Context

Persistent App Server threads accumulate server-side history, increase input
tokens, and make scientific context less explicit. A controlled S2/P2
comparison measured lower input usage for stateless A4 while both decisions
remained valid.

## Decision

Use `stateless_turns` as the production default. Each Director turn receives a
bounded complete scientific state. Persistent and compacted modes remain
explicit experimental alternatives.

## Consequences

- Context is auditable and hashable.
- Token growth is bounded by DirectorState/scientific memory.
- Continuity depends on durable state, not hidden conversation memory.
- A fresh thread is created for repair turns and normal cycles.
- The system must keep scientific memory complete enough for good decisions.

## Rejected alternatives

- Persistent thread as default.
- Relying only on App Server conversation compaction.
