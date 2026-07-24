# M6.3 Concurrent Stateful Lanes

Date: 2026-07-24

## Result

The offline M6.3 lane-runtime milestone passes. This is an implementation and
integration result, not an M6 completion claim and not a mathematical result.

## Implemented boundary

- `src/sglab/research/lanes.py` owns long-lived spawned lane processes,
  micro-batches, safe-boundary mailboxes, deterministic checkpoints, target
  selection, seed lineage, telemetry, and bounded retention.
- `src/sglab/research/actions.py` delivers only previously committed reviewed
  actions and translates worker events back into the single-writer store.
- `src/sglab/research/telemetry.py` provides bounded summaries, score slopes,
  diversity, duplicate rate, throughput, operator yield, and pre/post effect
  comparisons.
- `src/sglab/research/store.py` atomically records lane births, revisions,
  multi-lane allocations, outcomes, checkpoints, and rotating metric windows.
- The legacy deterministic `sglab run` path is unchanged.

## Safety and reproducibility

- maximum active lane count is enforced before process creation;
- each lane has a 512 MiB default `RLIMIT_AS`;
- event and command queues are bounded;
- checkpoint JSON is hashed, atomically replaced, and bounded by per-lane and
  pinned-action retention;
- telemetry is bounded both in memory and SQLite;
- integer parameter domains are type checked;
- graph order cannot be hot-patched;
- model actions contain no code, command, SQL, executable, URL, or path;
- stale worker commands are rejected by `expected_lane_version`;
- action application occurs after a checkpoint boundary;
- accepted action IDs are not delivered twice;
- fork children derive deterministic seeds from action and child IDs while the
  parent continues searching.

## Focused integration gate

Command:

```text
uv run python -m unittest tests.test_lane_actions -v
```

Observed:

```text
Ran 1 test in 0.248s
OK
wall_seconds=0.34s
user_seconds=0.41s
system_seconds=0.08s
cpu_percent=146%
```

The gate:

1. commits and starts simulated-annealing and iterated-local-search lanes;
2. observes both processes making candidate progress;
3. commits a parameter patch to one live lane;
4. forks the other from an exact retained checkpoint;
5. verifies the parent advances while the child starts;
6. atomically reallocates reviewed shares across all three lanes;
7. restarts one lane and safely stops another;
8. verifies lane versions, outcomes, bounded metric rows, and SQLite integrity.

`tests.test_lanes` separately holds a simulated Director-inference window open
while polling telemetry and asserts that total candidate count continues to
increase.

## Regression evidence

The final milestone gate ran `make test` after the compatibility and retention
tests were added: 58 tests passed in 11.692 seconds. `make check` also passed.

## Deliberate remaining work

- event coalescing, snapshots, and asynchronous Director scheduling;
- archive-elite restart and retained-candidate promotion through the bounded
  candidate/M4 broker;
- effect-window persistence and next-turn intervention evaluation;
- campaign crash recovery from durable lane checkpoints;
- campaign CLI, HTTP API, dashboard, exports, and replay;
- authenticated app-server live turns and restart/resume proof;
- one live acceptance campaign and the required two-hour soak.
