# Structural Graph Conjecture Lab

A compact Linux research tool for reproducible searches for finite
counterexamples to structural graph conjectures. The implemented pilot target
is the **Erdős–Gyárfás conjecture**:

> Every finite simple graph with minimum degree at least 3 contains a simple
> cycle whose length is a power of two.

The general conjecture is recorded as open on **2026-07-23**. A public SAT
repository claims verification through 31 vertices, so this project treats
`n <= 31` as validation/reproduction territory and begins heuristic novelty
searches at `n >= 32`.

This is an engineering and experimentation system, not a claim that the
conjecture has been resolved.

## Implemented vertical slice

- immutable integer-bitset graphs and graph6 import/export through 128 vertices;
- two Python exact algorithms cross-checked on small random graphs;
- one independent C++17 bitset verifier with a JSON protocol;
- simulated annealing and iterated local search with cubic and mixed-degree modes;
- bounded multiprocessing telemetry, checkpoints, resume, worker recycling,
  resource limits, improvement-only archives, and deterministic seeds;
- SQLite WAL run archive and standalone cross-hashed verification artifacts;
- optional witness-backed CEGAR-SAT path through PySAT/CaDiCaL;
- static HTML plus standard-library HTTP API, bearer-token protection, and safe
  start/pause/resume/stop controls;
- microbenchmarks, frontier calibration, forecasts, and soak automation;
- optional adapters for nauty, SAT Modulo Symmetries, and Glasgow.

No rejected-candidate firehose is stored, no LLM is called in the candidate
loop, and a timeout is always unknown rather than UNSAT.

## Install

Python 3.12 or newer and a C++17 compiler are required.

With `uv`:

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
make cyclecheck
```

Regular virtual environments are also supported:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
make cyclecheck
```

Optional SAT and reference packages:

```bash
uv pip install -e '.[sat,reference]'
```

The bootstrap scripts cover package prerequisites on Ubuntu/Debian and
Arch/Manjaro. External solvers remain optional and are reported by `doctor`.

## Verify the installation

```bash
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

## Pilot run

Initialize a workspace, start a bounded frontier run, and open the dashboard:

```bash
sglab init --workspace ./workspace
sglab run \
  --target erdos_gyarfas \
  --order 32 \
  --mode cubic_first \
  --algorithm simulated_annealing \
  --workers 12 \
  --seed 1 \
  --time-limit 24h \
  --workspace ./workspace

sglab serve --workspace ./workspace --host 127.0.0.1 --port 8080
```

The run is foreground by design. Run the dashboard in another terminal, or
start the run from its validated form. Controls can also be issued from a CLI:

```bash
sglab control --workspace ./workspace --action PAUSE
sglab control --workspace ./workspace --action RESUME
sglab control --workspace ./workspace --action STOP
```

Resume the same run and worker RNG checkpoints:

```bash
sglab resume --run ./workspace/runs/<run-id> --time-limit 2h
```

For LAN exposure, explicitly pass `--host 0.0.0.0`, configure a firewall, and
set `SGLAB_WEB_TOKEN`.

## Independent verification

Verification is standalone and reads only the exported graph:

```bash
sglab verify \
  --graph6 ./candidate.graph6 \
  --artifact-dir ./certificate
```

The artifact contains graph6, a JSON edge list, hashes, environment metadata,
both verifier reports, and a reproduction command. A graph is marked
`COUNTEREXAMPLE_VERIFIED` only when structural validation and both independent
exact paths agree that every target cycle length is absent.

## Benchmarks and SAT

```bash
sglab benchmark micro --iterations 10 --output ./workspace/benchmarks
sglab benchmark calibrate \
  --minutes 15 \
  --seeds 2 \
  --target erdos_gyarfas \
  --output ./workspace/benchmarks
sglab benchmark soak \
  --hours 2 \
  --order 32 \
  --workers 12 \
  --workspace ./workspace-soak \
  --output ./workspace-soak/benchmarks

sglab sat \
  --order 8 \
  --time-limit 10m \
  --seed 1 \
  --output ./workspace/sat-n8
```

SAT UNSAT is never advertised as certified unless a proof is preserved and
independently checked. The current optional PySAT path therefore reports an
unchecked solver UNSAT conservatively as `NO_RESULT_WITHIN_BUDGET` with an
explicit detail field.

See [the command reference](docs/18_COMMAND_REFERENCE.md), the
[operations runbook](docs/15_OPERATIONS_RUNBOOK.md), and the
[implementation status](docs/IMPLEMENTATION_STATUS.md) for exact usage and
remaining scientific limitations.
