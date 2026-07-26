# Persistence

## Source of truth

Each workspace owns one SQLite database in WAL mode plus filesystem artifacts.

SQLite stores identity, lifecycle, relationships, counters, hashes, and
bounded metadata. Large graphs, checkpoints, responses, rollouts, reports, and
certificates remain files indexed by SQLite.

## Single-writer model

The coordinator/store is the single authoritative writer. Worker processes
emit bounded events. This avoids cross-process SQLite write contention and
keeps action/checkpoint ordering explicit.

## Current schema

The documented baseline uses schema version 16.

Major domains include:

- campaign and execution attempts;
- Director sessions/turns/decisions/actions/hypotheses;
- lanes, checkpoints, telemetry, candidates;
- candidate pins and immutable snapshots;
- structured candidate provenance copied into immutable snapshots;
- verification jobs and terminal events;
- scientific-memory snapshots;
- comparison suites/arms/turns/authorizations/worker lifecycle;
- resource accounting;
- ratings and cost profiles.

See [SQLite Schema](../reference/sqlite-schema.md).

## Transaction boundaries

Critical transactions include:

- decision commit before dispatch;
- action ID/idempotency validation;
- candidate pin/snapshot plus accepted targeted action;
- inference reservation before model start;
- terminal job/attempt state;
- lease acquisition and release.

## Migrations

- additive and versioned;
- tested from previous production schema;
- run first on SQLite Online Backup;
- integrity and foreign-key checked;
- historical canonical records/fingerprints preserved.

## Hashes

Use canonical content hashes for scientific identity. Do not use the physical
SQLite main-file hash while WAL mode is active.

## Artifact references

Database rows store safe relative paths and SHA-256. Public reports avoid
private runtime paths.
