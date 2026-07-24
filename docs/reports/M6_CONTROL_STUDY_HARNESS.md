# M6 Equal-Budget Control Study Harness

Date: 2026-07-24

Status: offline harness complete; authenticated comparison results pending.

## Delivered

The hidden-witness study now runs four controllers through the same campaign,
lane, candidate, action, telemetry, SQLite, and M4 verification boundaries:

1. seeded static deterministic control;
2. seeded random admissible-action control;
3. serial-AI compatibility control;
4. production Active app-server Director.

The authoritative pre-M6 repository did not contain the M5 AI provider assumed
by the planning package. The serial arm is therefore an explicit compatibility
construction: it uses the same persistent app-server Director, typed action
contract, and exact verifier as M6, but pauses all lanes for the entire
Director turn. It is never selected as a production fallback.

Each trial has the same fixed wall deadline, maximum eight active lanes, one
M4 verifier slot, four-Director-turn budget, and twelve-action schema cap per
turn. The normal `research-campaign start` interface remains unchanged and
does not expose controller, graph, algorithm, lane, seed, mutation, or cadence
parameters.

The report retains every trial and failure plus:

- time and success at the M4 latch;
- best-score time area and candidate throughput;
- unique structures and verified finalist yield;
- applied, stale, rejected, and evaluated interventions;
- uplift/regret summaries from measured effect windows;
- provider token categories and wall time;
- an explicitly labeled share-time CPU-hours proxy.

No superiority claim is generated. The full default uses five fixed seeds;
`--smoke` uses two fixed seeds and a ten-second deadline solely as an
integration gate.

## Commands

```text
sglab benchmark active-director-controls \
  --workspace ./workspace/m6-active-control \
  --output ./docs/reports

sglab benchmark active-director-controls \
  --workspace ./workspace/m6-active-control \
  --output ./workspace/m6-active-control/smoke-report \
  --smoke
```

Both commands require the explicit private auth import because two arms use
the real app-server provider. They write `M6_BENCHMARK_RESULTS.json` and
`M6_BENCHMARK_RESULTS.md`.

## Offline evidence

A 15-second static-control integration run used two real concurrent spawned
lanes and the real M4 broker. It ended in
`succeeded_certified_counterexample` after three controller turns, with one
two-verifier certification and both lane processes durably stopped. The
focused test suite also proves that the full study refuses to create a
campaign before explicit auth is present.

All five repository gates pass:

```text
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

The full repository suite contains 84 passing tests.

The required four-controller multi-seed result remains pending; this report is
implementation evidence only.
