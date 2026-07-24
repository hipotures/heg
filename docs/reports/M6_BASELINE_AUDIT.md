# M6 Active Director Baseline Audit

Audit timestamp: **2026-07-24T08:02:08Z**

This report freezes the real repository state before implementation of the
Active AI Research Director. The repository is authoritative; the package in
`planning/m6-active-director/` is treated as a target specification.

## Frozen Git baseline

- Branch: `main`
- Commit: `bdacdb34b12086fe3f906bf3794397d81f4427ab`
- Commit subject: `Complete acceptance audit and pilot evidence`
- Remote state at audit: `main...origin/main`
- Pre-existing tracked changes: none
- Pre-existing untracked input: `planning/`
- Tags before the audit: none
- Baseline tag created by this audit:
  `m6-baseline-bdacdb3` → `bdacdb34b12086fe3f906bf3794397d81f4427ab`

The untracked planning package is user-supplied input and is deliberately not
part of the baseline or subsequent implementation commits.

## Existing checks

| Gate | Baseline result | Notes |
| --- | --- | --- |
| `make doctor` | PASS | Python 3.14.5 satisfies `>=3.12`; C++ helper available; cgroup v2 present |
| `make test` | PASS, 40 tests | 10.819 s outside the socket-restricted sandbox |
| `make check` | PASS | `compileall` for `src` and `tests` |
| `make benchmark-smoke` | PASS | `micro-20260724T075948Z`; two samples at n=20,24,28,32 |
| `make dashboard-smoke` | PASS | Local HTTP endpoint and static page |

The first sandboxed `make test` and `make dashboard-smoke` attempts could not
create an IPv4 socket and failed with `PermissionError: [Errno 1] Operation not
permitted`. Re-running the unchanged commands with local-socket permission
passed. This is an execution-sandbox restriction, not an application failure.

## Authoritative current architecture

The package name and CLI are `structural-graph-lab` / `sglab`, not `gilab`.
There is no current AI provider, research-round orchestrator, action protocol,
replay provider, research export, or `src/gilab/research/` package.

The live path is:

```text
sglab CLI or HTTP POST
  → sglab.search.run_search()
  → one synchronous master/coordinator
  → N multiprocessing search workers with static SearchConfig
  → bounded telemetry/improvement queue
  → master-only SQLite and artifact writes
  → workers stop
  → one best finalist passes sglab.certification.certify()
  → independent Python DFS + C++17 verifier quorum
  → atomic state consumed by stdlib HTTP dashboard
```

### Current module boundaries

| Concern | Actual module(s) and behavior |
| --- | --- |
| Configuration | `config.py`, layered TOML; normal CLI/dashboard also accept scientific tuning |
| CLI | `cli.py`; `run`, `resume`, `control`, `verify`, `sat`, benchmark and HTTP commands |
| HTTP | `web.py` + `web/index.html`; static assets and JSON polling; POST launches `sglab run` without a shell |
| Search orchestration | `search.py::run_search`; global lock, static configuration, process lifecycle, archive, state, final verification |
| Worker execution | `search.py::_worker`; long-lived graph/RNG/tabu state, periodic checkpoint, but no control mailbox or parameter revision |
| Algorithms | `search.py` and `targets/erdos_gyarfas.py`; simulated annealing and ILS over three graph modes |
| Snapshot/state | `state.py` and per-run `state.json`; atomic replace and bounded JSONL event rotation |
| Persistence | `db.py`; per-run SQLite database, WAL, one master writer, bounded metric retention |
| Candidate artifacts | `artifacts.py`; bounded archive files and hashes |
| M4 boundary | `certification.py`; only two complete independent verifiers can emit `COUNTEREXAMPLE_VERIFIED` |
| Exact implementations | `targets/erdos_gyarfas.py`, `verification.py`, and the single C++17 helper |
| SAT | `sat.py`; separate optional CEGAR command, not the normal search loop |
| Resource controls | `resources.py` plus `search.py`; bounded queues/output/logs/archive, RLIMIT, process groups, RSS/disk checks, worker recycling |
| External tools | `external.py`; optional bounded adapters |
| Benchmarks | `benchmark.py`; micro, calibration and soak controls |

Useful foundations for M6 already exist: stateful deterministic worker
checkpoints, bounded multiprocessing queues, worker recycling, atomic state,
master-only database writes, a target plugin, strict two-verifier
certification, and a minimal static dashboard.

## SQLite baseline

`src/sglab/db.py` declares `SCHEMA_VERSION = 1`. Read-only inspection of:

- `workspace/results.sqlite3`;
- `workspace/runs/20260724T033028Z-eg-n32-sa-s1/results.sqlite3`;
- `workspace/runs/20260724T032408Z-eg-n32-sa-s1/results.sqlite3`;

reported `PRAGMA user_version = 1` and the same definitions:

- `runs`
- `run_metrics`
- `candidates`
- `candidate_scores`
- `artifacts`
- `verifications`
- `benchmarks`
- `tool_versions`
- index `candidates_run_score`

There are no migration SQL files. Migration 0→1 is embedded in `db.py`.
Production run data is stored in each run directory; the workspace database
created by `sglab init` is not the coordinator's campaign database.

## Verification and authority baseline

`certification.py::certify` is the only current path that emits
`COUNTEREXAMPLE_VERIFIED`. It requires:

1. complete `VERIFIED` from the Python reference DFS; and
2. complete `ABSENT` from the independently implemented C++17 bitset DFS.

Timeout and memory outcomes remain unknown, malformed output is a tool
failure, and disagreement is explicit. M6 must call this boundary without
changing its semantics. The current coordinator verifies only the best
finalist after all search workers have stopped; there is no concurrent
verifier broker or queue yet.

## Discrepancies between the planning package and the repository

1. The planning package targets `gilab`; the repository exposes `sglab`.
2. The package assumes an M5 AI-directed serial controller. No AI/model call
   exists anywhere in the current runtime.
3. The package assumes schema v6 and many research tables. The actual schema
   is v1 with eight tables.
4. `docs/reports/M5_COMPLETION.md` does not exist. The authoritative completion
   evidence is `docs/IMPLEMENTATION_STATUS.md`, where M5 means the dashboard
   and the existing M6 means benchmarking.
5. No provider, deterministic provider, replay provider, provider-call store,
   structured AI protocol, repair turn, or app-server client exists.
6. No campaign/round/assignment/outcome entities exist. A run is the current
   top-level scientific unit.
7. Search is concurrent only as identical statically configured workers, not
   as independently versioned lanes.
8. Workers have useful state and checkpoints, but cannot accept patches,
   forks, resource changes, leases, or safe-boundary actions.
9. The master waits for all search to stop before exact verification. There is
   no bounded live M4 broker.
10. `state.json` is a UI snapshot, not an immutable Director snapshot with a
    committed ID, evidence allowlist, or high-water mark.
11. Existing pause/resume/stop controls are workspace-global file requests;
    there is no per-lane mailbox.
12. Current normal CLI and dashboard expose target, order, graph mode,
    algorithm, workers, seed, scoring cap, memory limits, and notes. M6 must
    add a separate campaign UX exposing only stop mode while retaining legacy
    `sglab run` for compatibility and controlled baselines.
13. Current normal terminal statuses include `NO_RESULT_WITHIN_BUDGET`,
    `UNKNOWN_MEMORY_LIMIT`, and `TOOL_FAILURE`; the M6 campaign contract needs
    separate scientific terminal and recoverable operational states.
14. Checkpoint resume exists for workers, but decision replay, campaign
    replay, research export, accepted-action reconciliation, and app-server
    thread resume do not.
15. Resource limits are global/static. There is no reviewed resource-share
    mapping or lane allocation.
16. The draft `007_active_director.sql` cannot be applied literally: it
    references campaign semantics absent from v1 and assumes pre-existing v6
    entities. It also omits a recoverable `paused_fault` terminal/state model.
17. The supplied action schema intentionally leaves several `spec` objects
    open. Production validation must narrow them to the two algorithms and
    three graph families actually implemented.
18. The sample action uses mutation operators not implemented by this target.
    The real catalog can initially expose only degree-preserving two-switch
    and the existing mixed/unrestricted moves, with numeric schedules actually
    supported by worker code.
19. The package asks to retain an M5 serial AI control for comparison, but no
    such implementation exists to preserve. Any serial-AI comparator added by
    M6 must be labeled as a new compatibility study adapter, not historical M5.
20. The existing hidden-witness/control target needed by live acceptance does
    not exist. It must be an explicitly non-open test target and must still
    certify through the unchanged M4 authority.
21. There is no authentication import, private Codex home, app-server
    preflight, isolation audit, protocol schema manifest, or session inspector.
22. The active environment is Python 3.14.5 although the production evidence
    was recorded with Python 3.12.10. The project supports 3.12+, so M6 tests
    must remain compatible with both rather than depending on 3.14-only APIs.
23. The untracked planning package makes repository dirty-state metadata true;
    M6 reports must distinguish this known input from implementation changes.
24. The package milestone name “M6” collides with the repository's completed
    benchmark milestone. Documentation must call the new work “M6 Active
    Director” without erasing the historical milestone record.

These are implementation mapping differences, not unresolved product choices.
The package already resolves provider type, persistence, authority, retention,
normal campaign input, and fault behavior.

## Phase 0 conclusion

The migration is feasible without rewriting the graph engine. The safe path
is additive:

- preserve `sglab run` as the legacy deterministic execution/baseline path;
- add an `sglab.research` package around the existing target, worker,
  checkpoint, certification, persistence, and HTTP boundaries;
- extract a micro-batch-capable worker kernel from the current worker rather
  than replacing graph/search logic;
- migrate schema v1 directly and additively to user version 7;
- make the app-server provider an isolated asynchronous control-plane process;
- keep Director inference outside every candidate-evaluation worker.

The concrete module-by-module sequence is in
`docs/reports/M6_IMPLEMENTATION_PLAN.md`.
