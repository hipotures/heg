# M6 persistent score-pipeline optimization

Date: **2026-07-26**

## Outcome

The persistent C++17 scorer, conservative ILS/tabu early exit and
mutation-delta duplicate key passed their acceptance gates. Incremental
witness maintenance failed its eligibility gate and was not implemented.
Neither heuristic path changes M4 certification.

The reproducible raw artifact is
[`score-kernel-20260726T153107Z.json`](score-kernel-benchmarks/score-kernel-20260726T153107Z.json).
It was produced from clean commit
`b19587ecc866c9ea57fbed8215cb69f7eba80a9d` on an AMD Ryzen 9 7950X3D
with GCC 16.1.1. Seven pairs alternated execution order.

## Correctness and failure behavior

Tests compare C++ and Python counts, completeness flags and DFS-node counts
at graph orders 4, 8, 16, 32, 64, 96 and 128 across multiple witness and node
budgets. Deterministic Python/C++, early-exit on/off, legacy/fast-key and
profiling on/off comparisons preserve the same graph, score, RNG state,
accepted count and record count.

Every proposed C++ global record receives a full Python recount. Ordinary C++
evaluation is sampled every 4096 candidates. A killed child restarts once;
protocol errors, timeout, second failure or parity mismatch switch the lane to
Python. A worker failure is never a zero cycle count or certification result.

## Backend throughput

Workload: random restart, `witness_cap=2000`, 100 candidates per run.

| Order | Python median | C++ median | Speedup | Logical trajectory |
|---:|---:|---:|---:|---|
| 64 | 21.71/s | 187.52/s | **8.64×** | equal |
| 96 | 20.47/s | 253.29/s | **12.38×** | equal |

These values include Python audits of every proposed global record. The 2×
acceptance gate passed at both orders. There were no benchmark worker
restarts, fallbacks or parity mismatches.

## Early exit and duplicate key

At order 96 with 1000 ILS/tabu candidates:

| Comparison | Left median | Right median | Change | Logical trajectory |
|---|---:|---:|---:|---|
| full score → early exit | 237.43/s | 259.61/s | **+9.3%** | equal |
| SHA graph key → delta key | 256.41/s | 330.63/s | **+28.9%** | equal |

Early exit rejected 890 of 1000 candidates in every paired run. Median local
duplicate-key time fell from 0.866 s to 0.00865 s per batch, a 99.0% reduction.
The fast key is local non-authoritative bookkeeping; candidate IDs, graph6,
checkpoint hashes, archive semantics and canonicalization are unchanged.

## Profiling gate

With otherwise identical C++/early-exit/fast-key settings:

| Mode | Median throughput |
|---|---:|
| profiling off | 337.60/s |
| profiling on | 335.20/s |

Measured overhead was **0.71%**, below the 2% production gate, with identical
logical trajectories. Profiling therefore remains available and aggregates
only integer counters once per completed batch.

## Incremental-scoring decision

The final profiled 1000-candidate run reported:

| Length | Evaluated | Complete | Early cutoff |
|---:|---:|---:|---:|
| 4 | 1000 | 1000 | 0 |
| 8 | 1000 | 1000 | 0 |
| 16 | 1000 | 0 | 22 |
| 32 | 978 | 0 | 831 |
| 64 | 147 | 0 | 37 |

Across dominant C16/C32/C64 stages, 0 of 2125 recounts were complete (0%).
The eligibility requirement was 20%. Maintaining an edge-to-witness index
from incomplete enumerations could miss invalidated or newly created cycles,
change the score and alter the deterministic search trajectory. The decision
is therefore **deferred/no-go**.

## Reproduction

```bash
make score-worker
PYTHONPATH=src python -m sglab benchmark score-kernel \
  --iterations 7 \
  --backend-evaluations 100 \
  --search-evaluations 1000 \
  --output docs/reports/score-kernel-benchmarks
```

The artifact's cgroup peak belongs to the shared terminal scope and is not an
isolated benchmark RSS measurement. Process-local `ru_maxrss` was 315,908,096
bytes.
