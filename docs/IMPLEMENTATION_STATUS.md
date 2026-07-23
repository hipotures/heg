# Implementation Status

## Bundle state

This repository currently contains a specification and a minimal runnable scaffold.

### Implemented in scaffold

- configuration parser;
- immutable bitset graph representation;
- slow reference exact-cycle witness search;
- atomic state JSON;
- standard-library HTTP dashboard;
- basic doctor/init/serve/verify/smoke commands;
- small unit tests.

### Not yet implemented

- production search coordinator;
- simulated annealing and iterated local search;
- multiprocessing workers;
- SQLite schema and run archive;
- C++ cycle checker;
- CEGAR-SAT;
- nauty/SMS/Glasgow adapters;
- checkpoint/resume search state;
- production benchmarks and forecasts;
- full dashboard controls.

Codex must update this file after every milestone.
