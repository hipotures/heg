# ADR 0001: Workspace Isolation

- **Status:** Accepted
- **Date:** 2026-07-26

## Context

Research campaigns produce databases, checkpoints, candidates, verifier
artifacts, model turns, comparisons, and exports. Implicit cross-workspace
inheritance would make experiments difficult to reproduce and compare.

## Decision

A workspace is an isolated source-of-truth boundary. Campaigns do not
automatically see another workspace's history. Cross-workspace movement
requires an explicit import, clone, comparison fixture, export/restore, or
future fork operation.

## Consequences

- Clean-room experiments are possible.
- Independent campaigns can be compared from matched initial states.
- A new workspace starts without prior scientific knowledge.
- Resume belongs inside the same campaign/workspace.
- Operators must deliberately import evidence when continuity across
  workspaces is desired.

## Rejected alternatives

- Global database shared by all experiments.
- Automatic discovery and import of nearby workspace data.
