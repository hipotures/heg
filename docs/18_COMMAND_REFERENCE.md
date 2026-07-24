# Command Reference

All commands accept `--help`. Durations accept seconds or a suffix `s`, `m`,
`h`, or `d` where supported.

## Active AI research campaign

```bash
sglab ai-director preflight --workspace ./workspace
sglab ai-director auth-import --workspace ./workspace \
  --from-codex-home /explicit/authorized/codex/home
sglab ai-director inspect-session --workspace ./workspace

sglab research-campaign start --workspace ./workspace --time-limit 24h
sglab research-campaign start --workspace ./workspace --until-success
sglab research-campaign status --workspace ./workspace
sglab research-campaign pause --workspace ./workspace
sglab research-campaign continue --workspace ./workspace
sglab research-campaign stop --workspace ./workspace
sglab research-campaign resume --workspace ./workspace \
  --campaign-id <campaign-id>
sglab research-campaign export --workspace ./workspace \
  --campaign-id <campaign-id> --output ./campaign.zip
```

Normal campaign start exposes no scientific tuning flags. The installed target
is read-only, and the AI Director chooses algorithms, graph sizes, lane count,
seeds, mutation parameters, resource shares, and review cadence. `run` below
is retained as the legacy fixed-configuration engine command.

## Workspace and diagnosis

```bash
sglab doctor
sglab init --workspace ./workspace
```

`doctor` reports Python, cgroup v2, the compiled cycle checker, and optional
external tools. `init` creates the bounded artifact layout and a WAL-mode
SQLite database.

## Search

The following is the legacy parameterized research-engine interface, not the
normal Active Director campaign interface.

```bash
sglab run \
  --target erdos_gyarfas \
  --order 32 \
  --mode cubic_first \
  --algorithm simulated_annealing \
  --workers 12 \
  --seed 1 \
  --time-limit 24h \
  --memory-high 161061273600 \
  --memory-limit 180388626432 \
  --exact-timeout 30 \
  --workspace ./workspace
```

Modes:

- `cubic_first`
- `minimal_structure_mixed_degree`
- `unrestricted_min_degree_3`

Algorithms:

- `simulated_annealing`
- `iterated_local_search`

Crossing `--memory-high` pauses new search work and records the incident;
crossing `--memory-limit` ends the run as `UNKNOWN_MEMORY_LIMIT`.
The high-water and hard checks use aggregate master-plus-worker RSS; a
nonzero hard value is also applied as a per-worker `RLIMIT_AS` fallback.
`--memory-limit 0` leaves that hard fallback unset; cgroups remain the
preferred production limit. When only a smaller hard limit is overridden, an
incompatible configured high-water mark is disabled rather than causing a
startup failure. `--exact-timeout 0` removes the wall timeout from
finalist verification and is appropriate only for a deliberately supervised
certification run.

```bash
sglab control --workspace ./workspace --action PAUSE
sglab control --workspace ./workspace --action RESUME
sglab control --workspace ./workspace --action STOP
sglab resume --run ./workspace/runs/<run-id> --time-limit 2h
```

Checkpoints have adjacent SHA-256 manifests. Resume rejects a mismatched
checkpoint rather than silently loading it. A workspace lock rejects a second
concurrent coordinator.

## Dashboard

```bash
sglab serve --workspace ./workspace --host 127.0.0.1 --port 8080
```

The dashboard exposes:

- `GET /api/status`
- `GET /api/runs`
- `GET /api/candidates?limit=50`
- `GET /api/logs?limit=100`
- `GET /api/artifact/<candidate-id>.<graph6|json|svg>`
- `POST /api/control`
- `POST /api/runs`
- `GET /api/research-campaign`
- `POST /api/research-campaign`
- `POST /api/research-campaign/control`

Set `SGLAB_WEB_TOKEN` to require `Authorization: Bearer ...` for every API
request. Open the page as `http://127.0.0.1:8080/#token=<value>`; URL fragments
are not sent in the HTTP request. Run parameters are numeric-range checked and
allowlisted. No request parameter becomes a shell command.

## Verification

```bash
sglab verify --graph6 candidate.graph6
sglab verify --graph-json candidate.json
sglab verify --graph6 candidate.graph6 --artifact-dir ./certificate \
  --timeout 0 --memory-limit 0
```

The default uses the Python reference DFS and independent C++17 bitset
verifier. `--reference-only` is a diagnostic mode and cannot produce a
two-verifier counterexample certificate.

## SAT

```bash
sglab sat \
  --order 8 \
  --solver cadical195 \
  --seed 1 \
  --time-limit 10m \
  --memory-limit 8589934592 \
  --output ./workspace/sat-n8
```

The optional command requires `python-sat`. It preserves the final DIMACS CNF,
metadata, candidate graph (if any), and every lazy clause in `learned.jsonl`.
Cycle clauses include their ordered vertex witnesses. Timeouts and unchecked
UNSAT results never become `UNSAT_CERTIFIED`. A nonzero `--memory-limit`
applies `RLIMIT_AS` to the isolated solver process; exhaustion is
`UNKNOWN_MEMORY_LIMIT`, never UNSAT.

## Benchmarking

```bash
sglab benchmark micro --iterations 10 --output ./workspace/benchmarks
sglab benchmark calibrate --minutes 15 --seeds 2 --target erdos_gyarfas \
  --output ./workspace/benchmarks
sglab benchmark soak --hours 2 --order 32 --workers 12 \
  --workspace ./workspace-soak --output ./workspace-soak/benchmarks
sglab benchmark active-director-controls \
  --workspace ./workspace/m6-active-control --output ./docs/reports
```

Reports preserve raw samples, p50/p90/p95/max, hardware metadata, peak RSS,
adjacent-order factors, and range forecasts. The soak command automatically
exercises pause/resume and records bounded-queue and worker-recycle settings.
Calibration cases run in separate processes; `--jobs` caps concurrency while
the default reserves at least two logical CPU threads.

`active-director-controls` is a control-only M6 research benchmark, not a
normal campaign form. Its static, random, serial-AI compatibility, and Active
AI arms use fixed equal envelopes. `--smoke` selects the fixed two-seed,
ten-second integration profile; there are no algorithm, worker, graph-size,
mutation, lane-allocation, or Director-cadence flags.
