# M6.4 Event-Driven Scientific Loop

Date: 2026-07-24

## Result

The offline event-driven coordination milestone passes. It demonstrates the
full deterministic control loop but does not substitute a scripted provider
for the required production Codex App Server provider. No M6 completion or
mathematical claim is made.

## Implemented boundary

- `triggers.py` coalesces events with debounce, mandatory maximum review, AI
  review contracts, candidate deltas, and critical-event bypass.
- `snapshot.py` writes bounded canonical research snapshot v3 artifacts and
  derives the exact semantic-validation context from the same state.
- `orchestrator.py` publishes snapshots and triggers, awaits a durable provider
  without stopping event processing, commits decisions optimistically, and
  delivers accepted actions.
- `effects.py` compares bounded pre/post telemetry windows and attaches
  measured outcomes to durable action outcomes.

SQLite and immutable snapshot artifacts remain authoritative. Conversation
memory is not used as campaign state.

## Snapshot contents and bounds

Each snapshot contains:

- stop mode, elapsed/remaining time, and campaign state version;
- immutable installed target hash and sole M4 success authority;
- CPU/memory/RSS and verifier queue summaries;
- at most 32 lanes with parameters, versions, leases, checkpoints, lineage,
  shares, and bounded telemetry;
- one structural global-best summary without an unbounded candidate stream;
- at most 64 recent actions and their expected/measured effects;
- at most 64 current hypotheses;
- at most 32 verification jobs;
- at most 512 exact admissible evidence IDs;
- a hard 256 KiB canonical payload limit.

The artifact byte count and SHA-256 stored in SQLite are computed over the
exact file bytes.

## Trigger behavior

Implemented sources include bootstrap, new global best, measured improvement
or regression, stagnation, diversity collapse, mutation-operator yield shift,
lane failure, action lease expiry, candidate delta, and maximum review
interval. Verifier-result/disagreement and resource-pressure reasons are
already mandatory/critical inputs for the M4/resource brokers added in later
milestones.

Critical events bypass debounce and the minimum interval. The Director may
select ordinary event types and intervals only within the reviewed schema; it
cannot disable fault, verifier, resource, or lease-safety triggers.

## Intervention measurement

For patch and restart interventions, the evaluator persists:

- pre and post lane-version window references;
- score-slope change;
- diversity and duplicate-rate change;
- throughput change;
- operator-yield change;
- candidate and wall deltas;
- whether the expected direction was observed.

The next snapshot includes this outcome beside the original expected effect.

## Focused active-loop gate

Command:

```text
uv run python -m unittest tests.test_orchestrator -v
```

Observed:

```text
Ran 1 test in 0.401s
OK
wall_seconds=0.49s
user_seconds=0.60s
system_seconds=0.07s
cpu_percent=137%
```

The deterministic durable scenario performs three turns:

1. bootstrap starts simulated annealing and iterated local search;
2. a delayed decision patches one and forks the other while candidate count
   continues increasing;
3. after persisted pre/post measurement, the next snapshot exposes the prior
   observed effect and the provider reallocates all live lanes.

The delayed second turn also reproduces and guards against checkpoint rotation
during inference by requiring its snapshot checkpoint to remain forkable.

## Regression gate

`make test`: 62 tests passed in 12.216 seconds.

`make check`: passed.

## Remaining work

- retained candidates, promotion, diagnostics, and bounded M4 queue;
- verifier and resource events connected to their real brokers;
- checkpoint/process/app-server crash recovery and scientific replay;
- operator campaign start/stop modes and deadline handling;
- HTTP/dashboard status and control surfaces;
- authenticated live app-server turn/restart proof;
- live AI acceptance campaign and two-hour soak.
