# Troubleshooting

## Campaign shows `paused_fault`

**Meaning:** the campaign stopped fail-closed because an infrastructure,
protocol, resource, or runtime invariant failed.

**Are results preserved?** Yes. Previous turns, lane telemetry, candidates,
checkpoints, and M4 outcomes remain.

**Next step:** inspect `fault_kind` and `fault_detail`, repair the cause,
preview Resume with a repair acknowledgement, then start a new attempt.

[screenshot: ID=USR-TROUBLE-01; save as docs/assets/screenshots/user/troubleshooting/fault-detail.png; crop the campaign status and fault card showing full fault kind and detail, the “fail-closed” explanation, prior attempt status, disabled live controls, and available Resume preview control; exclude lower unrelated sections.]

## Resume button is disabled

Possible reasons:

- campaign is currently running;
- campaign is certified success;
- campaign is scientifically invalidated;
- fault requires a repair acknowledgement;
- the page is showing an old terminal state that does not support Resume.

Use the Resume preview command to obtain the exact reason.

## `stale_target`

A Director action referenced a candidate that is no longer executable. The
action is not run. One replan receives the current candidate registry.

This is not a generic runtime fault unless the replan also fails or another
invariant breaks.

## Invalid Director response

The response is preserved as evidence and never executed. One fresh stateless
repair may be attempted for the identical scientific state.

Common causes:

- unknown hypothesis ID for `revise`/`reject`;
- prose used where an evidence-registry ID is required;
- action ID collision;
- unsupported parameter;
- inactive lane or candidate used as an executable target;
- context or output size above a hard limit.

## `scientific_state_overflow`

The deterministic compacted state could not fit below the hard limit without
dropping non-droppable exact facts or current executable IDs. No model turn was
started.

Inspect the latest scientific-memory snapshot and source counts.

## `DirectorContextBudgetExceeded`

No Director action or exact-verification job was started after this fault.
Upgrade to a build that compacts scientific memory before enforcing the total
Director-state limit, then preview Resume with a repair acknowledgement.

For `client-owned context estimate exceeds ... tokens`, use a build that also
reduces policy-droppable state against the exact combined size of base
instructions, prompt, and output schema. The saved context-budget report shows
`client_limit_compaction_applied` and the attempted state-byte targets.

If the fault remains after both passes, inspect that report. A final reduced
`DirectorStateV2` above 32,768 bytes, or a complete request above its token
gate after all safe reductions, is a real fail-closed condition.

If the detail instead says `prompt DirectorStateV2 does not match the
committed snapshot` immediately after a completed invalid Director turn,
upgrade to a build that reuses the first turn's exact post-budget state for
repair. The invalid response and stopped attempt remain evidence; Resume only
after the fix is committed and acknowledged.

## Checkpoint mismatch

A checkpoint hash failed. The affected lane is not restored. Other lanes and
campaign history remain usable. The Director should receive the restore
failure.

## App Server timeout

The runtime records the authoritative thread/turn IDs, sends `turn/interrupt`
when available, drains late events, stores nullable final answer/usage, and
shuts down. It does not invent zero usage.

## Filesystem policy failure

Expected App Server wrappers are allowed only in the reviewed private runtime
location with trusted executable targets. Unexpected external symlinks fail as
`filesystem_policy`, not as a false byte-quota crossing.

## Resource limit failure

The UI should identify:

- failure domain;
- current/peak/limit;
- largest safe contributor label;
- lifecycle stage;
- cleanup result.

A completed valid arm or Director turn remains completed even if a later
suite-level preservation/shutdown step fails.

## SQLite integrity

```bash
sqlite3 workspace/results.sqlite3 'PRAGMA integrity_check;'
sqlite3 workspace/results.sqlite3 'PRAGMA foreign_key_check;'
```

Use a supported Online Backup or export before intrusive diagnosis.
