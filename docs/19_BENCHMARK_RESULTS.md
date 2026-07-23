# Recorded Benchmark Results

These measurements are engineering evidence, not a result about the
Erdős–Gyárfás conjecture.

## Machine

- CPU: AMD Ryzen 9 7950X3D, 16 cores / 32 logical threads
- RAM: 201,412,857,856 bytes
- Kernel: Linux 7.0.10-1-MANJARO
- Python: 3.14.5
- C++: GCC 16.1.1, `-O3 -std=c++17`
- CPU governor during measurement: `powersave`
- cgroup v2: available

## Microbenchmark

Artifact:
[`micro-20260723T213054Z.json`](benchmarks/micro-20260723T213054Z.json).
Five raw samples were retained for every operation and order.

Selected p50 values:

| Operation | p50 |
|---|---:|
| cubic mutation, `n=32` | 37.9 µs |
| capped score, `n=32` | 792.7 µs |
| Python exact check, easy `n=20` witness | 13.7 µs |
| C++ subprocess, same easy graph | 3.78 ms |
| SQLite batch of 100 rows | 108.7 µs |
| atomic state serialization | 53.5 µs |
| tiny `n=4` CEGAR ground truth | 41.1 µs |

The easy verifier case finds a forbidden cycle almost immediately. C++ process
startup therefore costs far more than the Python DFS. This result prevents
using the helper in the candidate-ranking loop without a harder-case profile.
The C++ path remains useful as an independent finalist verifier.

## 15-minute parallel calibration

Artifact:
[`calibration-20260723T215711Z.json`](benchmarks/calibration-20260723T215711Z.json).

The gate ran 16 independent processes: two deterministic seeds for each
combination of `n ∈ {20,24,28,32}` and the two baseline algorithms. Every case
ran for 900.000–900.003 seconds.

- aggregate per-process throughput p50: 1,277.5 candidates/s;
- p90: 1,387.4 candidates/s;
- measured `n=32` range: 990.4–1,015.6 candidates/s;
- recommended production search workers: 12;
- observed peak RSS of the calibration coordinator: 28,639,232 bytes;
- no candidate was presented as a counterexample.

Adjacent-order throughput factors were:

- `20 → 24`: 1.073
- `24 → 28`: 0.953
- `28 → 32`: 1.311

The non-monotone middle factor shows that these four points do not support a
reliable exponential runtime model.

The throughput-only forecast ranges are:

| Horizon | Pessimistic | Central (12 workers) | Optimistic |
|---|---:|---:|---:|
| 24 hours | 110.4 million | 1.325 billion | 1.438 billion |
| 7 days | 772.6 million | 9.272 billion | 10.069 billion |

The pessimistic figure is deliberately single-worker. Central and optimistic
figures assume linear scaling to 12 workers; a production run must validate
that assumption from aggregate telemetry.

These counts cover capped heuristic evaluations only. They do not predict SAT
frontier time or hard exact-cycle verification. Both may be heavy-tailed, so
the implementation refuses a linear SAT extrapolation.

## Soak evidence

A short functional soak exercised `PAUSE → RESUME`, worker recycling, bounded
queues, SQLite growth, finalist verification, and state polling. It reached a
stable approximately 51 MiB combined master/worker RSS and completed with
`NO_RESULT_WITHIN_BUDGET`. The 7.2-second raw smoke artifact is
[`soak-20260723T215936Z.json`](benchmarks/soak-20260723T215936Z.json).

This short result is not the two-hour memory gate. Use:

```bash
sglab benchmark soak \
  --hours 2 \
  --order 32 \
  --workers 12 \
  --workspace ./workspace-soak \
  --output ./workspace-soak/benchmarks
```

The generated JSON contains raw RSS/database samples, control actions,
recycling settings, final process status, and the plateau decision.
