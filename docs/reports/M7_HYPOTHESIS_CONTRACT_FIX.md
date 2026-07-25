# M7 hypothesis and independent-arm contract fix

Date: 2026-07-25  
Baseline commit: `6f7a04c8fc65576cee3483a5e7ea1c7e93948bba`  
Workspace: `workspace/model-comparisons-live`

## Outcome

The Director hypothesis-update contract is now operation-specific and shared
by the prompt, generated structured-output schema, and semantic validator.
New measurement-only comparison plans also persist and fingerprint an explicit
policy that continues after an invalid independent model result while
preserving fail-closed behavior for infrastructure failures and dependent
persistent arms.

No model inference, credential access, authenticated turn, graph search, or
Director action dispatch occurred.

## Preserved Luna-high response

The preserved raw response for
`comparison-24c99e0539684b9ca488cdaba4f2486b` contains:

```json
{
  "path": "$.hypothesis_updates[1].hypothesis_id",
  "operation": "revise",
  "hypothesis_id": "H0"
}
```

The exact submitted scientific state had an empty hypothesis registry.
`revise` acts on an existing hypothesis, so `H0` was unknown. This was not a
valid `create` rejected by a client-contract mismatch. Offline validation
therefore correctly remains invalid with:

```text
$.hypothesis_updates[1].hypothesis_id: must reference an existing hypothesis
```

For the same empty registry, the new generated schema exposes only the
`create` branch. The preserved `revise(H0)` response is consequently rejected
structurally before semantic validation in future turns. The historical
suite, raw response, and original validation record were not altered.

Preserved response SHA-256:
`743f8ecdb463e6221bd135e1a54b9a11a148e06d9c1c4958281d5e97e8c455b2`.

## Unified hypothesis contract

- `create`: the ID must not exist in the submitted registry and must be unique
  among creations in the response.
- `confirm`, `weaken`, `reject`, `retain`, and `revise`: the ID must be in the
  exact submitted hypothesis registry.
- Duplicate creation and revision of an unknown ID are invalid.

The generated schema uses operation-specific `anyOf` branches. `oneOf` and
cross-item uniqueness are not used because they are outside the currently
reviewed strict structured-output subset. The create/existing distinction and
the exact existing-ID enumeration are structural; duplicate creation remains
a semantic check.

## Comparison-arm result policy

New suites store
`arm_failure_policy=independent_invalid_continue_v1`. The policy is part of
plan schema 2.2 and therefore part of the plan fingerprint:

- schema-invalid or semantic-invalid independent response: persist the result
  and continue to the next independent arm;
- infrastructure, security, protocol, resource, or model-contract failure:
  block later arms fail-closed;
- persistent arm requiring prior success: block it unless its predecessor
  completed;
- returned actions: never execute.

Historical suites retain a null policy, plan schema 2.1, their original
behavior, and their exact stored and recomputed fingerprints.

## Persistence and historical evidence

Schema v14 adds one nullable `comparison_suites.arm_failure_policy` column.
A v13 snapshot made with SQLite Online Backup migrated to v14 with
`integrity_check=ok` and no foreign-key violations. The canonical hash of all
historical comparison records, excluding only the newly added nullable
column, was identical before and after migration:

```text
851b087f56e993acdac7337210383a76c2b961486c5a439569d3ce1be7318b8b
```

All three terminal historical suites retain null policy and exact
fingerprints:

| Suite | Status | Consumed starts | Stored and recomputed fingerprint |
|---|---:|---:|---|
| `comparison-4407a28f8e7c47b89a7226045b61b1b4` | failed | 1 | `89e09e8f82428e86f2a75ae24ff51f7187536c22c2ad023152dcb80b60512886` |
| `comparison-aaabfae5a010445e9d966ea50a0958a8` | failed | 0 | `a44e96f67628cb9afcacbc6c76b8f0e6e65696ba075a62c587d5f02b9b41c6d7` |
| `comparison-24c99e0539684b9ca488cdaba4f2486b` | failed | 1 | `062bc657ccd45f56808b741c042a9685f0f8b7e7135b5cc5f7af2ce4edef1790` |

The latest suite still records Luna high as `semantic_invalid`, Luna xhigh as
not started, zero executed actions, and no active lease.

Historical evidence hashes remained:

- worker log:
  `8165e111d28b08821c2446a6c91fc1f9e95467e6e6284e27e200f79093eb2ced`;
- runtime report Markdown:
  `c89da80568a6d679147c84dbdedaf010013f246f4d4b766d0f7c8dd79d4bdb3d`;
- runtime report JSON:
  `ab88b3de23025d34b4e82f617d5da88749eb930438c23fcb54a30676d34a3b10`.

## Deterministic verification

Focused tests cover:

- create with a new ID;
- revise with an existing ID;
- revise with an unknown ID;
- duplicate create;
- schema-invalid and semantic-invalid first independent arms followed by a
  completed second arm;
- infrastructure failure blocking the second arm;
- an invalid persistent predecessor blocking its dependent arm;
- zero action batches and zero action dispatches.

Completed gates:

- focused protocol/director/comparison/worker tests: 84 passed;
- complete safe suite: 236 passed;
- `make doctor`;
- `make test`;
- `make check`;
- `make benchmark-smoke`;
- `make dashboard-smoke`;
- SQLite v13-to-v14 Online Backup migration;
- SQLite `integrity_check`: `ok`;
- SQLite `foreign_key_check`: no rows;
- strict installed App Server protocol audit without `turn/start` or model
  inference.

## Final status

```text
preserved_response_operation: revise
preserved_response_offline_revalidation: invalid; unknown existing-hypothesis ID H0; rejected structurally by the new empty-registry schema
hypothesis_create_contract_fixed: true
existing_hypothesis_operations_enforced: true
independent_invalid_arm_continues: true
infrastructure_fail_closed_preserved: true
historical_suites_unchanged: true
zero_model_inferences: true
ready_for_first_real_graph_campaign: true
```
