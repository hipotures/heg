# Debugging Production Campaigns

## First rule

Do not modify the production workspace while diagnosing unless the operation is
an explicit repair or authorized Resume.

## Read-only triage

Inspect:

- campaign state/fault;
- execution attempts;
- Director turn statuses and validation issues;
- lane states/checkpoints;
- candidates/pins/snapshots;
- verification jobs;
- scientific-memory snapshots;
- leases/processes;
- resource samples;
- integrity/FK.

Use `sqlite3 -readonly` or an Online Backup.

## Classify the failure

- scientific negative result;
- invalid Director output;
- stale target;
- candidate/verification reference problem;
- App Server protocol/auth/model contract;
- resource quota;
- filesystem policy;
- process lifecycle;
- SQLite/checkpoint integrity;
- UI-only presentation defect.

Do not collapse all cases into `RuntimeError`.

## Decide recovery

| Finding | Action |
|---|---|
| UI-only | Fix UI; do not mutate runtime data |
| Invalid Director output | Persist; bounded repair if permitted |
| Stale target | Mark stale; refresh registry; replan |
| Non-scientific fault | Fix; preview Resume with acknowledgement |
| Scientific invalidation | Mark invalidated; start fresh campaign |
| M4 rejection | Preserve negative evidence; continue/replan |
| Integrity failure | Stop; repair from consistent backup |

## Preserve evidence

Do not rewrite:

- old turn result;
- old fault;
- old plan fingerprint;
- old artifact hashes;
- consumed inference count;
- historical attempt state.

Create a new report or attempt for the correction.
