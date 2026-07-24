# M6.7 Operator Campaign and Dashboard

Date: 2026-07-24

Status: offline milestone complete; M6 Active Director is not complete.

## Delivered

- Production composition root for the direct persistent Codex App Server
  provider, event-driven coordinator, concurrent lanes, candidate archive,
  diagnostics, and M4 broker.
- Foreground single-coordinator lock, separate monotonic campaign controls,
  deadline latch, emergency pause/resume/stop, crash resume, and automatic
  reproducibility export after M4 success.
- Normal CLI start with exactly one choice: `--time-limit` or
  `--until-success`.
- Read-only installed target and no normal order, algorithm, worker, seed,
  mutation, resource-allocation, or cadence inputs.
- Bounded read-only campaign status API and standard-library dashboard panels
  for Director/session/turn usage, hypotheses, actions/effects, lanes,
  revisions, telemetry, verifier state, resources, and faults.
- Legacy `sglab run` and `/api/runs` retained for backward compatibility but
  removed from the normal campaign form.

## Safety properties exercised

- Explicit authentication is checked before campaign creation.
- Unknown HTTP campaign fields and CLI tuning flags are rejected.
- Deadline and operator-stop code cannot request the M4 success state.
- Emergency controls are evaluated while the Director turn runs as an
  asynchronous task.
- SQLite remains the single authoritative writer; dashboard status uses a
  read-only connection.
- Export continues through SQLite Online Backup and excludes authentication.

## Verification

```text
PYTHONPATH=src python3 -m unittest tests.test_campaign -v
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

Result: all five repository gates passed. The 74-test suite completed in
13.467 seconds; compile checks, microbenchmark smoke, and dashboard smoke
passed. This is a smoke measurement, not the required two-hour Active Director
soak.

## Remaining gates

No credential was copied and no authenticated inference was attempted in this
milestone. M6.1 live persistence/isolation, the hidden-witness active-control
campaign, equal-budget controller comparison, provider-outage hardening, and
the two-hour Active Director soak remain required before completion.
