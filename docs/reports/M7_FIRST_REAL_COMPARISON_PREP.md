# M7 First Real Comparison — Deterministic Preparation

Date: 2026-07-25  
Phase: A only  
Result: **all deterministic gates passed; paid execution is not authorized**

## Prepared exact suite

- Name: `Luna high vs xhigh — A4 worker smoke`
- Suite ID: `comparison-4407a28f8e7c47b89a7226045b61b1b4`
- Status: `prepared`
- Authorization: `unauthorized`
- Plan fingerprint:
  `89e09e8f82428e86f2a75ae24ff51f7187536c22c2ad023152dcb80b60512886`
- Canonical fingerprint recomputation: matched
- Effective randomized order for seed `20260725`:
  1. `arm-9a0c4225502c4959973bffe2101201a5` — Luna high
  2. `arm-f95c90d663ff45b9b0b6e846c609df9c` — Luna xhigh

The suite was created from the rendered New comparison suite page and prepared
with the rendered lifecycle control through Playwright CDP. The safe comparison
API was then read from the authenticated browser session. `Authorize exact
plan` was not clicked, `Start authorized suite` remained disabled, and no
worker command was invoked.

## Immutable arm contract

| Order | Arm | Model | Effort | Context | Repetitions |
|---:|---|---|---|---|---:|
| 1 | Luna high | `gpt-5.6-luna` | `high` | `stateless_turns` | 1 |
| 2 | Luna xhigh | `gpt-5.6-luna` | `xhigh` | `stateless_turns` | 1 |

Both arms use a fresh thread. Their DirectorStateV2, prompt, base instructions,
empty developer instructions, structured output schema, evidence registry,
advisory registry, executable registry, applicable action space, campaign
budget, and fixture hashes are identical. The only scientific/runtime contract
difference is reasoning effort. Arm IDs, labels, and persisted order are
administrative identifiers.

## Bounds

- Measurement only: `true`
- Execute decisions: `false`
- Fail closed: `true`
- Timeout per turn: 300 seconds
- Planned and maximum inference starts: 2
- Maximum authoritative server tokens: 40,000
- Client-owned input limit per turn: 12,000
- Fixture estimate per turn: 6,516
- Expected search batches: 0
- Expected action dispatches: 0
- Expected model tools: 0
- Expected compactions: 0
- Retries reaching inference: 0

The production worker rejects compacted execution before auth access, supplies
empty tool/capability roots, rejects tool and retry notifications, and stops
later arms after the first fail-closed failure.

## Executable preserved A4 fixture

- Display name: `M6 executable preserved A4`
- Fixture ID: `m6-executable-preserved-a4`
- Type: `campaign_snapshot`
- Fixture/DirectorStateV2 SHA-256:
  `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77`
- Preserved source scientific snapshot SHA-256:
  `db1bf0e0049cbae497e975e932a12e7493d5c9b4ba654cc0267b3ee97746476a`
- Source report SHA-256:
  `97d6fdeabedc159725730bc06ffa3025fd75e0ac3e1b1649bd2ed8ce393faa1d`
- Fixture-bundle file SHA-256:
  `637a767672cb6e569814554283711ab7c614830a63d8c31158467ef6f2a0f86d`

The source snapshot and destination copy have the same byte hash. The
production fixture loader passed its complete `verify_only` path, including
all material-hash checks and Director decision-context reconstruction. No auth,
rollout, wire log, session, normal Codex home, or private runtime path occurs in
the workspace marker or scientific fixture artifacts.

## Workspace and repository integration

The dedicated destination is
`workspace/model-comparisons-live`, marked:

```text
workspace_kind: model_comparison_live
synthetic_data: false
source_workspace: first-ai-search-auth-20260724-01
schema_version: 11
```

It was constructed through a read-only SQLite Online Backup plus a fresh
schema-v11 destination, not a plain SQLite file copy. The source research
workspace remains unchanged. Final database checks report
`integrity_check = ok` and no foreign-key violations.

Tested code commit:
`3979af3b9675feefcedb34dda930bdcd136dba2a`.
It contains both the bounded worker baseline
`04aec06fa5847dd79d0efac55f991e10f375e30d` and the final semantic UI commit
`25920da`, integrated through merge `825ddc7`.

## Phase-A zero-side-effect evidence

At the authorization boundary the dedicated database contains:

| Record class | Count |
|---|---:|
| comparison authorizations | 0 |
| inference reservations | 0 |
| comparison turns | 0 |
| execution attempts | 0 |
| worker leases | 0 |
| comparison runtime campaigns | 0 |
| research lanes | 0 |
| Director action batches | 0 |
| Director actions/outcomes | 0 / 0 |

Consumed inference starts and server tokens are both zero. No `auth.json`
content was read or copied. Only source availability was configured and
reported as a boolean by the dashboard.

The dashboard is bearer-protected and bound only to `127.0.0.1:8788`. During
browser authentication diagnosis the first short-lived dashboard bearer was
visible in tool diagnostics; the server was stopped and that bearer was
rotated before Prepare. The invalidated value and the current bearer are
excluded from screenshots and reports.

## Verification

- Focused fixture, comparison-worker, persistence, HTTP, and UI tests: passed
- `make doctor`: passed
- `make test`: 194/194 passed
- `make check`: passed
- `make benchmark-smoke`: passed
- `make dashboard-smoke`: passed
- Schema version: 11
- SQLite integrity: `ok`
- Foreign-key violations: 0
- Rendered Playwright workspace/suite/plan/progress verification: passed
- Safe comparison API plan verification: passed

## Rendered evidence

- [Workspace confirmation](m7-first-real-comparison-prep/workspace-confirmation.png)
- [Exact suite form](m7-first-real-comparison-prep/suite-form.png)
- [Prepared immutable plan](m7-first-real-comparison-prep/prepared-plan.png)
- [Inference-limit summary](m7-first-real-comparison-prep/inference-limit-summary.png)
- [Machine-readable safe plan artifact](M7_FIRST_REAL_COMPARISON_PREP.json)

## Authorization boundary

Phase B has not started. Fresh explicit user authorization is required before
copying the single configured auth file into suite-specific private runtime
homes, authorizing the exact fingerprint, starting either arm, or performing
any authenticated inference.
