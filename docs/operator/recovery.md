# Recovery

## Recovery goals

Recovery must preserve scientific progress without pretending that process
state survived.

## Campaign Resume

Use the normal Resume preview:

```bash
sglab research-campaign resume   --workspace <workspace>   --campaign-id <campaign-id>   --additional-time 1h   --cpu-workers 16   --max-active-lanes 8   --repair-acknowledgement "<repair description>"   --preview
```

Review:

- source state and previous fault;
- new attempt ID/index;
- starting scientific-memory hash;
- checkpoint hashes;
- inherited counters;
- resource changes;
- stale actions excluded from execution.

## Checkpoint recovery

- verify adjacent hash/manifest;
- restore graph, RNG, tabu/search state, counters, and high-water;
- preserve the checkpoint's `duplicate_key_scheme`; do not rewrite a legacy
  visited/tabu set during Resume or a trajectory-preserving fork;
- for `random_restart` with `independent_sample`, do not load legacy
  `accepted_ancestry` or `best_ancestry` into live telemetry;
- start a new process generation;
- do not advance SQLite telemetry beyond a durable checkpoint boundary;
- report missing/corrupt checkpoint per lane.

Selecting the faster `delta_local_v2` duplicate key requires an explicit
algorithmic restart that creates fresh local duplicate state. It is not a
Resume migration.

## App Server recovery

No automatic provider retry is used in the strict campaign contract unless it
is explicitly fingerprinted. Interrupted turns remain durable with nullable
answer/usage.

Stateless Director mode rebuilds context from scientific memory rather than
relying on conversation recovery.

The passive scheduler has one narrower host-side concurrency recovery: a
commit-time `rejected_stale_campaign` dispatches nothing, publishes a fresh
snapshot, and performs one fresh deterministic review. This is not an App
Server/provider retry. A repeated conflict remains a fault requiring normal
repair acknowledgement and Resume.

## Repaired faults

A fault Resume requires:

- repair acknowledgement;
- code commit;
- preserved original fault/attempt;
- new attempt;
- one current executable registry;
- no replay of terminal actions or completed verifier jobs.

For `DirectorContextBudgetExceeded: DirectorStateV2 remains oversized after
deterministic compaction`, confirm that the running code applies secondary
scientific-memory reduction before the final Director hard-limit check. Test
the repair against an SQLite Online Backup of the affected workspace, run
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`, and verify that the
rebuilt projection is at most the campaign's recorded hard limit before
resuming the original campaign.

For `client-owned context estimate exceeds ... tokens`, also confirm that the
build measures and, when possible, reduces the complete request rather than
only `DirectorStateV2`. The Resume preview should be checked against an Online
Backup of the faulted workspace. Compare the old and rebuilt
evidence/advisory/executable ID sets and require exact parity before resuming.
For current builds, require a 15,000-token soft target, a 32,000-token hard
gate, and successful irreducible-floor recovery when the ideal state target is
unattainable. `client_limit_compaction_failure_recovered=true` means the failed
intermediate target was handled; it is not itself a terminal fault.

For `prompt DirectorStateV2 does not match the committed snapshot` after an
invalid response, inspect the first turn's context-budget artifact. If
`client_limit_compaction_applied` is true, confirm that the repair path reuses
the exact prepared state and registries from that turn. A repair must not
recompute the same source snapshot at the default byte limit. Test an
invalid→repair sequence before Resume.

For `Director response remained invalid after repair` caused by an
inadmissible `schedule_verification` candidate, confirm that the generated
schema's `candidate_ids.items.enum` exactly equals the submitted candidate
target list. Replay the faulted action space, verify the full request remains
below its client-owned token gate, and retain the semantic membership check
before Resume.

## Scientific invalidation

If a bug invalidated prior scientific results, do not Resume. Mark the
campaign scientifically invalidated and start a fresh campaign.

## Recovery verification

Always run:

```sql
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

Use a consistent backup for intrusive repair or migration tests.
