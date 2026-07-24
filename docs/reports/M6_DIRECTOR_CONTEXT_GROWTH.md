# DirectorStateV2 bounded-growth validation

Date: **2026-07-24**

## State contract

`DirectorStateV2` is the only scientific state included by the production
Director prompt builders. Its version is `2.0`; the checked-in schema is
`M6_DIRECTOR_STATE_V2_SCHEMA.json`.

It contains:

- target statement ID, immutable definition hash, state and status timestamp;
- elapsed, remaining and evaluation budgets;
- currently implemented action/algorithm/parameter space;
- best result;
- latest outcome and at most two previous outcome summaries;
- plateau, operator aggregates and timing percentages;
- exact-verifier status and parameter effects;
- previous hypothesis, expected signal and measured boolean;
- at most eight record summaries and eight accepted final-best ancestors;
- source, outcome and candidate IDs/hashes.

It excludes full graph bodies, full ancestry, complete raw outcomes, raw and
validated decision pairs, checkpoints, RNG state, metric windows, prompts and
SQLite rows. Full outcome artifacts remain immutable and addressable by hash.

## Hard pre-turn gate

Before `turn/start`, the application persists one size report containing both
pre-compaction and post-compaction measurements. Limits are:

| section | limit |
|---|---:|
| serialized Director state | 32 KiB |
| ancestry | 8 KiB |
| historical outcomes | 12 KiB |
| estimated client-owned input | 12,000 tokens |

Client input is conservatively estimated as
`ceil((baseInstructions + prompt + output schema UTF-8 bytes) / 4)`. This is
explicitly an estimate, not server tokenizer output. An over-limit state is
compacted deterministically by retaining only the newest bounded information.
If state or estimated client input still exceeds its limit, the request aborts
before inference.

## Preserved Phase-B states

Applying V2 to the four exact preserved Phase-B snapshots gives:

| state | old snapshot | V2 state | V2 ancestry | V2 history | estimated total client input |
|---:|---:|---:|---:|---:|---:|
| A1 | 4,545 | 3,033 | 65 | 2 | 6,501 tokens |
| A2 | 91,227 | 12,678 | 5,584 | 2 | 8,969 tokens |
| A3 | 192,771 | 14,750 | 5,629 | 1,798 | 9,530 tokens |
| A4 | 246,329 | 16,655 | 5,611 | 3,593 | 10,045 tokens |

All four fit every hard limit. A4 scientific state falls from 246,329 bytes to
16,655 bytes, a 93.2% reduction. These are deterministic serializer
measurements; they are not predictions of server input tokens on a persistent
thread.

## One-hundred-batch replay

The deterministic audit appended 100 batch outcomes derived from the four
preserved Phase-B state shapes. It ran identically for all three context modes.

Results:

- maximum submitted V2 state: 16,682 bytes;
- final submitted V2 state: 16,682 bytes;
- outcomes submitted: exactly 3;
- record ancestry: at most 8;
- accepted final-best ancestry: at most 8;
- last-20 size range: 1,461 bytes, caused by rotating bounded outcome shapes;
- last-20 maximum did not exceed the first-20 maximum by more than 1 KiB;
- all newest outcome hashes remained correlated;
- JSON round-trip/restart reconstruction was identical;
- all four preserved replay decisions still passed the existing action
  validator and schema;
- the fourth decision remained final analysis and did not create a fourth
  batch.

The submitted scientific state is therefore bounded rather than linear in
campaign length. Persistent server-side conversation history is outside replay
visibility and is reported separately.

## Deterministic verification

- focused context/protocol tests: passed;
- all 109 pre-existing tests: passed once with the production changes;
- the final 110-test run, after adding the restart-mode test, passed 109 tests
  and exposed the existing timing-sensitive
  `test_static_control_runs_in_real_lanes_and_retains_metrics`: its 50 ms lane
  window occasionally produced zero evaluations under concurrent host load;
- that unchanged test passed immediately when run alone;
- `make doctor`, `make check`, `make benchmark-smoke` and
  `make dashboard-smoke`: passed;
- an SQLite Online Backup snapshot of the preserved Phase-B database returned
  `integrity_check: ok` at `user_version: 8`.

The timing flake is not caused by Director context code, but it remains an
exact test-suite uncertainty rather than being hidden as a clean final run.
No authentication file, app-server runtime, model turn or preserved runtime
artifact was modified.
