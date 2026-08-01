# AI Research Director Loop

The reviewed decision/validation/dispatch pipeline has two orchestration
sources. `llm` uses the AI Research Director described below. `passive` uses
the deterministic host scheduler described in the final section; it never
impersonates an App Server turn.

## Context mode

Production uses `stateless_turns` by default. Each turn starts fresh and
receives a complete bounded scientific state.

This avoids server-side conversation growth and makes model context auditable.

Two deterministic gates apply before inference:

1. reduce `DirectorStateV2` to its byte limit;
2. measure base instructions, prompt, and output schema together.

The complete-request pass targets 15,000 estimated client-owned tokens, leaving
headroom below the 32,000-token hard gate. While the state still contains
policy-droppable detail, the host derives a smaller state-byte target from the
exact excess plus 1 KiB headroom and rebuilds the prompt, registries, and
schema. If that ideal target is below the irreducible safe-state floor, a
deterministic binary search selects the tightest feasible state instead of
discarding the entire reduction. Exact-verifier facts and current executable
IDs remain non-droppable. If the complete request still exceeds the hard gate,
the turn fails closed before inference.

Scientific-memory reduction removes duplicated historical candidate and lane
summaries only after their rich fields have been reduced. Exact-verifier
outcomes, current executable candidate/checkpoint IDs, and the live applicable
action space remain authoritative; full candidate and lane rows remain in
SQLite.

## Submitted material

A Director request contains:

- target and campaign status;
- current scientific-memory snapshot;
- bounded recent deltas;
- budgets/resources;
- hypothesis ledger;
- best/result summaries;
- exact-verifier facts;
- current evidence, advisory, and executable registries;
- applicable action space;
- previous expectation/outcome comparison;
- action-ID namespace recommendation.

The action space carries compact target-ID lists. Evidence, advisory, and
executable registries derive their roles from those lists; the prompt does not
repeat a verbose object for every reference.

The surrounding prompt points to `director_state_v2.allowed_action_space`
instead of embedding a second copy. It reports the number of durable reserved
action IDs but does not replay their complete list. Workspace-scoped action-ID
collision validation remains authoritative in the durable store.

## Structured output

The output includes:

- campaign assessment;
- hypothesis updates;
- typed actions;
- rationale and expected effect;
- evidence IDs;
- evaluation windows;
- next review trigger.

When the action space exposes retained candidates, every candidate target in
the generated output schema is restricted to the exact submitted candidate
ID list. This includes each item of
`schedule_verification.candidate_ids`; semantic validation repeats the same
membership check as defense in depth.

Every evidence reference in `hypothesis_updates[].evidence_for`,
`hypothesis_updates[].evidence_against`, and `actions[].evidence_ids` is
likewise restricted to the exact submitted evidence registry. The generated
schema stores that enum once in `$defs` so the complete request does not
multiply the registry across action variants. An empty submitted registry
forces all evidence-reference arrays to remain empty. Semantic membership
validation remains authoritative defense in depth.

The generated `start_lane.spec` contract is algorithm-discriminated. Each
algorithm receives only its legal parameter keys; `random_restart` has no
`proposal_ranking` key, while an explicitly ranked mutation campaign requires
the reviewed catalog ID on every new mutation-lane branch. The host still
performs the same semantic checks after inference, so an invalid model result
is rejected rather than silently rewritten.

## Validation layers

1. JSON/schema validation.
2. operation-specific hypothesis contract.
3. evidence-registry membership.
4. action applicability.
5. executable-target membership.
6. algorithm/parameter implementation.
7. budget/resource bounds.
8. action ID and idempotency checks.
9. prohibited tool/code/shell/file checks.

## Repair turn

An invalid result is stored as its own artifact.

The repair request uses:

- identical scientific state;
- exact validation issues;
- invalid-response SHA-256;
- no duplicated full invalid response.

If complete-request budgeting reduced the first turn below the ordinary
Director-state limit, the repair reuses that exact prepared state and its
registries. It does not rebuild the state at the default limit or perform a
second, semantically different projection.

The repair runs on a fresh stateless thread. One repair is allowed per
scientific state.

## Action ID scope

`action_id` is workspace-scoped durable identity. The Director receives a
deterministic snapshot-derived prefix. Non-idempotent collisions reject the
whole batch before insertion.

## Hypothesis contract

- `create` → new unique ID;
- existing operations → exact existing hypothesis ID;
- `evidence_for`/`evidence_against` → exact submitted evidence IDs, never
  prose.

## No model tools

The Director cannot invoke search, shell, code, filesystem, or verification
tools directly. It proposes reviewed actions; the host validates, commits, and
executes them.

## No-LLM passive scheduler

`balanced_v1` produces the same decision schema and submits it to the same
schema, semantic, target, lane-version, capacity, and resource validation.
Its accepted decision and next scheduler state are committed before dispatch.
Invalid internal output is persisted as a scheduler implementation fault and
executes nothing; there is no schema/semantic repair turn. A commit-time
`rejected_stale_campaign` is instead an optimistic-concurrency conflict. The
coordinator drains lane events before snapshot publication and does not pump
or dispatch more events between a passive snapshot, its host-local review, and
the batch commit. The global campaign-version check remains authoritative, so
an unexpected external version change still persists the rejected batch,
dispatches nothing, and permits one fresh snapshot plus one fresh
deterministic scheduler review. If that review is also stale, or is rejected
for another reason, the scheduler faults fail-closed. Rejected reviews do not
advance committed scheduler state; a durable per-state decision-attempt
ordinal keeps regenerated action IDs unique without rewriting the rejected
history, including after Resume.

The scheduler persists policy/state versions, bounded input metrics,
deterministic reason codes, generated action IDs, validation, review index,
stagnation counters, exploration cursor, and SHA-256 counter-based RNG
lineage. It creates a conservative reviewed-algorithm portfolio, keeps a
random-restart exploration floor, fills unused capacity gradually, prefers
valid checkpoints for stagnant-lane restarts, and uses the existing M4
verification action. It never selects vertices, edges, mutations, shell
commands, or hot-loop operations.
