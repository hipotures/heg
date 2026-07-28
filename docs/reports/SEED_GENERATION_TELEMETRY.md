# Seed-Generation Telemetry Acceptance

Date: 2026-07-28

## Scope

Issue #2 adds observation only. It does not optimize or replace a generator,
change retry budgets or graph-family semantics, or alter mutation, scoring,
acceptance, archive, provenance, checkpoint continuation, or M4 authority.

## Implemented contract

- initial lane, automatic restart, explicit restart, and random-restart
  candidate sources are distinct;
- success/failure, internal attempts, retry budget, elapsed time, and four
  bounded failure categories are recorded;
- fixed attempt/time histograms expose p50/p95/p99 estimates per batch,
  cumulatively, and per source;
- telemetry is persisted in metric windows and a separately hashed checkpoint
  envelope;
- checkpoint restore does not increment generation counters;
- `seed_generation_efficiency` compares lane/family/order retry pressure and
  runtime share;
- disabled instrumentation uses the original direct generator call.

## Validation

Focused tests cover first-attempt success, exact forced retries, both bounded
construction-exhaustion categories, invalid configuration, implementation
failure, all sources, restore exclusion, bounded aggregation, batch/cumulative
consistency, deterministic instrumentation parity, Resume replay identity,
and cross-lane/order diagnostics.

## Representative benchmark

One 100-call local sample reported:

| Workload | Baseline seeds/s | Instrumented seeds/s | Overhead | Measured runtime in generator |
|---|---:|---:|---:|---:|
| cubic, order 20 | 18,241 | 16,716 | 9.13% | 67.85% |
| mixed-degree, order 21 | 4,178 | 4,139 | 0.95% | 91.20% |
| random-restart cubic, order 20 | 18,920 | 17,968 | 5.30% | 67.34% |

All generated graph sequences and final RNG states matched their
uninstrumented controls. Attempt and elapsed histograms each remained fixed at
13 buckets. These wall-clock samples are noisy evidence, not a hard throughput
gate; the disabled path performs no trace allocation or histogram work, and
non-seed mutation/scoring behavior is unchanged.

## Final gates

All required gates passed:

- focused seed/recovery/schema/context/diagnostic/benchmark tests;
- `make doctor`;
- `make test`;
- `make check`;
- `make benchmark-smoke`;
- `make dashboard-smoke`;
- `git diff --check`.
