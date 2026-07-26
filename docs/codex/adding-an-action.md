# Adding a Director Action

## Checklist

1. Define scientific purpose and applicability.
2. Add type-specific schema.
3. Add semantic validation.
4. Add executable-target rules.
5. Add parameter domains and normalization.
6. Add durable action identity/idempotency behavior.
7. Add executor.
8. Add effect/outcome persistence.
9. Add recovery/Resume behavior.
10. Add dashboard semantic renderer.
11. Add reference documentation.
12. Add tests at every boundary.

## Applicability

The action must not appear in prompt/schema unless at least one locally valid
output exists for the submitted state.

Examples:

- lane-bound action requires active executable lane;
- candidate action requires executable candidate;
- diagnostic may accept evidence/advisory subject according to its contract.

## Dispatch

The batch and action must be committed before delivery.

Candidate-target actions must create/acquire pin and immutable snapshot in the
accepted-action transaction.

## Recovery

Define:

- idempotency key;
- duplicate/no-op semantics;
- terminal outcome;
- whether a pending accepted action is redispatched;
- how Resume prevents repetition.

## UI

Primary display is semantic. Raw JSON is secondary `<details>` evidence.
