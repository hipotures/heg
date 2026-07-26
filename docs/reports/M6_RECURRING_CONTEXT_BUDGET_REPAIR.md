# M6 recurring Director context-budget repair

Date: 2026-07-26

## Reproduced production fault

Campaign:

```text
campaign-b68ec445388e49b2be0b6fabf8ff6600
```

The fifth recurrence was reconstructed from persisted context-budget artifact
`app-turn-98794e43540d4c12a7a28f6b4f21d275.json` and committed scientific-memory
snapshot `snapshot-d2049d5081814c3a872804a000b754e2.json`. No inference, model
authentication, campaign Resume, action dispatch, or verifier job was used.

| Component | Bytes |
|---|---:|
| base instructions | 682 |
| prompt | 39,384 |
| output schema | 27,284 |
| complete request | 67,350 |
| estimated tokens | 16,838 |
| `DirectorStateV2` | 32,738 |

The old complete-request pass calculated a 28,364-byte state target. The
non-droppable projection could not fit there, so the one-shot compactor
reported `DirectorStateV2 remains oversized after deterministic compaction`
and abandoned all otherwise-safe reduction.

## Root cause

There were two independent sources:

1. an impossible ideal state target was incorrectly treated as proof that no
   smaller safe projection existed;
2. the outer prompt duplicated `allowed_action_space` and all 64 recently
   reserved action IDs even though the durable store already validates
   workspace-scoped collisions.

The irreducible safe-state floor for this snapshot is 28,876 bytes. It
preserves exact-verifier outcomes and all current executable IDs.

## Repair

Complete-request budgeting now:

1. targets 15,000 estimated tokens, below the unchanged 16,000 hard gate;
2. applies the exact excess plus 1 KiB headroom;
3. when that target is infeasible, binary-searches deterministically for the
   tightest feasible state;
4. rebuilds the prompt, registries, validation context, and output schema;
5. records the search targets and recovered state limit;
6. still rejects the request before inference if the final hard gate fails.

The prompt points to `director_state_v2.allowed_action_space` and supplies the
reserved-action count, namespace rule, and durable collision authority instead
of replaying the full reserved-ID list.

## Acceptance result

Replaying the same production snapshot through the repaired preflight produced:

| Measurement | Before | After |
|---|---:|---:|
| `DirectorStateV2` bytes | 32,738 | 28,876 |
| prompt bytes | 39,384 | 31,110 |
| output schema bytes | 27,284 | 27,284 |
| complete request bytes | 67,350 | 59,076 |
| estimated tokens | 16,838 | 14,769 |
| within 15,000 soft target | no | yes |
| within 16,000 hard gate | no | yes |

The floor search tested 12 deterministic byte targets and recovered the exact
28,876-byte safe floor. Focused tests verify that one byte below the recovered
limit fails, the prompt omits the durable ID list, request budgeting stays
within the hard gate, and invalid-response repair reuses the exact submitted
state.

The locally installed Codex App Server protocol audit also passed without an
authenticated turn. This fault was therefore isolated to client-owned prompt
construction and compaction, not the App Server transport.
