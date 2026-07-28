# Passive Stale-Campaign Recovery

Date: 2026-07-28

## Incident

A passive `restart_lane` decision was built from campaign snapshot version
473. Other accepted durable work advanced the campaign before the decision
batch committed, so the store persisted `rejected_stale_campaign` and
dispatched nothing. The orchestrator then raised `PassiveSchedulerFault`
without attempting a fresh deterministic review.

The original rejected decision, action, trigger, snapshot, terminal attempt,
lane history, and absence of downstream action or verification work remain
unchanged evidence.

## Repair contract

- A passive batch containing only `rejected_stale_campaign` statuses dispatches
  nothing.
- The scheduler restores its last committed state, publishes a fresh snapshot,
  and performs exactly one fresh deterministic review.
- Rejected scheduler state is never presented as committed state.
- A durable per-state decision-attempt ordinal gives regenerated actions unique
  deterministic IDs without rewriting rejected actions, including after a
  process restart or Resume.
- A repeated stale-campaign conflict, or any different passive rejection,
  remains fail-closed.

## Focused verification

- A single forced campaign-version race is recovered by one fresh review whose
  batch is accepted.
- Two forced races raise `PassiveSchedulerFault` with zero accepted actions.
- Restarting from the last committed scheduler state after the repeated fault
  produces non-colliding action IDs and can commit successfully.
- The complete orchestrator and passive-scheduler test modules pass.
- Focused Ruff and Python compilation checks pass.
