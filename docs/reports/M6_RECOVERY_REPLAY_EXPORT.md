# M6.6 Recovery, Replay, and Export

Date: 2026-07-24

## Result

The offline recovery/replay/export milestone passes. It proves deterministic
lane recovery and safe data packaging. Actual Codex thread resume still needs
the authenticated live gate; M6 is not complete.

## Recovery sequence

`CampaignRecovery` performs:

1. `PRAGMA integrity_check`;
2. durable interruption status for incomplete app-server turns and sessions;
3. requeue of M4 jobs interrupted while running;
4. safe-path and SHA-256 verification of every active lane checkpoint;
5. exact restoration of graph, best graph, RNG, tabu, algorithm counter,
   stagnation, lane version, parameters, and telemetry high-water;
6. process-generation increment;
7. preserved paused state;
8. delivery of accepted actions only when no durable outcome exists;
9. persisted app-server thread-ID lookup for production resume;
10. a caller-generated recovery trigger/snapshot before the next decision.

Corrupt/missing/stale checkpoints fail the lane rather than silently reseeding
it. Timeouts and interrupted verification remain unknown/retryable.

## Crash-consistent worker boundary

Each completed micro-batch now emits its exact checkpoint before its telemetry
aggregate. Both share the same high-water. This removes the former crash
window in which metrics could be durable while the matching RNG state was not.

The recovery integration starts a real lane, persists multiple batches,
destroys the manager/store, opens a fresh store and manager, and restores the
lane. The first recovery event has the exact prior checkpoint ID, hash, and
high-water; only a later batch advances it. `process_generation` changes from
zero to one.

## Replay

- Decision replay revalidates the recorded structured response against the
  current catalog/context and may create a synthetic durable turn that uses
  the same transactional decision-commit path.
- Scientific replay restores the lane kernel from a hashed checkpoint and
  re-executes 1–100 bounded micro-batches. Repeated runs reproduce graph, RNG,
  checkpoint ID, accepted/legal/improvement counts, score, and high-water.
  Wall-clock throughput is intentionally excluded from equality.
- Artifact audit re-hashes exact snapshot files and canonical recorded
  Director responses before accepting them for replay.

## Reproducibility export

- live SQLite state is snapshotted only with Online Backup API;
- the snapshot must pass `PRAGMA integrity_check`;
- WAL/SHM files and the live database file are not copied;
- input is limited to 10,000 files and 512 MiB by default;
- symlinks, recursive exports, `auth.json`, `.codex`, and private Codex/SQLite
  homes are excluded;
- every included file is hashed in `manifest.json`;
- ZIP timestamps and modes are deterministic;
- output replacement is atomic.

The export test confirms the snapshot contains committed campaign data and
that a deliberately planted `auth.json` is absent.

## Focused gate

```text
Ran 4 tests in 0.323s
OK
wall_seconds=0.41s
user_seconds=0.35s
system_seconds=0.07s
cpu_percent=100%
```

## Regression gate

`make test`: 69 tests passed in 12.665 seconds.

`make check`: passed.

## Pending live/reliability evidence

- kill and restart the full application during a real authenticated Director
  turn;
- resume the identical app-server thread and verify saved rollout isolation;
- recovery snapshot before the resumed Director acts;
- bounded outage/retry/paused-fault behavior;
- two-hour database/archive/RSS/queue plateau soak.
