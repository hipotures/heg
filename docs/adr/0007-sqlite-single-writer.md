# ADR 0007: Workspace-Local SQLite With a Single Writer

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

Concurrent lanes and verifier processes produce frequent events. Multiple
direct SQLite writers complicate ordering, recovery, and WAL contention.

## Decision

Each workspace owns one authoritative SQLite database. The coordinator/store is
the single writer; workers send bounded events. Large artifacts remain files
indexed by SQLite.

## Consequences

- Durable ordering boundaries are explicit.
- Recovery can align telemetry with checkpoints.
- Workspace backup/export is portable.
- Worker queues must be bounded.
- Online Backup is required for consistent live copies.

## Rejected alternatives

- One database per lane/run.
- Global database across workspaces.
- Multi-writer worker access.
- JSON files as primary relational state.
