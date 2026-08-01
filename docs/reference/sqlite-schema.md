# SQLite Schema Reference

## Version

The documented baseline uses SQLite schema version **18**.

```sql
PRAGMA user_version;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

## Principal domains

### Campaign

- campaign identity and plan;
- state/version/fault;
- execution attempts;
- cumulative and attempt-local counters;
- terminal events.

### Director

- sessions and turns;
- requests/responses;
- usage;
- decision batches/actions;
- validations and hypotheses;
- evidence/action registries.

`director_action_batches` has exactly one durable source: an App Server turn
or a passive scheduler decision.

### Passive scheduler

- `passive_scheduler_states`;
- `passive_scheduler_decisions`;
- policy/state version, review counters, bounded metrics and reason codes;
- seed/counter RNG lineage and shared action-batch linkage.

### Search

- lanes and revisions;
- checkpoints;
- telemetry windows, including bounded batch/cumulative seed-generation
  aggregates in `metrics_json`;
- candidates;
- candidate pins and immutable snapshots;
- `provenance_json` on retained candidates and immutable snapshots;
- action outcomes.
- `research_lane_policy_identities`, an append-only identity ledger for
  explicitly enabled reviewed proposal-ranking lanes.

### Verification

- queue/jobs;
- independent path results;
- manifests/certification state.

### Scientific memory

- immutable memory snapshots;
- parent/version;
- high-water marks;
- canonical payload/hash;
- size/token estimate;
- trigger.

### Comparisons

- fixtures;
- suites and arms;
- plans/authorizations;
- worker attempts, leases, heartbeats, stop requests;
- inference reservations;
- turns;
- resource samples;
- ratings and cost profiles.

## Inspection

Use SQLite's schema commands against a read-only or backed-up database:

```bash
sqlite3 -readonly <workspace>/results.sqlite3 '.tables'
sqlite3 -readonly <workspace>/results.sqlite3 '.schema research_campaigns'
```

The migration files under `sql/` are authoritative for exact table and column
names.

## WAL caution

The physical main-file hash can change during WAL checkpointing. Scientific
identity uses canonical row/artifact hashes, plan fingerprints, checkpoint
hashes, and export manifests.

## Migration rule

Every migration must:

- be additive where practical;
- preserve historical rows;
- pass Online Backup migration from the previous production version;
- pass integrity and FK checks;
- preserve canonical historical fingerprints.

The v15→v16 migration only adds non-null `provenance_json` columns with the
default `{}`. New retained candidates store schema-v2 provenance; candidate
pinning copies the exact JSON into the immutable M4 snapshot.

The v16→v17 migration adds mode provenance and passive scheduler tables, then
rebuilds only `director_action_batches` so its source may be either a model
turn or scheduler decision. Historical batch IDs and fingerprints are copied
unchanged and verified with `foreign_key_check`.

The v17→v18 migration adds the reviewed proposal-ranking identity ledger and a
campaign/lane lookup index. It is additive, preserves default-lane behavior,
and is validated from an Online Backup snapshot with `integrity_check` and
`foreign_key_check`.

Seed-generation instrumentation requires no schema migration. Its bounded
aggregate is stored in existing telemetry JSON and checkpoint artifacts; it
does not create per-seed SQLite rows.
