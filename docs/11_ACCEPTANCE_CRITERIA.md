# Acceptance Criteria

## M0

- package installs;
- `doctor`, `init`, and `serve` work;
- state snapshots are atomic;
- dashboard smoke test passes.

## M1

- graph invariants validated;
- graph6 round trip;
- reference exact-cycle detector passes known cases;
- target verifier returns witnesses and explicit unknowns.

## M2

- simulated annealing and iterated local search implemented;
- fixed seeds reproduce trajectories within documented tolerance;
- pause/resume/checkpoint works;
- no unbounded memory in two-hour soak.

## M3

- fast exact verifier is independently cross-checked;
- machine-readable protocol;
- final certification can run without a heuristic timeout.

## M4

- CEGAR-SAT reproduces small ground truth;
- learned clauses are witness-backed;
- timeout remains unknown;
- CNF and metadata are preserved.

## M5

- dashboard shows live metrics and archived candidates;
- controls are safe and validated;
- no arbitrary shell execution;
- binds locally by default.

## M6

- 15-minute calibration report;
- microbenchmark and scaling data;
- 24-hour and 7-day forecast ranges;
- recommended concurrency.

## Scientific acceptance

A claimed counterexample requires:

- exact target audit;
- two independent verifiers;
- clean-room artifact reproduction;
- current literature/status check;
- complete graph export and hashes.
