# M6 score-kernel optimization

Date: **2026-07-26**

## Scope

This gate changes only heuristic evaluation of one candidate. It does not
change batch size, checkpoint semantics, SQLite schema, live-frontier
publication or either M4 verifier.

The production hot path now counts bounded cycles with an iterative
integer-bitset DFS and reuses one traversal workspace per lane. The
witness-returning enumerator remains the correctness oracle.

## Correctness

Deterministic tests compare count, completeness and full `ScoreResult` against
the prior bounded witness enumerator across multiple graph orders, limits and
DFS budgets. Profiling-on and profiling-off runs produced identical best
graphs, scores and trajectories.

Profiling stores only integer nanoseconds and DFS-node counts in memory during
the batch. One aggregate payload is constructed at the batch boundary.

## Throughput gate

Workload:

```text
algorithm=random_restart
seed=7262027
order=64
witness_cap=2000
batch_candidates=100
instrumentation=false
```

| implementation | samples (candidates/s) | median |
|---|---|---:|
| `11a2903` bounded witness enumeration | 18.5334, 18.5699, 18.4351 | 18.5334 |
| iterative count-only workspace | 24.4137, 24.1540, 24.4915 | 24.4137 |

Median throughput improved by **31.7%**. The acceptance threshold was 20%.

## Profiling-overhead gate

Five profiling-on/off pairs used the same workload and alternated execution
order. All other instrumentation remained enabled.

| mode | candidate-evaluation seconds | median |
|---|---|---:|
| profiling on | 4.1981, 4.2240, 4.1817, 4.1677, 4.2159 | 4.1981 |
| profiling off | 4.1504, 4.1868, 4.1585, 4.2213, 4.2514 | 4.1868 |

Measured median overhead was **0.27%**, below the 2% production gate.
Profiling therefore remains enabled by default and can be disabled through
`search_limits.score_profiling_enabled`.
