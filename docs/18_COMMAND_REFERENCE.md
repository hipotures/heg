# Command Reference

All commands accept `--help`. Durations accept seconds or a suffix `s`, `m`, or
`h`.

## Workspace and diagnosis

```bash
sglab doctor
sglab init --workspace ./workspace
```

`doctor` reports Python, cgroup v2, the compiled cycle checker, and optional
external tools. `init` creates the bounded artifact layout and a WAL-mode
SQLite database.

## Search

```bash
sglab run \
  --target erdos_gyarfas \
  --order 32 \
  --mode cubic_first \
  --algorithm simulated_annealing \
  --workers 12 \
  --seed 1 \
  --time-limit 24h \
  --memory-limit 0 \
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

`--memory-limit 0` leaves the per-worker `RLIMIT_AS` unset; cgroups remain the
preferred production limit. `--exact-timeout 0` removes the wall timeout from
finalist verification and is appropriate only for a deliberately supervised
certification run.

```bash
sglab control --workspace ./workspace --action PAUSE
sglab control --workspace ./workspace --action RESUME
sglab control --workspace ./workspace --action STOP
sglab resume --run ./workspace/runs/<run-id> --time-limit 2h
```

Checkpoints have adjacent SHA-256 manifests. Resume rejects a mismatched
checkpoint rather than silently loading it.

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

Set `SGLAB_WEB_TOKEN` to require `Authorization: Bearer ...` for mutations and
artifact downloads. Run parameters are numeric-range checked and
allowlisted. No request parameter becomes a shell command.

## Verification

```bash
sglab verify --graph6 candidate.graph6
sglab verify --graph-json candidate.json
sglab verify --graph6 candidate.graph6 --artifact-dir ./certificate
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
  --output ./workspace/sat-n8
```

The optional command requires `python-sat`. It preserves the final DIMACS CNF,
metadata, candidate graph (if any), and every lazy clause in `learned.jsonl`.
Cycle clauses include their ordered vertex witnesses. Timeouts and unchecked
UNSAT results never become `UNSAT_CERTIFIED`.

## Benchmarking

```bash
sglab benchmark micro --iterations 10 --output ./workspace/benchmarks
sglab benchmark calibrate --minutes 15 --target erdos_gyarfas \
  --output ./workspace/benchmarks
sglab benchmark soak --hours 2 --order 32 --workers 12 \
  --workspace ./workspace-soak --output ./workspace-soak/benchmarks
```

Reports preserve raw samples, p50/p90/p95/max, hardware metadata, peak RSS,
adjacent-order factors, and range forecasts. The soak command automatically
exercises pause/resume and records bounded-queue and worker-recycle settings.
