# M7 comparison UI — deterministic engineering milestone

Date: 2026-07-25

## Baseline

The implementation started at
`110f805e56fac39c241bd33e423ee00324c33caf`. The annotated tag
`m6-context-optimization-proven` points to that exact baseline. The preserved
M6 context report was not modified; its SHA-256 remains
`a1f01415059494161b5c0d9feb608160e48afff1e3b23404e234eec87f27883c`.

The proven result remains:

- stateless input reduction: `24.800062725419476%`;
- stateless total-token reduction: `7.01805988587564%`;
- both A4 decisions schema-valid and semantically valid;
- completion reliability: `both_completed`;
- recommendation: `stateless_turns`;
- recommendation basis: `single controlled S2/P2 pair`.

No preserved runtime report or context-screen artifact was rewritten.

## Implementation

Schema v10 adds comparison fixtures, suites, arms, turns, authorizations,
manual ratings, blind pairwise ratings, and immutable cost-profile snapshots.
An authenticated comparison turn can reference the existing
`app_server_turns` lifecycle row instead of duplicating it. Historical
campaign/session/turn records are not rewritten.

The production Director default is now `stateless_turns`. Explicit
`persistent_thread` and `compacted_thread` remain accepted. New explicit
persistent campaigns emit the required token-growth warning. Campaigns,
sessions, and turns persist the effective context mode and fresh/resumed
thread provenance. Replay and rule providers retain their prior behavior.

The configured catalog contains Luna and Sol with `medium`, `high`, and
`xhigh`; an absent pair is rejected. Effective model/effort/context preflight
is persisted and a mismatch fails before inference.

The standard-library dashboard now provides:

- `GET /comparisons`
- `GET /comparisons/new`
- `GET /comparisons/<suite-id>`
- `GET /comparisons/<suite-id>/blind`
- `GET /model-cost-profiles`
- all required bearer-protected JSON `POST` endpoints.

All suite decisions are forced to `measurement_only=true`,
`execute_decisions=false`, and `executed=false`. Browser payloads cannot set
an auth path or command. Model, effort, context mode, fixture ID, numeric
limits, and text are locally validated. Servers bind to `127.0.0.1` in tests
and shut down cleanly.

Usage accounting treats cached input and reasoning output as subsets and
keeps the server total authoritative. Relative multipliers are editable.
API-equivalent estimates appear only with explicit rates and are not described
as subscription charges.

The historical importer produced:

| slot | contract | input | total | semantic | selected action |
|---|---|---:|---:|---|---|
| S2 | Luna xhigh / stateless | 9,591 | 15,806 | valid | `request_diagnostic` |
| P1 | Luna xhigh / persistent | 4,405 | 6,498 | valid | `start_lane` |
| P2 | Luna xhigh / persistent | 12,754 | 16,999 | valid | `schedule_verification` |

The imported suite is read-only and marked
`runtime_executed_elsewhere=true`. It contains no private paths, credential
hashes, rollout content, or wire logs.

## Deterministic evidence

The replay-only dry run created three planned arms, three simulated turns
(two completed and one failed), two manual rating revisions, one blind
pairwise rating, and one cost-profile snapshot. It recorded:

- model inferences: `0`;
- auth access: `0`;
- search batches: `0`;
- lanes: `0`;
- action dispatches: `0`;
- decision execution: `0`;
- SQLite integrity: `ok`;
- missing usage retained as `null`.

Authorization requires an exact plan fingerprint. A changed model/effort plan
is detected before start and invalidates the authorization. Fail-closed
sequencing blocks later arms after a failed earlier arm. The inference cap
cannot be exceeded and no arm can acquire a replacement turn.

## Verification

- focused comparison tests: `19/19` pass;
- complete suite, pass 1: `153/153` pass;
- complete suite, pass 2: `153/153` pass;
- `make doctor`: pass;
- `make check`: pass;
- `make benchmark-smoke`: pass;
- `make dashboard-smoke`: pass;
- loopback comparison and existing dashboard HTTP tests: pass;
- default bind: `127.0.0.1`;
- server shutdown: clean;
- SQLite schema: `10`;
- SQLite `integrity_check`: `ok`;
- migration from earlier schemas: pass using temporary databases/Online
  Backup tests.

Three legacy dispatch tests initially depended on a lease expiring at
`2026-07-25T00:00:00Z`. Their test-only leases now use an explicitly future
date so they deterministically exercise an active contract.

The complete suite's installed App Server compliance check only tested strict
configuration rejection and did not start an authenticated turn. No model
inference, auth read/copy, paid comparison, graph-search batch, compaction, or
tool call occurred during this milestone.

## Limitations

This milestone implements the durable comparison control plane and web state
machine. It intentionally does not perform an authenticated comparison.
Running plans still require a future, separately authorized bounded worker.
The recommendation is based on one controlled pair and is not a claim of
statistical superiority. Visual redesign remains deferred.

## Final status

```text
stateless_default_enabled: true
persistent_mode_preserved: true
comparison_schema_created: true
comparison_web_ui_created: true
model_effort_catalog_created: true
cost_profiles_created: true
usage_accounting_correct: true
manual_ratings_created: true
blind_pairwise_created: true
historical_context_result_imported: true
authorization_bound_to_plan: true
measurement_only_enforced: true
zero_model_inferences: true
zero_auth_access: true
zero_search_batches: true
http_tests_passed: true
sqlite_integrity_check: ok
ready_for_user_created_comparisons: true
```
