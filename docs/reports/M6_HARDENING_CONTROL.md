# M6.8 Control Target and Provider Resilience

Date: 2026-07-24

Status: offline milestone complete; M6 Active Director is not complete.

## Control target

`m6_hidden_witness_control_v1` is deliberately false and control-only. It
states that each connected cubic graph on ten vertices contains a triangle.
The witness is withheld from Director snapshots. The plugin shares the real
bounded graph generator and mutations, while its exact structural validation
requires order ten, connectedness, and degree three at every vertex.

Certification is target-aware. The Python reference DFS and independent C++17
bitset checker both receive length three. A persisted manifest must name both
complete implementations before the M4 broker can create
`succeeded_certified_counterexample`. Wrong-order objects are `INVALID`, not
success. The default production target remains `erdos_gyarfas`.

## Provider and growth hardening

- Three bounded app-server recovery attempts within 90 seconds.
- Same persisted thread resumed; no deterministic scientific takeover.
- Lane, verification, and action queues continue to be pumped during retry.
- Expired AI policy lease aborts retry and leads to `paused_fault`.
- Applied patch/restart/allocation actions renew the durable lane policy lease.
- Session rollover after 24 turns or 1,000,000 input tokens.
- Parent thread and compact durable rollover brief retained.
- Raw `tokenUsage` plus normalized last-turn categories persisted.
- Per-turn wire buffer drain and fixed 64-file diagnostic retention.
- Initial checkpoint best may enter the bounded archive.
- Candidate identity is campaign-scoped while graph hashes remain comparable.

## Verification

```text
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

Result: 81 tests passed in 13.622 seconds; compile checks passed. Focused tests
cover the real two-verifier positive control, broker-only success latch,
invalid control objects, provider retry, lease expiry, rollover lineage, wire
retention, and initial-checkpoint retention. All five repository gates passed;
the benchmark result is a smoke only, not the required two-hour soak.

## Remaining gates

No authenticated Director turn was used. The live intervention/restart
campaign, saved-rollout isolation audit, equal-budget multi-seed comparison,
and two-hour Active Director soak remain mandatory.
