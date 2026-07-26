# M6 Director verification-target schema

Date: **2026-07-26**

## Outcome

The generated Director schema now restricts every
`schedule_verification.candidate_ids` item to the exact candidate target list
submitted with the same scientific state. Semantic validation remains a
second independent membership check. No response is sanitized or partially
executed.

## Reproduced gap

Production attempt 15 used snapshot
`snapshot-312187900f3a458d88a04b11d31b10cb`. Its repair response supplied:

```text
candidate-07bf733afd1233c9
```

The committed candidate target was:

```text
candidate-07bf733afd1233c9f1049966
```

The old output schema accepted any string at that location, after which the
semantic validator correctly rejected the entire batch. No action or verifier
job was dispatched.

## Offline acceptance

The saved attempt-15 action space contained 12 candidate targets. Rebuilding
the schema produced:

| Check | Result |
|---|---:|
| generated enum equals submitted candidate list | yes |
| truncated production ID excluded | yes |
| previous schema size | 13,461 bytes |
| repaired schema size | 13,914 bytes |
| schema increase | 453 bytes |
| complete request size | 53,359 bytes |
| estimated client-owned tokens | 13,340 / 16,000 |

Focused tests also preserve the generic schema behavior used without a
submitted action space and confirm that semantic validation rejects an
inadmissible retained-candidate ID.

## Compatibility

This is a constraint correction within schema version `1.0`, not a new field
or action. Historical request, response, fingerprint and campaign records
remain immutable. No SQLite migration is required.

## Production rollout

Before Resume, an SQLite Online Backup of the schema-v16 production database
had SHA-256
`50347193ab926412ffba013fd67e92337d504b255a5eeefe90c044cb96534c98`.
`PRAGMA integrity_check` returned `ok` and
`PRAGMA foreign_key_check` returned no rows.

Resume preview preserved the campaign contract and resources, proposed
attempt 16, validated all 14 historical checkpoints and correctly selected
zero process restorations. It reported zero model, search, auth and database
side effects.

Attempt `execution-attempt-196c315cf1880254f6e8b2b5` ran commit
`8c8c40f814976fdcf93b6114c5d978f74db15807`. Its first live request reported:

| Measurement | Value |
|---|---:|
| candidate enum members | 12 |
| output schema | 13,914 bytes |
| complete request | 53,373 bytes |
| estimated client-owned tokens | 13,344 / 16,000 |
| request within gate | yes |

The first two Director turns were `completed_valid`. The first scheduled four
exact enum members for M4; all four completed as `INVALID_CANDIDATE`. A later
attempt to reverify terminal candidates became `stale_target` and was not
reexecuted. Four new order-96 lanes produced:

| Measurement | Value |
|---|---:|
| durable metric windows | 5 |
| evaluated candidates | 591,338 |
| observed throughput | 249.5–820.1/s |
| C++ scorer requests | 591,346 |
| Python audits | 1,249 |
| scorer fallbacks | 0 |
| parity mismatches | 0 |
| backend / early exit / duplicate key | C++ / on / `delta_local_v2` |

The third independent Director turn reached the configured timeout after
302.04 seconds. The campaign stopped fail-closed as `AppServerTurnTimeout`;
the four new lanes became `paused`, all campaign and scorer processes exited,
and no automatic attempt 17 was started. This terminal condition is distinct
from the accepted schema repair: neither the unknown verification ID nor a
Director context-budget/state-identity fault recurred.
