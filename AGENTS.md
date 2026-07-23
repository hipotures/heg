# Project Instructions for Codex

## Mission

Implement a compact Linux research tool for searching structural graph conjecture counterexamples. The default pilot target is the Erdős–Gyárfás conjecture. Follow `CODEX_PROMPT.md` and the documents under `docs/`.

## Non-negotiable engineering constraints

1. Keep the implementation small and inspectable.
2. Use Python 3.12 for orchestration and the HTTP dashboard.
3. Use a single optional C++17 helper only where profiling proves Python is too slow.
4. Do not introduce React, Node.js, Django, Flask, FastAPI, Celery, Redis, an ORM, Kubernetes, or a distributed task framework.
5. The web UI must remain a static HTML page plus standard-library Python HTTP endpoints.
6. Do not put an LLM call in the candidate-evaluation loop.
7. Do not store every candidate. Persist only run metadata, periodic aggregates, improvements, checkpoints, and verified artifacts.
8. Bound queues, caches, subprocess time, resident memory, output size, and database growth.
9. A timeout is `UNKNOWN`, never `UNSAT`.
10. Any claimed counterexample must pass two independent exact verification paths.
11. Any exhaustive nonexistence claim must preserve the complete instance, solver version, logs, hashes, and a machine-checkable proof certificate when the selected solver supports it.
12. Do not optimize before measuring. Add benchmark gates before replacing simple code.

## Testing policy

Keep the test suite focused. Required tests cover:

- graph representation invariants;
- reference cycle detection on small known graphs;
- exact-verifier agreement on small random graphs;
- state-file atomicity;
- one tiny SAT ground-truth comparison;
- one HTTP API smoke test;
- one resource-limit smoke test.

Do not generate large combinatorial parameter grids in unit tests. Expensive checks belong in explicit benchmark or verification commands.

## Development workflow

- Work milestone by milestone.
- At the end of each milestone, update `docs/IMPLEMENTATION_STATUS.md`.
- Preserve unsuccessful benchmark results and failure logs.
- Do not silently change the mathematical target.
- Prefer deterministic seeds and record them.
- Keep research claims separate from software completion claims.

## Required commands when complete

```bash
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

The project is not complete merely because the dashboard starts. The exact verifier and reproducible artifact format are the scientific core.
