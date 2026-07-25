# M7 third real comparison — deterministic preparation

Date: 2026-07-25

Tested commit: `76b6b33c15c8584003f780220b7080b320163de5`

Workspace: `workspace/model-comparisons-live`

## Prepared suite

- Suite name: `Luna high vs xhigh — A4 installed-wrapper rerun`
- Suite ID: `comparison-24c99e0539684b9ca488cdaba4f2486b`
- Status: `prepared`
- Authorization status: `unauthorized`
- Plan schema: `2.1`
- Plan fingerprint:
  `062bc657ccd45f56808b741c042a9685f0f8b7e7135b5cc5f7af2ce4edef1790`
- Resource accounting contract: version 2 on SQLite schema 13
- Fixture: `m6-executable-preserved-a4`
- Fixture SHA-256:
  `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77`

The suite was created and prepared through the rendered dashboard using
Playwright CDP. The rendered detail view and the protected safe comparison API
returned the same fingerprint, contracts, order, hashes, and limits. The
recomputed canonical plan fingerprint is identical to the stored value.

## Effective arm order

1. `Luna high`
   - arm ID: `arm-72342014dab94046869814ff2a48ffc0`
   - model: `gpt-5.6-luna`
   - reasoning effort: `high`
   - context: `stateless_turns`
   - repetition index: 0
   - fresh thread: true
   - resume prior thread: false
2. `Luna xhigh`
   - arm ID: `arm-a3d5c064486e458a808a10a259dc4441`
   - model: `gpt-5.6-luna`
   - reasoning effort: `xhigh`
   - context: `stateless_turns`
   - repetition index: 0
   - fresh thread: true
   - resume prior thread: false

Randomized ordering is persisted with seed `20260725`. The only intended
model/scientific contract difference is reasoning effort.

## Scientific-input equality

The prepared plan reports `fixture_equality.all_equal=true`. Both arms have
the following identical hashes:

- DirectorStateV2:
  `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77`
- prompt:
  `12bada6af03626bf10a3b5313a8e058e39555bf0083529ff72fd0fff91d004f7`
- output schema:
  `9147d4fcc81bcfbdfc986b71fa1f194cf4986b0d0ac4f5602228a4a9a966a400`
- base instructions:
  `bb79f9078bf017c9079d10fc1619dfe52072d58172977a7868b5201c2c37f151`
- developer instructions:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- campaign budget:
  `4766fb7b07941614d2b09868b95b853c36c363265624bc508cb8c706cf08398d`
- evidence registry:
  `2b15586edf1e512f9285af13f51d6b2897e154bba9c995404c9b92eaec88048c`
- advisory registry:
  `2c4d430e52710fa3345b6c27ce58573d6885455e4d869463e0a3025279f2d463`
- executable registry:
  `b594c18a0112206f01258ade6daa18b3e11935d20749b769c03736ac301f83f7`
- applicable action space:
  `437647c85fc5a970a0d49c381967ea7eb5b541c3ba2310a4fbd2c94abd43de8e`

The fixture is a single immutable source for both arms, so its target metadata
and status timestamp are also identical.

## Bounded runtime contract

- planned turns / inference starts: 2
- hard maximum inference starts: 2
- timeout: 300 seconds per turn
- maximum authoritative server tokens: 40,000
- client-owned estimated token limit per turn: 12,000
- fixture estimate per turn: 6,516
- worker wall-time limit: 7,200 seconds
- maximum concurrent suites: 1, from server policy
- measurement only: true
- execute decisions: false
- fail closed: true
- compaction: disabled
- inference-reaching retries: zero
- graph-search batches: zero
- returned-action dispatches: zero
- model tools: zero

Resource limits fingerprinted into the plan:

- preserved artifacts: 67,108,864 bytes
- runtime scratch: 536,870,912 bytes
- single preserved artifact: 33,554,432 bytes
- single runtime file: 268,435,456 bytes
- wire log: 8,388,608 bytes
- stderr: 262,144 bytes
- stdout: 1,048,576 bytes

The deprecated artifact-directory compatibility field maps only to
`max_preserved_artifact_bytes`; it is not also used as the scratch quota.

## Schema-v13 filesystem and process contract

The runtime policy is code-bound to the tested commit rather than supplied by
the browser or suite metadata. The schema-v13 worker:

- recognizes only `apply_patch`, `applypatch`, `codex-execve-wrapper`, and
  `codex-linux-sandbox` at the safe label
  `app-server-tmp/arg0/<wrapper-name>`;
- uses `lstat` and bounded `readlink` metadata without following or opening a
  symlink target for accounting;
- permits expected wrappers only when the server-owned trusted-target contract
  passes;
- fails unexpected external links as `filesystem_policy`, independently of
  byte accounting;
- emits a byte-quota failure only when the measured value is numerically above
  the configured limit.

The dashboard retains a bounded registry of worker `Popen` handles it owns and
polls those handles nonblockingly. It persists the reaping result and removes
the live registration without requiring dashboard shutdown or globally
reaping unrelated children.

## Deterministic gates

- SQLite schema: 13
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: no rows
- active comparison leases: 0
- new-suite authorizations: 0
- new-suite execution attempts: 0
- new-suite inference reservations: 0
- new-suite comparison turns: 0
- new-suite resource samples: 0
- new-suite private runtime roots: 0
- consumed inference starts: 0
- model inference: 0
- credential copies: 0
- graph-search batches: 0
- action dispatches: 0
- model tool calls: 0

The protected safe API response used for validation has SHA-256
`d1e76bccc24893fbb574c2cf2b8873e50d18135d1ee12e996f19fbffe1f6f206`.
It is retained only in the private temporary control-plane directory and is
not a credential artifact.

Both older failed suites remain terminal and unchanged. Their stored
fingerprints still recompute exactly, their consumed inference counts remain
one and zero respectively, and the second suite retains exactly twelve
historical resource samples.

## Authorization boundary

No authorization was created, the Authorize control was not clicked, the
Start control remained disabled, and no worker or private model runtime was
started. A fresh explicit authorization must name exactly the suite ID and
plan fingerprint above.
