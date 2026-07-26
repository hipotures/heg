# M6 live-frontier publication report

Date: 2026-07-26

## Acceptance contract

- publish from the current accepted graph and already computed score;
- do not call the scorer or construct a full checkpoint;
- publish at most once per second during a long batch;
- atomically overwrite one bounded file per lane;
- do not create preview history, SQLite rows, logs, or scientific events;
- prefer the preview in the graph view and fall back to a durable checkpoint;
- report evaluation, checkpoint, SQLite, event, and preview costs separately.

## Implementation result

The worker's one-second publisher reads an atomic tuple containing the current
`BitGraph`, `ScoreResult`, candidate ID, and high-water counter. It creates a
minimal SHA-256-protected payload and sends a non-important bounded-queue
event. The coordinator overwrites:

```text
lane-checkpoints/live-frontier-<lane-hash>.json
```

The file is limited to 64 KiB by both producer and reader contracts. It is not
a Resume checkpoint and is not persisted in SQLite. Queue pressure may drop a
preview without affecting search or durability.

Focused tests prove that publication succeeds while both `_score()` and
`checkpoint()` are patched to fail, that two publications leave exactly one
file containing the newest preview, and that the visualization prefers a
valid preview but falls back when it is corrupt.

## Stage benchmark

Command:

```text
PYTHONPATH=src python3 -c 'from sglab.benchmark import microbenchmark; ...'
```

Workload: 10 samples, deterministic random-restart lane, `n=20`,
`witness_cap=16`, ten candidates per evaluation batch. SQLite uses a fresh
temporary database; live publication uses a fresh temporary file.

| Stage | Median | p95 |
|---|---:|---:|
| candidate evaluation, 10 candidates | 5.672 ms | 7.112 ms |
| checkpoint serialization | 0.818 ms | 1.265 ms |
| SQLite commit, 100 rows | 0.066 ms | 0.105 ms |
| telemetry/event bounded enqueue | 0.001 ms | 0.046 ms |
| live-frontier payload plus atomic publication | 0.097 ms | 0.280 ms |

The benchmark operations are now part of `microbenchmark()` and therefore of
`make benchmark-smoke`, rather than existing only as a one-off measurement.
