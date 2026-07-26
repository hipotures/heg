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

## Output limitations

The Director cannot:

- execute tools;
- issue shell/code/file commands;
- provide arbitrary executable code;
- declare certification;
- bypass M4;
- use unseen IDs as evidence or targets.
