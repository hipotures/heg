# M6 complete Director request-budget repair

Date: 2026-07-26

## Reproduced failure

Campaign:

```text
campaign-b68ec445388e49b2be0b6fabf8ff6600
```

Attempt 8 stopped before a new Director action or verifier job with:

```text
DirectorContextBudgetExceeded
client-owned context estimate exceeds 16000 tokens
```

The persisted context report showed:

| Component | Bytes |
|---|---:|
| base instructions | 682 |
| prompt | 37,927 |
| output schema | 25,641 |
| complete request | 64,250 |
| estimated tokens | 16,063 |
| `DirectorStateV2` | 32,722 |

`DirectorStateV2` was 46 bytes below its own 32,768-byte limit, so the old
state-only condition recorded `compaction_applied: false` and rejected the
complete request.

## Repair

The model-facing action space now submits compact target-ID lists and a lane
lifecycle map instead of a six-field object for every reference.
`build_reference_registries()` derives the same lifecycle and
evidence/advisory/executable roles from those values.

After the normal state limit, the Director measures base instructions, prompt,
and output schema together. If that total exceeds the 16,000-token estimate,
it computes:

```text
next state limit =
    current state bytes - exact excess bytes - 1 KiB headroom
```

It then performs deterministic policy-aware reduction and rebuilds the prompt,
registries, validation context, and output schema. It never starts inference
from an over-limit request. Exact-verifier outcomes and current executable IDs
remain non-droppable.

## Production-workspace verification

A consistent snapshot was made with SQLite `.backup`; no plain database copy
was used.

```text
PRAGMA integrity_check;   -> ok
PRAGMA foreign_key_check; -> no rows
```

Rebuilding latest snapshot
`snapshot-f137df1e22ac4a66a35652da5489d853` produced:

| Measurement | Before | After |
|---|---:|---:|
| `DirectorStateV2` bytes | 32,722 | 26,315 |
| complete request bytes | 64,250 | 57,843 |
| estimated tokens | 16,063 | 14,461 |
| within 16,000 gate | no | yes |

Reference-role parity:

| Registry | Old IDs | New IDs | Missing | Added |
|---|---:|---:|---:|---:|
| evidence | 60 | 60 | 0 | 0 |
| advisory | 43 | 43 | 0 | 0 |
| executable | 37 | 37 | 0 | 0 |

The focused request-level regression starts one fake Director turn only after
compaction, verifies the persisted context report is within the gate, and
checks that all 64 synthetic hypothesis IDs plus an exact-verifier outcome
survive the reduction.

## Repair-turn follow-up

Production attempt 11 later exercised the invalid-response repair path after
complete-request compaction. The first turn was within budget:

| Measurement | Value |
|---|---:|
| derived state target | 31,099 bytes |
| submitted `DirectorStateV2` | 31,077 bytes |
| complete request estimate | 15,739 tokens |
| first-turn status | `completed_invalid` |

Before starting repair inference, the old recursion rebuilt the source
snapshot at the default 32 KiB limit and rejected the repair prompt's exact
31,077-byte state as a mismatch. No repair action or verifier job started.

The repair recursion now carries the exact prepared state and registries from
the invalid first turn. The regression sends an invalid response through the
same request-budget reduction, starts exactly one repair turn, and asserts
equality of the two submitted `DirectorStateV2` objects.

A consistent Online Backup of the paused schema-v16 production database had
SHA-256
`7ad6b1ee2e3e1757d2c83fbf4e059603d83d290713a6dff77de72c55d17109a0`;
`PRAGMA integrity_check` returned `ok` and
`PRAGMA foreign_key_check` returned no rows.
