# First AI-Directed Search — Phase A

Date: **2026-07-24**

Baseline commit: **d0db3095b051b2f5bbcadde92d2b5a7341e8e271**

## Result

The deterministic no-model integration gate passed:

- provider: `ReplayDecisionProvider`;
- authenticated model calls: `0`;
- validated and persisted Director decisions: `2`;
- bounded graph-search batches: `1`;
- evaluations: `300`;
- algorithm: `simulated_annealing`;
- graph family: `connected_cubic`;
- graph order: `10`;
- seed: `20260724`;
- termination: `evaluation_limit`;
- SQLite `integrity_check`: `ok`;
- failures: none.

The first decision and its application event were committed while the
recorded graph-evaluation count was zero. Only then was the search kernel
created. The batch outcome was persisted and appeared as the observed effect
in the exact second snapshot consumed by the replay Director. The second
decision was validated and committed but never dispatched.

The campaign status backing the minimal dashboard exposed all four required
views: the Director assessment, active search parameters, batch progress and
the final measured outcome. A focused HTTP integration test passed outside
the sandbox restriction on loopback sockets.

The one-batch primitive also has deterministic focused coverage for all three
algorithms admitted by the authenticated experiment contract:
`random_restart`, `simulated_annealing`, and
`iterated_local_search_tabu`. The former `iterated_local_search` identifier is
retained for backward compatibility.

## Preserved evidence

The ignored workspace report is:

```text
workspace/first-ai-search-phase-a/integration-2/phase-a-report.json
```

It records the decision and snapshot identifiers, complete batch metrics,
reference-verifier outcome, dashboard gates and the locally calibrated
conservative evaluation cap. The subsequent no-model app-server compliance
report also passed with `ok: true`, `failures: []`, strict startup, zero
post-reload active skills and separate private homes.

Phase B remains unexecuted. No auth file was read or copied and no model turn
was performed.
