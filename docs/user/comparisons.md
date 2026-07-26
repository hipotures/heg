# Model and Context Comparisons

Comparison suites measure model, effort, or context behavior without executing
returned research actions.

## Typical questions

- Does `high` produce useful decisions at lower cost than `xhigh`?
- Does `stateless_turns` reduce input tokens compared with
  `persistent_thread`?
- Does a more expensive model improve scientific usefulness?
- Are decisions schema-valid and semantically valid?
- Which answer does a human prefer when model identity is hidden?

## Comparison contract

A prepared suite binds:

- immutable fixture;
- model and reasoning effort per arm;
- context mode;
- arm order and repetitions;
- prompt, schema, and registry hashes;
- timeout and inference caps;
- resource limits;
- fail-closed or independent-invalid continuation policy;
- exact plan fingerprint.

Measurement-only suites enforce:

- `measurement_only=true`;
- `execute_decisions=false`;
- zero search batches;
- zero returned-action dispatch;
- zero model tools.

## Create a suite

Use `/comparisons/new` on the dashboard.

[screenshot: ID=USR-COMPARISON-01; save as docs/assets/screenshots/user/comparisons/new-suite-form.png; crop the complete new comparison suite form showing fixture selection, two arm rows, model, effort, context mode, repetitions, timeout, hard inference cap, total-token limit, ordering seed, and measurement-only/fail-closed settings; exclude browser chrome.]

Prepare the suite, review its immutable plan and fingerprint, then authorize
only that exact plan.

[screenshot: ID=USR-COMPARISON-02; save as docs/assets/screenshots/user/comparisons/prepared-plan.png; crop the prepared comparison plan summary including suite ID, fingerprint, fixture hash, planned/maximum inference starts, arm order, scientific-input equality hashes, resource limits, and the separate Authorize control.]

## Read results

Per turn, the UI shows:

- expected and effective model/effort/context;
- lifecycle status;
- input, cached input, output, reasoning output, and total tokens;
- latency;
- schema validity;
- semantic validity;
- selected action;
- validation issues;
- relative cost profile;
- manual rating.

Cached input is part of input, and reasoning output is part of output; they
must not be added to total tokens again.

## Blind comparison

The blind page hides model, effort, context, usage, latency, and cost until a
rating is submitted.

[screenshot: ID=USR-COMPARISON-03; save as docs/assets/screenshots/user/comparisons/blind-pair.png; crop the blind pairwise page before rating, include both semantic answer cards and A better/Equal/B better/Skip controls, ensure no model, effort, context, token, latency, or cost identity is visible.]

## Invalid responses

For new independent comparison arms:

- schema-invalid or semantic-invalid output is persisted as a model result;
- the next independent arm may continue;
- infrastructure, protocol, resource, security, or model-contract failures
  remain fail-closed;
- dependent persistent-thread arms require a valid predecessor.

## Cost semantics

The UI separates:

1. authoritative server token usage;
2. editable relative subscription-cost units;
3. optional API-equivalent estimate.

An API-equivalent estimate is not an actual subscription charge.
