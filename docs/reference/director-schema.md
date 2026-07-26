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

The submitted action space uses separate compact lists for active executable
lanes, historical lanes, candidate targets, and checkpoint targets, plus one
compact lane-lifecycle map. Reference registries deterministically recover
status and evidence/advisory/executable roles from these values. A duplicated
per-reference object list is not part of the model-facing contract.

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

## IDs

Action IDs have workspace scope. The state supplies a deterministic recommended
prefix. A non-idempotent collision rejects the batch before insertion.

The generated schema binds `promote_candidate.candidate_id`,
`request_diagnostic.subject_ids`, and
`schedule_verification.candidate_ids` to the submitted candidate-target enum.
An unseen, historical-only, or truncated candidate ID is therefore outside
the structured-output contract and remains invalid under semantic validation.

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

The complete-request budget includes base instructions, prompt, and output
schema. A request-level compaction pass may reduce policy-droppable
`DirectorStateV2` detail and rebuild these artifacts under the same snapshot ID
before any inference starts.

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
