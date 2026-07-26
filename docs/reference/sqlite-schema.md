# SQLite Schema Reference

## Version

The documented baseline uses SQLite schema version **15**.

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

### Search

- lanes and revisions;
- checkpoints;
- telemetry windows;
- candidates;
- candidate pins and immutable snapshots;
- action outcomes.

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
