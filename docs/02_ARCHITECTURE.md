# Architecture

## High-level design

```text
                           periodic human / LLM analysis
                                      |
                                      v
+------------------+       +----------------------+       +------------------+
| target plugin    | ----> | search coordinator   | ----> | worker processes |
| constraints      |       | budgets / archive    |       | mutate + score   |
+------------------+       +----------+-----------+       +--------+---------+
                                      |                            |
                                      v                            v
                           +----------------------+       +------------------+
                           | exact verification   |       | bounded telemetry|
                           | Python/C++/SAT/tools  |       +------------------+
                           +----------+-----------+
                                      |
                                      v
                  +-------------------+-------------------+
                  | SQLite + files + atomic state snapshot|
                  +-------------------+-------------------+
                                      |
                                      v
                           minimal HTTP dashboard
```

## Processes

### Master

Responsibilities:

- read immutable run configuration;
- create the workspace and database record;
- start workers;
- enforce global budgets;
- aggregate metrics;
- maintain top-K archive;
- queue exact verification;
- process dashboard control requests;
- write atomic state snapshots;
- checkpoint and resume.

The master must not perform expensive graph search.

### Search workers

Each worker:

- owns one current graph and RNG state;
- performs local mutations;
- computes cheap scores;
- sends only improvements and periodic aggregates;
- does not write directly to SQLite;
- may be recycled after a configured number of candidates.

### Exact-verifier workers

Separate processes with stricter concurrency and memory limits. They may call:

- the Python reference verifier;
- the C++ exact cycle checker;
- Glasgow Subgraph Solver;
- PySAT/CaDiCaL.

### HTTP server

A separate lightweight thread or process reads snapshots and SQLite. It never owns search state and cannot execute arbitrary shell commands.

## Storage

### SQLite

Use WAL mode. Tables should include:

- `runs`
- `run_metrics`
- `candidates`
- `candidate_scores`
- `artifacts`
- `verifications`
- `benchmarks`
- `tool_versions`

Write in batches. The master is the only writer.

### Files

```text
workspace/
  runs/<run-id>/
    run.json
    state.json
    control.json
    events.jsonl
    results.sqlite3
    checkpoints/
    best/
    certificates/
    benchmarks/
    logs/
```

### Atomic state

Write `state.json.tmp`, `fsync`, then `os.replace`. The dashboard must tolerate a missing or temporarily stale state file.

## Plugin boundary

A target plugin defines:

- graph-domain constraints;
- seed generation;
- legal mutations;
- cheap score;
- exact verification;
- witness serialization;
- result explanation;
- optional SAT encoding hooks.

Search code must not contain hard-coded Erdős–Gyárfás logic outside its target plugin.

## Why not MCTS first

MCTS is valuable when partial states have informative value estimates and actions form a meaningful tree. A graph mutation landscape is cyclic, has many transpositions, and already has strong local-search baselines. Implement simulated annealing and iterated local search first. Add MCTS only if benchmark evidence shows that sequence-dependent construction outperforms state-space mutation.
