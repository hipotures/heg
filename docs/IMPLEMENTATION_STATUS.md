# Implementation Status

Last implementation audit: **2026-07-24**.

## M0 — complete

- installable standard `src/` package and CLI entry point;
- layered TOML configuration;
- `doctor`, `init`, `serve`, `verify`, and smoke commands;
- versioned SQLite schema in WAL mode, without an ORM;
- atomic, directory-synced state snapshots and bounded JSONL event rotation;
- required workspace artifact directories.

Evidence: focused unit tests plus `make doctor`, `make test`, `make check`, and
`make dashboard-smoke`.

## M1 — complete

- immutable integer-bitset graph representation through at least 128 vertices;
- invariant checks, edge iteration, degrees, connectivity, graph6 round trip,
  and stable non-canonical hash;
- exact DFS cycle witness detector;
- independent subset-DP detector with agreement tests on deterministic small
  random graphs;
- Erdős–Gyárfás structural validation and witness-returning exact result.

## M2 — implemented

- bounded multiprocessing coordinator with master-only SQLite writes;
- simulated annealing and iterated local search with deterministic seeds;
- cubic swaps, minimal-structure mixed-degree seeds, and unrestricted
  add/remove/swap moves;
- lexicographic structural, witness, weighted, novelty, and simplicity score;
- bounded top archive, improvement-only persistence, worker telemetry and
  recycling;
- a deterministic per-length DFS-node budget for the explicitly incomplete
  hot-loop scorer;
- hashed checkpoints, same-run resume, and file-based pause/resume/stop;
- one-coordinator workspace locking and bounded SQLite/event-log retention;
- finalist submission to both exact verifier paths.

A short automated soak exercised pause/resume and recycling. The production
two-hour evidence gate is tracked separately from this software-completion
statement.

## M3 — implemented and benchmark-gated

- one C++17 integer-bitset helper with `FOUND`, `ABSENT`, `TIMEOUT`, and
  `ERROR` JSON results and cycle witnesses;
- subprocess process-group, output, and wall limits;
- deterministic cross-checks against the Python oracle;
- standalone two-verifier certificate manifest.

The smoke profile shows process startup dominates easy early-witness cases.
The C++ helper is therefore used for independent finalist verification, not
silently inserted into the heuristic loop.

## M4 — implemented as an optional path

- edge-variable CNF and minimum-degree cardinality clauses;
- lazy connectedness cuts and witness-backed forbidden-cycle clauses;
- preserved final CNF, learned JSONL, metadata, hashes, and optional proof;
- tiny deterministic DPLL/CEGAR ground truth at `n=4`;
- optional nauty overlap adapter;
- conservative timeout and unchecked-UNSAT semantics.

PySAT 1.9.dev7 with the `cadical195` backend was exercised on Python 3.12 at
`n=4`, including proof preservation, and with a forced timeout at `n=8`.
The UNSAT proof remains deliberately unchecked and therefore unclaimed.
nauty is not installed on the host, so its live overlap gate remains external.

## M5 — complete

- standard-library threaded HTTP server and static HTML/JavaScript;
- overview, candidates, experiments, bounded logs, graph downloads, and
  deterministic SVGs;
- validated start form and POST pause/resume/stop;
- local binding by default and optional bearer protection;
- bearer protection for every API route when configured;
- path traversal, request size, response size, action, and numeric guards.

## M6 — implemented

- raw-sample microbenchmarks with p50/p90/p95/max and peak RSS;
- deterministic calibration at `n=20,24,28,32` for both baseline algorithms;
- adjacent-order factors, candidates/day ranges, 24-hour and 7-day forecasts;
- hardware metadata and explicit heavy-tail SAT warning;
- configurable soak runner that exercises pause/resume, recycling, RSS plateau,
  database growth, and bounded queues.

The earlier 15-minute, 16-process calibration is preserved under
`docs/benchmarks/`, but the scorer work-budget correction requires a fresh
calibration before final acceptance. A short soak passed functional
pause/resume and RSS checks; a failed 265-second attempt is retained as
negative evidence. Neither substitutes for the separate two-hour production
soak gate.

## M7 — optional adapters complete

- bounded adapters and availability/version reporting for nauty/Traces, SAT
  Modulo Symmetries, and Glasgow;
- nauty canonical-label path with a clearly marked non-authoritative fallback;
- `tools.lock.json` refuses to pretend absent tools have pinned commits.

Installed external tools must receive exact commits and overlap tests before
their lock entries are enabled.

Engineering completion is not a mathematical result. No counterexample or
exhaustive nonexistence claim has been made.
