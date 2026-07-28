# Backup and Export

## SQLite WAL rule

Do not use the physical main-database file hash as a scientific identity while
a dashboard or coordinator is attached in WAL mode.

The main file may change during checkpointing even when logical scientific
rows are unchanged.

## Consistent backup

Use SQLite Online Backup or the project's export command.

```bash
sglab research-campaign export   --workspace <workspace>   --campaign-id <campaign-id>   --output ./campaign.zip
```

Exports should:

- use a consistent SQLite snapshot;
- run integrity checks;
- preserve deterministic ZIP metadata where supported;
- include required scientific artifacts and hashes;
- exclude credentials and private runtime homes;
- enforce file/byte bounds.

## What to preserve

- plan and fingerprint;
- campaign/attempt records;
- current mode, per-attempt mode transitions, and contract fingerprints;
- passive scheduler state/decisions, reason codes, and RNG lineage;
- scientific-memory snapshots;
- lane checkpoints and hashes;
- retained candidate snapshots;
- verifier manifests/reports;
- Director request/response hashes;
- implementation commit;
- environment/tool metadata;
- public report.

## Workspace clone

For a comparison or migration:

1. stop mutating processes or use Online Backup;
2. create a new marked destination workspace;
3. copy only required safe scientific artifacts;
4. migrate destination schema;
5. run integrity and FK checks;
6. preserve source hashes;
7. never copy auth or private Codex homes.

## Restore test

Periodically verify that an export can reconstruct:

- campaign identity;
- attempts;
- scientific memory;
- checkpoints;
- candidates;
- M4 outcomes;
- cumulative counters.
- the active mode and passive scheduler continuation state.
