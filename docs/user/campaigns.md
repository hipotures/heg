# Campaigns

A campaign is one durable scientific experiment.

## Campaign lifecycle

```mermaid
stateDiagram-v2
    [*] --> prepared
    prepared --> running: authorize and start
    running --> paused_by_operator: pause
    paused_by_operator --> running: continue live attempt
    running --> budget_exhausted
    running --> deadline_reached
    running --> stopped_by_operator
    running --> paused_fault
    running --> certified_success
    paused_fault --> running: repaired Resume / new attempt
    budget_exhausted --> running: Resume / additional budget
    deadline_reached --> running: Resume / additional budget
    stopped_by_operator --> running: Resume / new attempt
    certified_success --> [*]
```

Exact state names may include additional terminal or recovery variants; see
[State Machines](../reference/state-machines.md).

## What the Director decides

The Director works through a reviewed action catalog. It may:

- start a lane;
- patch lane parameters;
- fork a lane from a checkpoint;
- restart or stop a lane;
- reallocate lane resources;
- promote a candidate;
- schedule exact verification;
- request diagnostics;
- set review triggers.

The operator does not normally choose algorithms or mutation parameters for
the Active Director campaign.

## Campaign budgets

A prepared campaign fingerprints:

- wall-time stop condition;
- maximum scientific cycles and Director turns;
- per-turn timeout;
- lane and aggregate resource limits;
- verification queue and timeout limits;
- App Server/log/resource limits;
- scientific-memory policy;
- replan policy.

## Director response policy

- Valid decisions are persisted, then dispatched.
- Invalid decisions are persisted and never dispatched.
- One fresh stateless repair turn may be allowed for the same scientific state.
- Repair prompts contain the same state, exact validation errors, and the
  invalid-response SHA-256—not a duplicated full rejected response.
- A second invalid repair stops cleanly.
- Infrastructure, protocol, resource, auth, and verifier failures remain
  fail-closed.

## Hypotheses

Hypothesis updates are operation-specific:

- `create` uses a new response-unique ID;
- `confirm`, `weaken`, `reject`, `retain`, and `revise` must reference an
  existing submitted hypothesis ID;
- evidence arrays contain exact submitted evidence-registry IDs, never prose.

## Campaign progress

Measure progress with:

- cumulative evaluations;
- score progression;
- explored graph families/orders/parameter regions;
- lane stagnation and diversity;
- retained candidates;
- exact-verifier outcomes;
- hypothesis changes;
- time and model usage.

Do not use only the final best score.

Operator diagnostics may include one aggregated score profile per completed
lane batch. These timing, DFS-node, completeness and early-cutoff counters
explain throughput; they are not candidate evidence and do not affect
heuristic scores or M4 verification. Batch diagnostics also identify the
requested/effective score backend and any Python audits or fallbacks.
When profiling is enabled, the same completed-batch diagnostic separates
uniform and forbidden-cycle-targeted mutation time and reports reuse of the
current graph's witness choices. It does not create a candidate history or
change the selected mutation sequence.

The dashboard's aggregate throughput is the sum of the latest completed
metric window from every running lane. Each lane card shows that same
latest-window value, so the visible lane rates can be added directly. Rolling
telemetry remains the basis for diversity, duplicate-rate, and trend fields.
Up to eight lane cards are visible in the main lane panel before expansion.
After Pause or another non-running transition, current aggregate and per-lane
throughput show `0/s`. The last completed measurement is retained as history,
but is not presented as current work.
After Resume, throughput starts at `0/s` again and includes only measurements
completed during the new execution attempt.

[screenshot: ID=USR-CAMPAIGN-01; save as docs/assets/screenshots/user/campaigns/director-assessment.png; crop the “Director assessment & hypotheses” section from a running or stopped campaign, include the latest campaign assessment, at least two hypothesis cards with confidence/evidence, and the adjacent current Director decision summary; exclude raw JSON technical details.]

[screenshot: ID=USR-CAMPAIGN-02; save as docs/assets/screenshots/user/campaigns/lane-trajectories.png; crop the live lane visualization or lane cards showing at least three lanes with distinct statuses or algorithms, checkpoint markers, and one fork/restart/parameter revision indicator; include the section heading and legend.]
