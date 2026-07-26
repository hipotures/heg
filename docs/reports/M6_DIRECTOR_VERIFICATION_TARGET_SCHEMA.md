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

Live Resume acceptance will be appended after the implementation commit,
Online Backup integrity checks, Resume preview and one bounded execution
attempt.
