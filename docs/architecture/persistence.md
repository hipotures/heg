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

The documented baseline uses schema version 18.

Major domains include:

- campaign and execution attempts;
- campaign/attempt orchestration mode and immutable mode-transition
  provenance;
- Director sessions/turns/decisions/actions/hypotheses;
- passive scheduler state and decisions, including bounded inputs, reason
  codes, validation, and RNG lineage;
- lanes, checkpoints, telemetry, candidates;
- candidate pins and immutable snapshots;
- structured candidate provenance copied into immutable snapshots;
- verification jobs and terminal events;
- scientific-memory snapshots;
- comparison suites/arms/turns/authorizations/worker lifecycle;
- resource accounting;
- ratings and cost profiles.
- reviewed proposal-ranking identities for explicitly enabled lanes, including
  frozen policy/source/schema hashes and worker contract.

See [SQLite Schema](../reference/sqlite-schema.md).

Migration 018 adds `research_lane_policy_identities` and its campaign index.
The table is append-only evidence keyed by lane ID; default lanes have no row.
It is applied after an SQLite Online Backup snapshot and does not rewrite
historical lane/checkpoint records.

## Transaction boundaries

Critical transactions include:

- decision commit before dispatch;
- passive decision, next scheduler state, and shared action batch before
  dispatch;
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

Lane checkpoints have two integrity domains. The scientific checkpoint
SHA-256 covers graph, RNG, algorithm state, provenance, counters, and
parameters. Bounded seed-generation telemetry has its own SHA-256 because its
elapsed-time fields are observational and must not change deterministic
checkpoint identity. Recovery verifies both; either mismatch rejects the
checkpoint.

## Artifact references

Database rows store safe relative paths and SHA-256. Public reports avoid
private runtime paths.
