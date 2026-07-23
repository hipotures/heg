# Codex implementation task: Structural Graph Conjecture Lab

You are implementing the repository described by `README.md`, `AGENTS.md`, and `docs/`. Read those files before editing code.

## Primary objective

Build a compact, fast, reproducible Linux system for searching finite counterexamples to structural graph conjectures. Implement a generic target plugin interface, but optimize the first complete vertical slice for the **Erdős–Gyárfás conjecture**:

> Every finite simple graph with minimum degree at least 3 contains a simple cycle whose length is a power of two.

The system must support heuristic discovery, exact verification, controlled SAT experiments, checkpointing, telemetry, and a minimal HTTP dashboard.

## Research status constraint

Do not present the project as attacking an unsearched small range. As of 2026-07-23:

- the general Erdős–Gyárfás conjecture remains open in current literature;
- a recent public SAT repository claims no counterexample through 31 vertices;
- therefore the novel heuristic frontier begins at order 32 or higher;
- smaller orders are validation and reproduction gates only.

Read `docs/00_RESEARCH_STATUS.md` and retain its status timestamp in generated run metadata.

## Technical choices

### Required

- Python 3.12.
- `argparse`, `sqlite3`, `multiprocessing`, `http.server`, `tomllib`, and other standard-library modules where practical.
- A compact bitset adjacency representation using Python integers for graphs up to at least 128 vertices.
- SQLite in WAL mode for run metadata and improvements.
- Atomic JSON state snapshots for the dashboard.
- Standard-library HTTP server with a static page and JSON polling.
- Optional PySAT/CaDiCaL integration for CEGAR-SAT.
- Optional external `nauty/Traces`, SAT Modulo Symmetries, and Glasgow Subgraph Solver integration.
- One optional C++17 helper executable for the hot exact cycle/subgraph checks if benchmarks justify it.

### Forbidden in v1

- React, Vue, Angular, Node.js build systems;
- Django, Flask, FastAPI;
- Celery, Redis, RabbitMQ;
- SQLAlchemy or another ORM;
- Kubernetes or container orchestration;
- a custom distributed scheduler;
- a GPU dependency;
- MCTS before simpler baselines are implemented and benchmarked;
- an LLM call inside the inner candidate loop.

## Milestones

Implement sequentially. Do not jump to optional solver integration before the baseline is correct.

### M0 — repository and operations baseline

- Make the starter scaffold installable with `uv` and regular `pip`.
- Implement `sglab doctor`, `sglab init`, `sglab serve`, and configuration loading.
- Add SQLite schema creation and migrations without an ORM.
- Add structured JSONL logs and atomic `state.json` updates.
- Make `make doctor`, `make test`, and `make dashboard-smoke` work.

Acceptance:

```bash
make doctor
make test
make dashboard-smoke
```

### M1 — graph core and reference verifier

- Complete `BitGraph` with immutable adjacency rows, edge iteration, degree sequence, connectivity, graph6 import/export, and stable hashing.
- Implement a slow, obviously correct reference detector for a simple cycle of exact length `k`.
- Implement Erdős–Gyárfás target validation:
  - finite simple undirected graph;
  - connected for minimal-candidate search;
  - minimum degree at least 3;
  - no cycle of length `2^j` for every `4 <= 2^j <= n`.
- Return witnesses, not only booleans.
- Add small cross-check tests against NetworkX only as an optional reference dependency.

Acceptance:

- exact results on hand-constructed graphs;
- agreement between two implementations on small random graphs;
- no test larger than necessary.

### M2 — heuristic search baseline

Implement two simple algorithms before considering MCTS:

1. multi-start simulated annealing;
2. iterated local search with tabu memory.

For cubic graphs use degree-preserving double-edge swaps. For mixed-degree graphs use constrained edge add/remove/swap operations while preserving or repairing minimum degree.

The objective is lexicographic:

1. hard structural validity;
2. number of forbidden-cycle witnesses found, capped per length;
3. weighted witness count by length;
4. diversity/novelty from the archive;
5. simplicity and canonical uniqueness.

The hot-loop detector may be incomplete and capped, but every finalist must go through the exact verifier. Never treat a heuristic timeout as absence of a cycle.

Requirements:

- deterministic seeds;
- bounded queues;
- worker process isolation;
- periodic checkpoints;
- resume support;
- improvement-only persistence;
- canonical deduplication at archive boundaries, not at every mutation unless profiling proves it affordable;
- per-worker and aggregate telemetry.

Acceptance:

- repeatable benchmark on `n=20,24,28,32`;
- clean stop/pause/resume;
- no unbounded RSS growth during a two-hour soak test.

### M3 — fast exact cycle checker

Profile the Python reference verifier. If it is the bottleneck, implement one small C++17 executable:

```text
sglab-cyclecheck --graph6 <file> --length 4 --length 8 ...
```

It must:

- use bit-parallel adjacency;
- support early witness return;
- support exact exhaustive completion;
- emit machine-readable JSON;
- distinguish `FOUND`, `ABSENT`, `TIMEOUT`, and `ERROR`;
- include the witness cycle when found;
- enforce a caller-provided wall-time limit only for search ranking, not for final certification;
- be cross-checked against the Python reference implementation on small graphs.

Do not build a Python extension unless subprocess overhead is demonstrated to dominate. A persistent worker protocol over stdin/stdout is acceptable after measurement.

### M4 — CEGAR-SAT path

Implement an optional SAT path using PySAT with CaDiCaL:

- one Boolean variable per possible edge;
- cardinality constraints for minimum degree at least 3;
- optional connectedness constraints or lazy connectedness cuts;
- solve for a candidate graph;
- exact verifier returns a forbidden cycle witness;
- add a blocking clause requiring at least one edge of that cycle to be absent;
- repeat until SAT candidate passes exact verification, UNSAT is certified, or budget expires.

Requirements:

- every learned cycle clause is stored with its witness;
- timeout result is `UNKNOWN`;
- CNF, learned structural clauses, solver version, seed, and hashes are preserved;
- implement only modest static symmetry breaking initially;
- compare against ground truth generated by `nauty` on small orders;
- do not claim exhaustive results above the validated range without a checkable proof artifact.

### M5 — minimal HTTP dashboard

Use only `http.server` and static HTML/JavaScript.

Pages/endpoints:

- overview: current run, status, elapsed time, candidates/s, best score, worker health, RSS, database size;
- best candidates: table, score components, graph SVG, graph6 download, exact-verifier status;
- experiments: previous runs and comparison metrics;
- logs: bounded tail;
- controls: start, pause, resume, stop;
- simple run form: target, `n`, algorithm, worker count, seed, time limit, memory limit, notes.

Security:

- bind to `127.0.0.1` by default;
- require an explicit flag for `0.0.0.0`;
- optional bearer token from an environment variable;
- whitelist actions and validate all numeric ranges;
- never expose arbitrary shell execution;
- use POST for controls;
- do not serve files outside the workspace.

### M6 — benchmarking and forecasting

Implement:

- microbenchmarks for mutation, score, exact cycle detection, canonicalization, SQLite writes, and SAT iterations;
- scaling runs at several `n` values;
- p50, p90, p95, and peak RSS;
- candidate/day estimates;
- empirical growth-factor estimates between adjacent orders;
- a forecast report with a range, not a single false-precision number;
- a one-command 15-minute calibration run;
- a two-hour soak run.

Do not extrapolate SAT runtime linearly. Report heavy-tail behavior and solver seeds.

### M7 — optional external tools

Only after M0–M6 pass:

- `nauty/Traces` for graph generation and canonical labels;
- SAT Modulo Symmetries for isomorph-free constrained generation;
- Glasgow Subgraph Solver for exact forbidden-cycle subgraph checks;
- pin source commits in a generated lock file;
- keep external tools optional and isolate them behind adapters.

## Data model

Use the formats in `docs/13_DATA_FORMATS.md`.

Core persisted artifacts:

- `run.json` — immutable parameters and environment;
- `state.json` — atomic live snapshot;
- `events.jsonl` — append-only bounded-detail events;
- `results.sqlite3` — indexed runs, metrics, improvements, artifacts;
- `best/<candidate-id>.graph6`;
- `best/<candidate-id>.json`;
- `certificates/<candidate-id>/...`;
- `benchmarks/<benchmark-id>.json`.

Do not store all rejected candidates.

## Resource safety

Implement the rules in `docs/06_RESOURCE_SAFETY.md`:

- bounded multiprocessing queues;
- process groups and kill-on-timeout;
- cgroup v2 integration when available;
- fallback `resource.setrlimit` and `/proc` RSS monitoring;
- configurable memory high-water and hard limit;
- SQLite WAL checkpoints;
- output-size limits;
- worker recycling;
- disk-space guard;
- master reserve of at least two CPU threads and 10–15% RAM.

A worker killed for memory is a normal controlled outcome, not a process-wide crash.

## Test budget

Keep tests small. Aim for roughly 20–40 meaningful tests, not hundreds of generated cases. Use explicit benchmark commands for scale and soak behavior.

## Documentation deliverables

Update or create:

- `docs/IMPLEMENTATION_STATUS.md`;
- command reference;
- actual installation instructions tested on Ubuntu/Debian and Arch/Manjaro;
- benchmark results with hardware metadata;
- limitations and unresolved risks;
- exact reproduction commands.

## Completion criteria

The implementation is complete when:

```bash
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

all pass, and a documented pilot run can be started, observed in the browser, paused, resumed, stopped, and independently verified.

Do not state that the Erdős–Gyárfás conjecture was refuted unless a graph passes both exact verifiers and the artifact contains the full witness and environment metadata.
