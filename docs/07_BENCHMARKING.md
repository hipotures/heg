# Benchmarking and Cost Forecasting

## Purpose

Benchmarking must answer:

- which component dominates runtime;
- how throughput changes with graph order;
- how many workers are useful before memory or contention dominates;
- what a 24-hour and 7-day run can realistically evaluate;
- whether an exact frontier step is plausible on the current machine.

## Hardware metadata

Record:

- CPU model, core/thread count;
- RAM total;
- kernel;
- Python version;
- compiler version and flags;
- solver versions and commits;
- CPU governor;
- cgroup limits;
- storage filesystem and free space.

## Microbenchmarks

1. `BitGraph` edge queries and degree computation.
2. Legal cubic edge-swap generation.
3. Cheap score at `n=20,24,28,32,40,48,64`.
4. Exact cycle detection per length.
5. Canonical labeling.
6. graph6 encode/decode.
7. SQLite batch write.
8. one CEGAR iteration.
9. dashboard state serialization.

Report p50, p90, p95, maximum, and peak RSS.

## Search benchmark

For each algorithm and `n`:

- fixed wall time, for example 10 minutes;
- at least 5 seeds for serious comparison, 2 for smoke tests;
- candidates evaluated;
- legal-move rate;
- accepted-move rate;
- improvements;
- best score components;
- exact-verifier submissions;
- duplicate rate;
- CPU utilization;
- peak RSS.

## Active Director control study

The M6 hidden-witness control uses the same fixed envelope for static,
seeded-random, serial-AI compatibility, and Active app-server controllers:

```bash
sglab benchmark active-director-controls \
  --workspace ./workspace/m6-active-control \
  --output ./docs/reports
```

The full command uses five fixed seeds, a 60-second deadline per trial, at
most eight lanes, one verifier slot, and four Director turns. `--smoke` uses
two fixed seeds and ten seconds only for integration checks. It does not
accept scientific tuning flags. The serial arm pauses lanes while the same
app-server Director reasons because no historical M5 AI implementation
existed in the authoritative baseline. Reports never infer AI superiority.

## Soak test

Run for two hours with production-like worker count.

Pass conditions:

- RSS reaches a plateau or grows within a documented bound;
- database growth matches policy;
- workers can be recycled;
- pause/resume works;
- dashboard remains responsive;
- no queue grows without bound.

The implemented two-hour gate additionally requires zero worker failures,
observed worker recycling, monotonic candidate counters, post-resume progress,
queue occupancy within configured capacity, and SQLite growth no greater than
64 MiB during the run.

## Forecast model

### Heuristic search

Estimate:

```text
candidates_per_day = observed_candidates / observed_seconds * 86400
```

Scale by observed worker efficiency, not nominal core count.

### Exact cycle verification

Fit empirical time by order and length. Use ranges and quantiles. Long-cycle detection may be exponential and multimodal.

### SAT frontier

Do not use a linear extrapolation. Report:

- median and worst seed;
- conflicts and propagations;
- clause growth;
- empirical ratio between adjacent orders;
- optimistic, central, and pessimistic forecasts.

If adjacent-order runtime factors are unstable, state that no reliable forecast is available.

## Calibration command

The final implementation should provide:

```bash
sglab benchmark calibrate --minutes 15 --target erdos_gyarfas
```

Output:

- JSON data;
- Markdown summary;
- recommended worker count;
- 24-hour forecast;
- warning if exact verification dominates.

## Scientific reporting

A benchmark report must separate:

- throughput;
- search quality;
- exact-verification confidence;
- hardware cost;
- mathematical novelty.

High throughput alone is not a research result.
