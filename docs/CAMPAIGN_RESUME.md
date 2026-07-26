# Campaign Resume

Campaign continuity separates the durable scientific campaign from the
process that happens to execute it. A campaign ID identifies one scientific
experiment. Every initial start or Resume creates a new immutable execution
attempt beneath that campaign.

## Execution attempts

Schema v15 records for every attempt:

- its campaign ID, monotonic attempt index, and immutable attempt ID;
- the start reason (`initial_start`, `operator_resume`,
  `additional_budget`, `infrastructure_recovery`, or
  `host_restart_recovery`);
- the executing code commit and start/terminal timestamps;
- requested and effective resources;
- the additional wall-time budget;
- the starting scientific-memory snapshot ID and SHA-256;
- verified starting checkpoint references;
- inherited cumulative counters and attempt-local counters;
- terminal status/reason, repair acknowledgement, process ID, and bounded
  authorization/runtime provenance.

The code commit may change to install a bug fix. The target, target-definition
hash, Director model, effort, context mode, and authenticated-versus-control
contract may not change during Resume. A scientifically different contract
requires a fresh campaign.

CPU workers are an application-level worker-slot limit. The implementation
does not claim cgroup, affinity, or operating-system CPU isolation.

## Resumable states

Resume is supported after operator pause/stop, deadline or budget exhaustion,
an interrupted process, host restart, and a non-scientific infrastructure
failure. A `paused_fault` requires an explicit repair acknowledgement. The
prior fault and prior attempt remain terminal historical evidence.

Resume is rejected for a currently live campaign, certified success, and
scientific invalidation. A stale `running` record with no live owned process
is treated as host-restart recovery.

Resume preserves hypotheses, Director assessments, candidates, exact-verifier
outcomes, lane history, valid checkpoints, telemetry summaries, cumulative
time/evaluations/tokens, idempotency keys, and prior faults. Terminal actions
and completed verifier jobs are not executed again.

Director action identifiers have durable workspace scope because
`director_actions.action_id` is a workspace-wide primary key. Every stateless
turn receives a deterministic snapshot-derived recommended prefix, and the
semantic validator rejects any identifier already present in the durable
workspace. The persistence layer repeats this check inside the decision-batch
transaction: a non-idempotent collision rejects the whole batch before any
action or hypothesis update is inserted. The campaign then permits one fresh
stateless replan; a second collision stops cleanly. A genuinely identical
idempotent submission retains the existing duplicate/no-op behavior.

An invalid Director result is retained as its own response artifact before
the one permitted stateless replan. The replan prompt includes the identical
scientific state, exact validation errors, and the invalid response SHA-256,
but does not duplicate the full rejected response into client-owned context.
Hypothesis evidence fields accept only exact submitted evidence-registry IDs,
never explanatory prose. This keeps the correction actionable and bounded
without raising the 16,000-token client-owned context limit.

## CLI

Preview has no database, auth, model, or search side effects:

```bash
sglab research-campaign resume \
  --workspace workspace/first-real-graph-campaign-01 \
  --campaign-id campaign-b68ec445388e49b2be0b6fabf8ff6600 \
  --additional-time 2h \
  --cpu-workers 16 \
  --max-active-lanes 8 \
  --lane-memory-bytes 536870912 \
  --verifier-concurrency 2 \
  --repair-acknowledgement "candidate pin repair installed" \
  --preview
```

Omit `--preview` only after reviewing the same contract. The dashboard exposes
the equivalent protected Preview and Start-new-attempt controls. It shows the
stable campaign ID separately from attempt IDs, cumulative versus
attempt-local metrics, resource differences, checkpoint/memory reuse, prior
fault, and repair acknowledgement.

## Recovery details

Resume never assumes a search subprocess survived. Active/resumable lanes are
reconstructed from their latest hash-verified checkpoints; terminal lanes
remain history. A bad checkpoint affects only its lane and is reported to the
next Director state. Existing lease recovery and action idempotency prevent
duplicate batches and actions.

Pre-Resume snapshots summarize persisted lane telemetry through the same
bounded projection used for live lanes. Full mutation ancestry and evaluation
details remain in `lane_metric_windows` and retained artifacts; they are not
copied wholesale into the bounded Director snapshot. The protected HTTP
endpoint waits for the immutable attempt row; if the subprocess exits first,
it reports the launch failure instead of returning a misleading started PID.

Candidate-target actions acquire durable candidate pins and immutable graph
snapshots before execution. M4 reads the immutable snapshot. Pins release only
after all referencing actions/jobs are terminal. A candidate that becomes
stale before action acceptance is recorded as `stale_target`, is not executed,
and causes at most one fresh stateless replan with the stale and current valid
IDs. A second stale/invalid replan ends the campaign cleanly.

Distinct fresh campaigns remain independent. Resume provides continuity only
inside one campaign; it does not import knowledge into another campaign.
