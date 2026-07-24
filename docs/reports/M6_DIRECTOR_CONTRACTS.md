# M6 Director Contracts and Schema-v7 Report

Status: **offline milestone complete**

Date: **2026-07-24**

## Additive migration

The authoritative database migrates directly from the repository's real
schema v1 to user version 7. The migration leaves all eight existing tables
and their semantics unchanged and adds fourteen tables:

- campaign state and terminal events;
- immutable Director snapshots and coalesced triggers;
- persisted app-server sessions and turns;
- versioned lanes, revisions, and bounded telemetry windows;
- decision batches, individual actions, and measured outcomes;
- hypothesis revisions;
- bounded M4 verification jobs.

The executable migration is `ACTIVE_DIRECTOR_SCHEMA_SQL` in
`src/sglab/db.py`; `sql/007_active_director.sql` records its reviewed role and
application policy. Fresh databases run 0→1→7 in order. Existing databases
newer than 7 remain rejected.

Migration testing obeyed the SQLite safety rule:

1. `workspace/results.sqlite3` was snapshotted with SQLite `.backup`;
2. only the temporary snapshot was opened by the new code;
3. the snapshot migrated from user version 1 to 7;
4. it contained 22 tables and passed `PRAGMA integrity_check` with `ok`;
5. the original database remained at user version 1.

The unit migration test independently uses `sqlite3.Connection.backup()` and
also proves that the original v1 source is untouched.

## Durable Director protocol

The new control-plane modules provide:

- a reviewed action and parameter catalog narrowed to the two algorithms and
  three graph families actually implemented;
- an exact generated output schema for all ten allowed action variants;
- strict unknown-field rejection, so model output cannot carry shell, Python,
  SQL, executable, path, URL, verifier, or target mutations;
- bounded canonical JSON for snapshots and decisions;
- evidence-ID allowlists;
- expected-lane-version validation with stale rejection;
- bounded resource shares, leases, evaluation windows, and review triggers;
- per-action idempotency keys;
- one and only one repair turn over the same committed snapshot;
- private mode-0600 request, response, and bounded wire artifacts;
- raw and normalized token usage without double counting;
- a replay provider that revalidates recorded decisions and makes no model
  call.

Validated decisions are not silently rebased. `ResearchStore` rechecks the
durable campaign and lane versions in one `BEGIN IMMEDIATE` transaction,
records accepted and stale actions, increments campaign state optimistically,
and prevents duplicated turn completion. All mutations are restricted to the
store's owning thread, preserving the one-writer rule.

## Verification

- Focused schema/migration/protocol/store/Director tests: 10 passed.
- Full repository suite: 52 passed in 11.031 seconds.
- `make check`: passed.
- Real v1 database snapshot migration: user version 7, integrity `ok`.

This milestone does not change the candidate-evaluation loop or search
throughput, so no performance superiority or new benchmark result is claimed.
The baseline benchmark-smoke result remains applicable. Live app-server model
acceptance of the production decision schema is still part of the explicit
authentication gate recorded in `M6_APP_SERVER_PREFLIGHT.md`.
