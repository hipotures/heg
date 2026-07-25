# M7 second real comparison preparation

Date: 2026-07-25

Tested implementation commit:
`e9ebe39e9ec51cec1002f4677c77eb1900a5ba9a`

## Outcome

The fresh bounded comparison is prepared and remains unauthorized:

- suite: `Luna high vs xhigh — A4 resource-accounting rerun`
- suite ID: `comparison-aaabfae5a010445e9d966ea50a0958a8`
- plan fingerprint:
  `a44e96f67628cb9afcacbc6c76b8f0e6e65696ba075a62c587d5f02b9b41c6d7`
- plan schema: `2.1`
- resource-accounting contract: `2`
- status: `prepared`
- authorization status: `unauthorized`
- inference starts consumed: `0`

No authorization, worker attempt, inference reservation, App Server turn,
private runtime home, search batch, model tool call, or returned-action
dispatch was created.

## Workspace and fixture

Workspace:
`/home/xai/DEV/heg/workspace/model-comparisons-live`

The workspace marker says `workspace_kind: model_comparison_live` and
`synthetic_data: false`. The database is schema v12, `integrity_check` is
`ok`, and `foreign_key_check` returned no rows.

Fixture:

- display name: `M6 executable preserved A4`
- fixture ID: `m6-executable-preserved-a4`
- fixture type: `campaign_snapshot`
- fixture SHA-256:
  `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77`
- estimated client-owned input per arm: 6,516 tokens
- configured client-owned limit per arm: 12,000 tokens

## Exact arm contracts and effective order

| Effective order | Arm ID | Display name | Model | Effort | Context | Thread |
|---:|---|---|---|---|---|---|
| 1 | `arm-14a8a736ee554229a793961f55b28b66` | Luna high | `gpt-5.6-luna` | `high` | `stateless_turns` | fresh |
| 2 | `arm-1429a6a782504ca2b8c56d5528fcd6d9` | Luna xhigh | `gpt-5.6-luna` | `xhigh` | `stateless_turns` | fresh |

Both arms have one repetition. They use independent conversation groups,
do not resume a prior thread, and do not compact.

## Bounded execution contract

| Limit or policy | Prepared value |
|---|---:|
| Planned turns | 2 |
| Hard maximum inference starts | 2 |
| Timeout per turn | 300 seconds |
| Total authoritative server-token cap | 40,000 |
| Client-owned estimated input cap per turn | 12,000 |
| Maximum concurrent suites | 1 |
| Worker wall time | 7,200 seconds |
| Ordering | randomized |
| Persisted seed | 20260725 |
| Measurement only | true |
| Execute decisions | false |
| Fail closed | true |

The maximum-concurrent-suites value is the fixed control-plane default. The
prepared plan fingerprints the suite-owned execution and resource limits.
The worker contract rejects retries reaching inference, model tool calls, and
compaction. Measurement-only execution creates no graph-search batch and
dispatches no returned action.

## Resource limits

| Category | Bytes |
|---|---:|
| Preserved artifacts | 67,108,864 |
| Runtime scratch | 536,870,912 |
| Single preserved artifact | 33,554,432 |
| Single runtime file | 268,435,456 |
| Wire log | 8,388,608 |
| Stderr | 262,144 |
| Stdout / JSONL | 1,048,576 |

The rendered page presents these as `Separated categories v2`; it does not
present the deprecated ambiguous artifact-directory label as the active
runtime contract. Controlled one-unit mutations of every listed byte quota
and the worker wall-time limit produced a different canonical plan
fingerprint.

## Scientific-input equality

The two arms have byte-identical scientific inputs:

| Material | SHA-256 |
|---|---|
| DirectorStateV2 | `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77` |
| Prompt | `12bada6af03626bf10a3b5313a8e058e39555bf0083529ff72fd0fff91d004f7` |
| Output schema | `9147d4fcc81bcfbdfc986b71fa1f194cf4986b0d0ac4f5602228a4a9a966a400` |
| Base instructions | `bb79f9078bf017c9079d10fc1619dfe52072d58172977a7868b5201c2c37f151` |
| Developer instructions | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Campaign budget | `4766fb7b07941614d2b09868b95b853c36c363265624bc508cb8c706cf08398d` |
| Evidence registry | `2b15586edf1e512f9285af13f51d6b2897e154bba9c995404c9b92eaec88048c` |
| Advisory registry | `2c4d430e52710fa3345b6c27ce58573d6885455e4d869463e0a3025279f2d463` |
| Executable registry | `b594c18a0112206f01258ade6daa18b3e11935d20749b769c03736ac301f83f7` |
| Applicable action space | `437647c85fc5a970a0d49c381967ea7eb5b541c3ba2310a4fbd2c94abd43de8e` |
| Target metadata | `4c358b3eb2fa244cfb1c1c00bb203d289af450a501d72f7817beaa801c81d46e` |
| Fixture | `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77` |

The target-metadata hash is the canonical SHA-256 of
`DirectorStateV2.target`. It is committed by the identical DirectorStateV2
hash; it is not a separate transport field. The only intended arm contract
difference is reasoning effort: `high` versus `xhigh`.

## Historical-suite preservation

The historical failed suite
`comparison-4407a28f8e7c47b89a7226045b61b1b4` remains terminal `failed`.
Its stored and recomputed fingerprint both remain
`89e09e8f82428e86f2a75ae24ff51f7187536c22c2ad023152dcb80b60512886`.
It still has one consumed inference start, Luna high remains completed, Luna
xhigh remains planned/not started, and it has no resource-telemetry rows.
No lease is active.

## Rendered UI and API verification

Playwright CDP created the draft through the rendered form and clicked only
`Prepare immutable plan`. The browser network record contains `POST` requests
only for suite creation and preparation; there is no authorize or start
request. The protected safe detail API returned HTTP 200 and confirmed the
same suite, arms, limits, hashes, zero starts, no attempt, and no lease.

Screenshots:

| Evidence | SHA-256 |
|---|---|
| [Suite configuration](m7-second-real-comparison-prep/suite-configuration.png) | `c2aef929165b8b4e40df4f4042a4a525eb67f80df308ecc337eb8462f05be14c` |
| [Prepared plan](m7-second-real-comparison-prep/prepared-plan.png) | `21815d2096505149b0fe950a68a5c5a882f23ae8d3fcf94ed5dd3badd5bdb251` |
| [Two arm contracts](m7-second-real-comparison-prep/two-arm-contracts.png) | `8f503138571619e4bef7dc5b2580dda27ecbc8aa8e7b027ad12de4ef030599ec` |
| [Inference cap](m7-second-real-comparison-prep/inference-cap.png) | `23bf358b2eb88c24e932a00b281f22c98419a5394486c0fb69531220315c5031` |
| [Resource limits](m7-second-real-comparison-prep/resource-limits.png) | `9d68366c375bc10a9b3f0db516c3b6fcb5396d3aebb3df70fa9b355a5f42eb59` |
| [Plan fingerprint](m7-second-real-comparison-prep/plan-fingerprint.png) | `412666106859762aa3144d31abea0e5a923af289b0bf8b10bedb66670a7c5651` |

The dashboard reports the credential source as configured and available while
exposing no path. Credential contents were not read or copied.

## Authorization boundary

All deterministic gates passed. The suite is prepared but not authorized.
No paid execution may begin without fresh explicit authorization bound only
to fingerprint
`a44e96f67628cb9afcacbc6c76b8f0e6e65696ba075a62c587d5f02b9b41c6d7`.
