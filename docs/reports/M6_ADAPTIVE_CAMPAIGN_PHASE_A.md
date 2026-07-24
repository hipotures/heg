# M6 adaptive campaign — deterministic Phase A

Date: 2026-07-24  
Starting commit: `105e2afde91333866b6dae7d37d40632353c322c`

## Safety boundary

Phase A performed no model inference, did not read or copy `auth.json`, and did
not start `codex app-server`. The accepted historical no-model compliance
artifact remained unchanged. Its SHA-256 is
`ca958f832af1c5c30ac32477930b280fc4df8ea0567906e0d32f9f03676fae7e`.
The live compliance command was deliberately not rerun because it starts the
installed app-server, which this phase explicitly forbids.

## Decision semantics

`promotion_penalty` is now described only as campaign-ranking metadata and is
absent from executable lane parameters. `restart_threshold` is executable
only for simulated annealing; ILS-tabu decisions containing it are rejected.
Every accepted action is enriched before persistence with
`effective_parameters`, `ignored_parameters`, `rejected_parameters`,
`parameter_effects`, and the selected algorithm's implemented controls.
Unsupported non-null parameters are rejected rather than discarded.

Mutation weights accept only `uniform_two_edge_switch` and
`forbidden_cycle_break_switch`, require non-negative weights and a positive
sum, and are normalized locally before persistence and execution. The uniform
policy preserves the former legal switch. The targeted policy selects a
detected forbidden-cycle witness, removes an edge of that witness, selects a
vertex-disjoint remote edge, and accepts only a simple, connected, cubic
rewiring.

## Replay integration

The deterministic `ai-experiment phase-a` command now executes:

```
A1 → B1 → O1 → A2(O1) → B2 → O2 → A3(O1,O2) → B3 → O3
   → A4(O1,O2,O3) → stop
```

The preserved assertions are:

- four replay turns and four committed decision batches on one replay thread;
- exactly three lane metric windows, each limited to 300 evaluations;
- a durable zero-evaluation application event before every search kernel;
- O1 in A2, O1/O2 in A3, and O1/O2/O3 in A4, correlated by action ID and
  outcome-artifact hash;
- A4 persisted without a fourth metric window;
- bounded ancestry (64 accepted ancestors per retained candidate);
- dashboard visibility for decisions, parameters, progress, and outcomes;
- `PRAGMA integrity_check = ok`.

Snapshots expose timing, witness-time percentage, best evaluation, plateau
inputs, records, acceptance, duplicates, diversity, operator uses/acceptance/
records/yield, final-best ancestry, exact verification, witness truncation,
actual restart state, parameter semantics, hypotheses, expected signals, and
measured outcomes. Checkpoints, graph bodies, raw RNG state, duplicated raw
metrics, and rejected candidates are excluded from Director snapshots.

## Order-20 mutation benchmark

Command source: `run_mutation_policy_benchmark(evaluations=300)`. All cases
used seed `24072026`, ILS-tabu tenure 48, perturbation interval 200, and exact
final reference verification. The raw local JSON had SHA-256
`618ad49abf3d7926a669d75c115201e471a8a1316338a28cff81bec4952dffb9`.
Numbers below are one deterministic smoke run, not evidence of statistical
superiority.

| cap | policy | instr. | cand/s | witness % | accepted | records | yield | best | truncated |
|---:|---|:---:|---:|---:|---:|---:|---:|---|:---:|
| 64 | uniform | on | 701 | 93.7 | 52 | 13 | .0433 | 3 / 48 | yes |
| 64 | uniform | off | 722 | n/a | 52 | 13 | .0433 | 3 / 48 | yes |
| 64 | targeted | on | 521 | 57.2 | 42 | 11 | .0367 | 4 / 48 | yes |
| 64 | targeted | off | 537 | n/a | 42 | 11 | .0367 | 4 / 48 | yes |
| 64 | mixed | on | 581 | 80.0 | 41 | 17 | .0567 | 3 / 48 | yes |
| 64 | mixed | off | 596 | n/a | 41 | 17 | .0567 | 3 / 48 | yes |
| 10000 | uniform | on | 463 | 96.3 | 37 | 17 | .0567 | 5 / 72 | no |
| 10000 | uniform | off | 457 | n/a | 37 | 17 | .0567 | 5 / 72 | no |
| 10000 | targeted | on | 351 | 66.6 | 41 | 12 | .0400 | 3 / 48 | no |
| 10000 | targeted | off | 360 | n/a | 41 | 12 | .0400 | 3 / 48 | no |
| 10000 | mixed | on | 407 | 85.6 | 47 | 13 | .0433 | 3 / 48 | no |
| 10000 | mixed | off | 409 | n/a | 47 | 13 | .0433 | 3 / 48 | no |

Every final candidate was `REJECTED` by the exact reference verifier because
a forbidden cycle remained. Cap-64 counts were truncated somewhere during
each search and therefore are not represented as exact. The targeted
operator's additional witness selection is timed under mutation generation;
the witness percentages above measure score witness counting only.
Instrumentation changed throughput by roughly 0–3% in these short runs, while
the witness cap and targeted selection dominated the differences. Peak RSS
was about 28.1 MiB.

For the first authenticated campaign, the Director should receive both caps,
all three weight presets as evidence rather than mandates, the full per-stage
timing, truncation flag, plateau signal, per-operator statistics, and the
bounded final-best ancestry. Three batches cannot establish statistical
superiority.

## Verification

- focused integration tests: 24 passed;
- complete Phase-A-safe suite: 103 passed;
- excluded test:
  `InstalledAppServerComplianceTests.test_strict_config_rejects_unknown_field`
  because it starts the real installed app-server;
- `make doctor`: passed;
- `make check`: passed;
- `make benchmark-smoke`: passed;
- `make dashboard-smoke`: passed;
- replay database `PRAGMA integrity_check`: `ok`;
- deterministic Phase A: `ok: true`, no failures, 4 turns, 3 batches.

`make test` and the live compliance command were not invoked verbatim because
both would execute the excluded real-app-server path, contradicting the
explicit Phase A prohibition. All other tests in the discovered suite ran.
