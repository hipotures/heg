# Pause, Continue, Stop, and Resume

## Four different operations

| Operation | Meaning |
|---|---|
| **Pause** | Ask the current live attempt to stop new work at a safe boundary. |
| **Continue** | Continue the same still-live attempt after an operator pause. |
| **Stop** | End the current attempt while preserving campaign state. |
| **Resume** | Create a new execution attempt under the same campaign. |

## When to Resume

Resume is supported after:

- operator stop;
- deadline or budget exhaustion;
- process interruption;
- host restart;
- repaired infrastructure fault;
- operator pause when a new attempt is preferred.

Resume is refused for:

- a campaign that is currently live;
- certified success;
- scientific invalidation.

## What Resume preserves

- campaign ID;
- hypotheses and assessments;
- cumulative evaluations, time, and tokens;
- lane history;
- valid checkpoints;
- retained and pinned candidates;
- M4 outcomes;
- scientific-memory snapshots;
- previous faults and attempts;
- action idempotency history.

## What Resume may change

Per attempt, you may change:

- additional time;
- application CPU worker slots;
- maximum active lanes;
- aggregate lane share;
- lane memory;
- verifier concurrency;
- verifier memory;
- supported queue limits.

These are recorded as requested and effective resources.

Resume may not silently change:

- research target;
- target-definition hash;
- Director model;
- reasoning effort;
- context mode;
- scientific prompt contract.

A scientifically different contract requires a new campaign.

## Preview first

```bash
sglab research-campaign resume   --workspace workspace/first-real-graph-campaign-01   --campaign-id <campaign-id>   --additional-time 2h   --cpu-workers 16   --max-active-lanes 8   --lane-memory-bytes 536870912   --verifier-concurrency 2   --repair-acknowledgement "candidate pin repair installed"   --preview
```

Preview has no model, auth, search, or database-write side effect.

Review:

- proposed attempt ID and index;
- starting scientific-memory hash;
- reusable checkpoints;
- cumulative counters;
- resource differences;
- previous fault and repair acknowledgement;
- stale historical actions excluded from execution.

[screenshot: ID=USR-RESUME-01; save as docs/assets/screenshots/user/resume/resume-preview.png; open the Resume preview for a campaign with at least one prior attempt and a historical fault, crop the entire preview card including same campaign ID, proposed new attempt ID, additional time, CPU workers, max lanes, memory/verifier overrides, reused checkpoints, scientific-memory snapshot, previous fault, and repair acknowledgement; exclude lower campaign telemetry.]

## Start the new attempt

After reviewing the same contract, omit `--preview` or use the protected
dashboard control.

```bash
sglab research-campaign resume   --workspace workspace/first-real-graph-campaign-01   --campaign-id <campaign-id>   --additional-time 2h   --cpu-workers 16   --max-active-lanes 8   --lane-memory-bytes 536870912   --verifier-concurrency 2   --repair-acknowledgement "candidate pin repair installed"
```

## Resume after a fault

A `paused_fault` Resume requires a repair acknowledgement. The original fault
remains historical evidence. The new attempt records the new code commit and
does not rewrite the failed attempt as successful.

## Checkpoint behavior

Resume never assumes old worker processes survived. Resumable lanes are
reconstructed from hash-verified checkpoints. A missing or corrupt checkpoint
affects only the relevant lane and is reported to the Director.

## Stale candidate behavior

A historical candidate action is not retried if its target is no longer
executable. It becomes `stale_target`, and the Director receives the current
valid candidate registry for one bounded replan.

[screenshot: ID=USR-RESUME-02; save as docs/assets/screenshots/user/resume/attempt-history.png; crop the execution-attempt history after a successful Resume, include at least two attempts, start reason, code commit, requested/effective resources, attempt-local evaluations, cumulative evaluations, terminal status, and memory/checkpoint reuse badges.]
