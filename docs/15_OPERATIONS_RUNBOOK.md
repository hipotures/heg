# Operations Runbook

## Pre-run checklist

1. Confirm current target status.
2. Run `make doctor`.
3. Check free disk and RAM.
4. Confirm cgroup limits.
5. Record git status and commit.
6. Run benchmark calibration after code or compiler changes.
7. Start with a short smoke run.

## Starting

```bash
sglab run \
  --target erdos_gyarfas \
  --order 32 \
  --mode cubic_first \
  --algorithm simulated_annealing \
  --workers 12 \
  --seed 1 \
  --time-limit 24h \
  --workspace ./workspace
```

This command is a required final interface; the starter scaffold does not implement it yet.

## Monitoring

Preferred local access:

```bash
sglab serve --workspace ./workspace --host 127.0.0.1 --port 8080
```

Remote access through SSH tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 server
```

## Pause and resume

Pause must:

- stop generating new candidates;
- finish or checkpoint safe in-flight work;
- flush metrics;
- preserve worker RNG states when practical.

Resume must not create a new run ID unless explicitly requested.

## Controlled stop

- request stop through CLI or HTTP;
- stop new tasks;
- checkpoint;
- wait for bounded grace period;
- terminate remaining process groups;
- mark run status accurately.

## Crash recovery

On startup:

- inspect last state;
- verify checkpoint hashes;
- mark orphaned prior process IDs as dead;
- recover SQLite WAL;
- offer resume or finalize-as-crashed;
- never overwrite the previous run directory.

## Incident: memory pressure

1. pause search workers;
2. cancel the largest exact task;
3. WAL checkpoint;
4. inspect per-process RSS;
5. lower exact-verifier concurrency;
6. resume with a documented configuration change.

## Incident: verifier disagreement

1. freeze the candidate artifact;
2. stop public claims;
3. run clean standalone verification;
4. reduce to a smaller witness if possible;
5. inspect definition mismatch and graph serialization;
6. retain both logs.
