# Witness-counting follow-up plan

Date: **2026-07-24**

Implementation outcome: the persistent C++17 option, conservative early exit
and delta-based local duplicate key were accepted on 2026-07-26. Incremental
witness maintenance was deferred because its completeness gate failed. See
`docs/reports/M6_SCORE_PIPELINE_OPTIMIZATION.md`.

## Measured baseline

The reproduced Phase-B ILS configuration previously spent 94.3% of its search
loop in Python forbidden-cycle witness counting. In the adaptive campaign the
corresponding shares were approximately 86.9% for B1, 80.3% for B2 and 80.1%
for B3. SQLite and telemetry construction were each near one millisecond per
batch. Optimization should therefore target witness evaluation, while leaving
the M4 exact-verifier boundary unchanged.

## Options

| option | expected throughput | complexity | verification risk |
|---|---|---|---|
| current Python enumeration | 1.0× reference | low | low |
| incremental update after a two-edge switch | estimated 2–5× | high | high |
| cheap screen, exact recount for promising candidates | estimated 1.5–3× | medium | medium |
| persistent C++17 bitset witness worker | estimated 3–10× kernel speed | medium/high | medium |

The speed ranges are engineering estimates, not benchmark results.

### Incremental recomputation

A two-edge switch changes only four endpoints, but cycles can include those
edges and otherwise remote vertices. A correct implementation needs indexed
witness membership and careful invalidation by forbidden length. Missed
invalidation would change acceptance and global-record ordering. Prototype
only behind periodic full Python recounts and fail closed on disagreement.

### Exact recount for promising candidates

Use a conservative cheap bound to reject obviously poor mutations, then run
the current exact score count before accepting a move or recording a global
best. This can preserve acceptance semantics only if the cheap stage never
rejects a candidate that could beat the applicable threshold. Measure filter
selectivity and prove decision equivalence on deterministic seeds.

### Persistent C++17 bitset worker

The project permits one small C++17 helper where profiling justifies it. A
persistent process avoids per-candidate startup overhead and can batch compact
adjacency bitsets. It should return counts and optional witnesses, while Python
remains the oracle during rollout. Bound IPC queues, request sizes, resident
memory and timeouts. A worker timeout is `UNKNOWN`, never cycle absence.

## Recommended measured sequence

1. Freeze the current Python kernel as correctness and throughput baseline.
2. Prototype the persistent C++ exact counter behind a feature flag.
3. Run deterministic graph-by-graph parity against Python across accepted,
   rejected and record mutations before timing it.
4. Benchmark IPC batch sizes and cap 64 versus cap 10000.
5. Evaluate the conservative two-stage exact-recount design only if the C++
   path does not meet the desired throughput.
6. Defer incremental witness-set maintenance until profiling demonstrates that
   exact C++ recount remains insufficient.

No option replaces either exact verifier, changes timeout semantics or permits
a mathematical claim from heuristic scores.
