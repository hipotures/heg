# Implementation Status

Last implementation audit: **2026-07-23**.

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

## Remaining

- M2 search coordinator and algorithms;
- M3 profiled fast verifier path;
- M4 optional CEGAR-SAT;
- M5 complete dashboard;
- M6 benchmark and forecast reports;
- M7 optional external-tool adapters.

Engineering completion is not a mathematical result. No counterexample or
exhaustive nonexistence claim has been made.
