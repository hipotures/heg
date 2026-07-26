# AI Research Director Loop

## Context mode

Production uses `stateless_turns` by default. Each turn starts fresh and
receives a complete bounded scientific state.

This avoids server-side conversation growth and makes model context auditable.

Two deterministic gates apply before inference:

1. reduce `DirectorStateV2` to its byte limit;
2. measure base instructions, prompt, and output schema together.

If the complete request exceeds its token estimate while the state still
contains policy-droppable detail, the host derives a smaller state-byte target
from the exact excess plus 1 KiB headroom and rebuilds the prompt, registries,
and schema. Exact-verifier facts and current executable IDs remain
non-droppable. If those facts alone cannot fit, the turn still fails closed
before inference.

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

## Structured output

The output includes:

- campaign assessment;
- hypothesis updates;
- typed actions;
- rationale and expected effect;
- evidence IDs;
- evaluation windows;
- next review trigger.

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
