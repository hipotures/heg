# Director Output Contract

## Top-level structure

A Director response contains:

- schema version;
- snapshot ID;
- campaign assessment;
- hypothesis updates;
- zero or more typed actions;
- next review trigger.

The exact generated JSON schema is derived from the submitted action space and
registries.

In `llm` mode this contract is model-facing. In `passive` mode the versioned
host scheduler constructs the same typed decision object and submits it to the
same semantic validator, durable action-batch store, and dispatcher. Passive
decisions have a scheduler-decision source instead of an App Server turn
source; they do not create repair turns. A rejected passive decision is
persisted and no action from that batch is dispatched. Invalid output and
commit-time target/lane rejection fault immediately. The narrower
`rejected_stale_campaign` concurrency status permits one fresh deterministic
review from a newly published snapshot; a repeated conflict faults. The
host-local passive review and commit do not pump lane events after that
snapshot is published, so ordinary queued lane outcomes cannot create this
conflict themselves.

The submitted action space uses separate compact lists for active executable
lanes, historical lanes, candidate targets, and checkpoint targets, plus one
compact lane-lifecycle map. Reference registries deterministically recover
status and evidence/advisory/executable roles from these values. A duplicated
per-reference object list is not part of the model-facing contract.

When the immutable campaign plan enables proposal ranking, the action space
also carries the exact reviewed `mutation_forge_stage4r_v1` contract. New
simulated-annealing and ILS/ILS-tabu starts must name that ID; `random_restart`
is always unranked, and patches cannot add or remove the capability. This
contract is available only to LLM Director campaigns; passive mode remains
unchanged. A plan without the option remains default-disabled.

## Hypothesis updates

Operations:

```text
create
confirm
weaken
reject
retain
revise
```

Rules:

- `create`: new response-unique ID;
- other operations: exact existing submitted hypothesis ID;
- evidence arrays: exact evidence-registry IDs;
- free-text evidence explanations are not IDs.

## Actions

Each action includes:

- `action_id`;
- type;
- priority;
- idempotency key;
- rationale;
- expected effect;
- evidence IDs;
- hypothesis IDs;
- evaluation window;
- fallback;
- type-specific fields.

`request_diagnostic` may select
`seed_generation_efficiency`. Its submitted subject enum is the bounded
diagnostic-subject registry, not only retained candidates, so current lane and
lane-metric evidence can be compared. The result identifies per-lane
family/order, p95/p99 attempts, retry-budget proximity and exhaustion,
generator runtime share, and random-restart lanes dominated by seed
construction. It remains heuristic telemetry and contains no graph bodies.

## IDs

Action IDs have workspace scope. The state supplies a deterministic recommended
prefix. A non-idempotent collision rejects the batch before insertion.
The prompt supplies the number of recently reserved IDs, not their full
durable list. The SQLite-backed workspace collision check remains the
authoritative membership test.

The generated schema binds `promote_candidate.candidate_id` and
`schedule_verification.candidate_ids` to the submitted candidate-target enum.
It binds `request_diagnostic.subject_ids` to the submitted diagnostic-subject
enum. An unseen or truncated ID is therefore outside the structured-output
contract and remains invalid under semantic validation.

The generated schema also binds every hypothesis and action evidence
reference to the exact submitted evidence-registry enum:

- `hypothesis_updates[].evidence_for`;
- `hypothesis_updates[].evidence_against`;
- `actions[].evidence_ids`.

The enum is defined once under `$defs` and referenced from each array. If the
submitted registry is empty, these arrays have `maxItems: 0`. Unknown,
historical-only, and invented evidence IDs remain independently rejected by
semantic validation.

`start_lane.spec` is emitted as algorithm-specific branches. A
`random_restart` branch contains only its three required seed parameters and
cannot contain `proposal_ranking`; when ranking is enabled, each supported
mutation branch requires the exact reviewed catalog ID. Unsupported fields are
therefore excluded from the model-facing contract before semantic validation,
while the validator remains fail-closed defense in depth.

## Zero-lane bootstrap

When the submitted action space has zero active lanes, no candidates, and at
least one available lane slot, the schema contains `start_lane` and the
prompt's applicable-action description names it as the constructive bootstrap
action. Candidate and lane-target branches are absent. A stale empty action
projection is reconciled at the schema boundary only to this same
zero-lane/start-capacity contract; it never invents candidate or lane IDs.

Strict Structured Outputs represents semantic optional controls with nullable
required transport properties. Host-side normalization removes those nulls
before `validate_decision`, which remains authoritative for positive mutation
weights, exclusive resource shares, target membership, and the exact
proposal-ranking catalog ID.

## Validation

Validation covers:

- structure;
- allowed operation/action;
- registry membership;
- target executability;
- implemented parameters;
- resource/budget bounds;
- prohibited requests;
- ID collisions;
- duplicate creates/idempotency.

## Repair

One invalid result may produce a repair request containing:

- same scientific state;
- validation errors;
- invalid-response SHA-256;
- no duplicated full rejected response.

The repair must keep the same snapshot ID.

Repair is available only for `llm` decisions. Passive decisions fail closed
after their single deterministic validation attempt.

The complete-request budget includes base instructions, prompt, and output
schema. A request-level compaction pass may reduce policy-droppable
`DirectorStateV2` detail and rebuild these artifacts under the same snapshot ID
before any inference starts.

The pass targets 15,000 estimated tokens before applying the 32,000-token hard
gate. If the calculated state target is smaller than the non-droppable
projection, the host searches deterministically for the tightest feasible
state. This preserves exact-verifier facts and current executable IDs while
still accepting every safe reduction available above that floor.

When the first response is invalid, its repair turn receives the exact
post-budget `DirectorStateV2` and reference registries submitted on that first
turn. Recomputing the repair state at a different byte limit is a protocol
fault, even when both projections have the same source snapshot ID.

## Output limitations

The Director cannot:

- execute tools;
- issue shell/code/file commands;
- provide arbitrary executable code;
- declare certification;
- bypass M4;
- use unseen IDs as evidence or targets.
