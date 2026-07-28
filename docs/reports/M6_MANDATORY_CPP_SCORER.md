# M6 Mandatory C++ Heuristic Scorer

Date: 2026-07-28

## Acceptance contract

- exactly one production heuristic scorer: persistent optimized C++;
- no Python heuristic scorer, shadow mode, backend switch or scoring fallback;
- conservative early exit and the fast duplicate key for new work;
- one bounded worker restart, then fail closed;
- M4 exact verification unchanged.

## Implemented evidence

- Removed the Python count-only DFS workspace and all `cheap_score` plugin
  methods.
- Ported both campaign lanes and the legacy search runner to the persistent
  C++ worker.
- Versioned the bounded worker protocol so targets supply their reviewed cycle
  lengths, including the control target's triangle length.
- Removed backend-selection environment handling and Python/C++ comparison
  modes from the benchmark.
- Runtime and batch provenance now identify only the C++ implementation.
- Focused tests cover the single-backend contract, worker reuse, one restart,
  repeated-failure closure and C++ counts against the independent witness
  enumerator.

## Verification

The required repository gates are recorded in the task commit. No campaign
database or historical execution evidence was modified.
