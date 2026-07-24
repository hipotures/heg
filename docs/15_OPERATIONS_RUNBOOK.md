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

### Active AI research campaign

Before importing credentials, run the no-model protocol/configuration audit:

```bash
sglab ai-director compliance-audit --workspace ./workspace
```

Import an existing Codex login only after explicit authorization:

```bash
sglab ai-director auth-import \
  --workspace ./workspace \
  --from-codex-home /explicit/authorized/codex/home
```

Then choose exactly one stop contract:

```bash
sglab research-campaign start --workspace ./workspace --time-limit 24h
sglab research-campaign start --workspace ./workspace --until-success
```

Both commands run in the foreground. The installed target is immutable for the
campaign; the Director chooses scientific parameters and concurrent lane
allocation. Authentication is kept under the private application directory
and is excluded from exports.

Operational commands:

```bash
sglab research-campaign status --workspace ./workspace
sglab research-campaign pause --workspace ./workspace
sglab research-campaign continue --workspace ./workspace
sglab research-campaign stop --workspace ./workspace
sglab research-campaign resume --workspace ./workspace \
  --campaign-id <campaign-id>
sglab research-campaign export --workspace ./workspace \
  --campaign-id <campaign-id> --output ./campaign.zip
```

Pause, resume, and stop are emergency operational controls, not scientific
inputs. A stopped campaign is an abnormal terminal result. Only M4
certification produces scientific success.

### Legacy fixed-configuration run

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

The command runs in the foreground and writes all live and immutable artifacts
under `workspace/runs/<run-id>/`. A nonblocking workspace lock prevents two
coordinators from writing the same workspace concurrently.

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

After workers stop, the best archived finalist enters
`VERIFYING_FINALIST`; Python and C++ reports are recorded before the terminal
run status is written.

## Crash recovery

On startup:

- inspect last state;
- verify checkpoint hashes;
- mark orphaned prior process IDs as dead;
- recover SQLite WAL;
- offer resume or finalize-as-crashed;
- never overwrite the previous run directory.

For an Active Director campaign, use `research-campaign resume`. Recovery
checks SQLite integrity and checkpoint hashes, resumes the same persisted
app-server thread, restores lane RNG/checkpoint state, requeues interrupted
verification, and redispatches only accepted actions without outcomes.

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
