# Adding a Director State or Output Field

## State field

Determine:

- source records;
- scientific meaning;
- exact versus heuristic status;
- bounded size;
- compaction behavior;
- high-water mark;
- whether the field is non-droppable;
- registry implications;
- deterministic ordering/hash.

Add the field to the state builder and scientific-memory projection as
appropriate. Test the 24,576/32,768-byte policy.

## Output field

Update:

- prompt contract;
- generated schema;
- normalization;
- semantic validation;
- persistence;
- action/hypothesis effect;
- UI renderer;
- reference docs.

## Registry references

If the field contains IDs, specify whether they are:

- evidence;
- advisory;
- executable.

Do not accept arbitrary strings when exact submitted IDs are required.

## Repair context

Validation errors must be actionable without embedding an unbounded rejected
response. Preserve the response artifact and pass SHA-256 plus exact errors.

## Compatibility

Schema changes may require a new plan/schema version and fingerprint.
Historical plans must remain readable and immutable.
