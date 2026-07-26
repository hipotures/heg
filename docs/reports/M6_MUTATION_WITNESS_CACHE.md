# M6 current-graph witness cache

Date: **2026-07-26**

## Outcome

The one-entry current-graph witness cache for
`forbidden_cycle_break_switch` passed its correctness, throughput and
profiling-overhead gates. It is enabled in the lane kernel and does not alter
M4 verification.

The reproducible raw artifact is
[`score-kernel-20260726T213242Z.json`](score-kernel-benchmarks/score-kernel-20260726T213242Z.json).
It was produced from clean commit
`e22b2e5bb35cfae9d1b5788ddc43b44821f054b7` on an AMD Ryzen 9 7950X3D.
Seven old/new pairs alternated execution order.

## Production profile that selected the work

The last six order-96 production windows before this change reported:

- 247–757 candidates/s per lane;
- mutation generation at 63.6–84.9% of accounted search time;
- score witness counting at 8.0–29.6%;
- 10–30% configured forbidden-cycle-targeted mutations.

The targeted operator independently called the bounded Python witness
enumerator on the unchanged current graph. Higher targeted weight corresponded
to lower throughput, making this a separate post-C++ bottleneck rather than a
regression in the persistent scorer.

## Cache contract

- The cache contains only the ordered witness-edge choices for one immutable
  current graph.
- Rejected candidates retain it.
- An accepted move, new seed or checkpoint restart invalidates it immediately.
- It is process-local and is never serialized, checkpointed, logged or written
  to SQLite.
- Cache population uses the existing bounded Python traversal.
- Selection still calls `rng.choice()` at the same point over the same ordered
  choices, preserving RNG consumption and deterministic continuation.

Cache on/off tests compare graph, score, best graph, best score, RNG state,
accepted count, improvement count and operator statistics.

## Controlled benchmark

Workload: order 96, connected cubic, simulated annealing, 1,000 candidates,
30% `forbidden_cycle_break_switch`, persistent C++ scorer, fast duplicate key,
seven alternating pairs.

| Measurement | Cache off | Cache on | Change |
|---|---:|---:|---:|
| median throughput | 186.82/s | 261.58/s | **+40.0%** |
| mutation-generation time | baseline | measured | **−72.65%** |
| witness-search time | baseline | measured | **−78.52%** |
| witness searches / 301 targeted moves | 301 | 67 | **−77.74%** |
| cache hits | 0 | 234 | 77.74% hit rate |
| logical trajectory | reference | equal | pass |

The required gates were at least 25% throughput improvement, at least 50%
mutation-time reduction and identical logical trajectories. All passed.

## Profiling contract

The mutation profile consists only of fixed in-memory integer accumulators for
operator evaluations/nanoseconds, witness searches/nanoseconds and cache
hits/misses. One aggregate `timing.mutation_profile` is materialized at batch
completion. Disabling score profiling removes this payload and its accumulator
updates.

The same full benchmark measured:

| Mode | Median throughput |
|---|---:|
| profiling off | 328.78/s |
| profiling on | 328.89/s |

The calculated overhead was **−0.03%**, measurement noise below the 2% gate,
with an identical trajectory.

## Earlier score-pipeline gates

The full run also rechecked the earlier optimizations:

- Python to persistent C++: 9.42× at order 64 and 19.71× at order 96;
- conservative early exit: 1.095×;
- fast duplicate key: 1.151×;
- optimized legacy key: 1.133×;
- independent-sample provenance: 1.330×;
- every compared trajectory remained equal.

Incremental witness maintenance remains `deferred_no_go`; its completeness
gate still fails.

## C++ witness-extension decision

The planned persistent-worker witness response was conditional on the
one-entry cache failing to remove enough cost. Since the cache delivered 1.40×
total throughput and removed 72.65% of mutation time without changing the
worker protocol, the protocol extension is deferred. A later profile may
reopen it if the remaining 67 cache misses per 1,000 candidates become
dominant.

## Reproduction

```bash
make score-worker
PYTHONPATH=src python -m sglab benchmark score-kernel \
  --iterations 7 \
  --backend-evaluations 100 \
  --search-evaluations 1000 \
  --output docs/reports/score-kernel-benchmarks
```
