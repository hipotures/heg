# Recorded Benchmark Results

These measurements are engineering evidence, not a result about the
Erdős–Gyárfás conjecture. Raw JSON and readable Markdown reports are retained
under `docs/benchmarks/`, including superseded and unsuccessful runs.

## Machine

- CPU: AMD Ryzen 9 7950X3D, 16 cores / 32 logical threads
- RAM: 201,412,857,856 bytes
- Kernel: Linux 7.0.10-1-MANJARO
- Python: 3.12.10
- C++: GCC 16.1.1, `-O3 -std=c++17`
- filesystem: btrfs
- CPU governor during measurement: `powersave`
- cgroup v2: available

The calibration was limited to 16 CPUs and the soak to 12 CPUs. Both retained
the configured 150 GiB high-water and 168 GiB hard memory limits.

## Current microbenchmark

Artifact:
[`micro-20260724T000057Z.json`](benchmarks/micro-20260724T000057Z.json).
Ten raw samples were retained for normal operations and three for the C++
subprocess check. Authoritative peak RSS was 21,585,920 bytes from a fresh
cgroup-v2 `memory.peak`.

Selected p50 values:

| Operation | p50 |
|---|---:|
| cubic mutation, `n=32` | 35.51 µs |
| capped score, `n=32` | 6.316 ms |
| capped score, `n=64` | 9.052 ms |
| Python exact check, easy `n=20` witness | 11.75 µs |
| C++ subprocess, same easy graph | 3.395 ms |
| canonical fallback, `n=32` | 136.12 µs |
| SQLite batch of 100 rows | 99.49 µs |
| tiny `n=4` CEGAR ground truth | 41.20 µs |

The easy verifier case finds a forbidden cycle almost immediately, so C++
process startup dominates. The helper is therefore an independent finalist
verifier, not part of candidate ranking. The canonicalization values use the
explicitly non-authoritative fallback because nauty is absent on this host.

The immediately preceding
[`micro-20260723T235832Z.json`](benchmarks/micro-20260723T235832Z.json)
retains valid operation timings but is marked superseded for peak-memory
reporting because inherited `ru_maxrss` included earlier launcher children.

## Current 15-minute calibration

Artifact:
[`calibration-20260723T235735Z.json`](benchmarks/calibration-20260723T235735Z.json).

Sixteen independent processes covered two deterministic seeds for every
combination of `n ∈ {20,24,28,32}` and both baseline algorithms. All 16 cases
ran for 900.000–900.020 seconds. The cgroup peak was 298,078,208 bytes.

Overall per-process throughput quantiles were:

- p50: 633.97 candidates/s;
- p90: 771.96 candidates/s;
- p95 and maximum: 787.64 candidates/s.

Forecasts intentionally use only the novel `n=32` frontier measurements, not
the much faster validation orders:

| Frontier statistic | candidates/s |
|---|---:|
| minimum | 63.24 |
| p50 | 65.21 |
| p90 / p95 / maximum | 67.11 |

Adjacent-order work factors were:

- `20 → 24`: 1.265;
- `24 → 28`: 0.820;
- `28 → 32`: 10.715.

Their non-monotonicity is evidence against pretending that four orders define
a reliable exponential runtime law.

The throughput-only frontier forecast is:

| Horizon | Pessimistic, one worker | Central, 12 workers | Optimistic, 12 workers |
|---|---:|---:|---:|
| 24 hours | 5.634 million | 67.608 million | 69.583 million |
| 7 days | 39.438 million | 473.257 million | 487.081 million |

These counts describe capped heuristic evaluations only. They do not predict
SAT or hard exact-verification time; both may be heavy-tailed and are not
linearly extrapolated.

The prior
[`calibration-20260723T234022Z.json`](benchmarks/calibration-20260723T234022Z.json)
is retained as superseded evidence because its forecast pooled validation
orders with the `n=32` frontier.

## Passing two-hour soak

Artifacts:
[`soak-20260724T020219Z.json`](benchmarks/soak-20260724T020219Z.json) and
[`soak-20260724T020219Z.md`](benchmarks/soak-20260724T020219Z.md).

The production soak used `n=32`, 12 workers, and ran for 7,201.986 seconds.
It passed every encoded gate:

- automatic `PAUSE` and `RESUME` were observed;
- the candidate counter stopped during the pause and advanced afterward;
- 3,734,333 candidates were recorded in the final sample;
- 180 controlled worker restarts and zero worker failures;
- all 1,439 dashboard probes returned HTTP 200;
- telemetry and exact queues remained bounded at capacity 256;
- sampled aggregate master-plus-worker peak RSS was 356,032,512 bytes;
- the RSS plateau test passed;
- SQLite grew by only 266,240 bytes and ended near 4.37 MiB;
- process exit code was 0;
- final status was `NO_RESULT_WITHIN_BUDGET`.

The earlier 7.2-second functional soak remains as smoke evidence. The
265-second interrupted attempt is also retained and explicitly marked failed;
neither is substituted for the passing two-hour artifact.
