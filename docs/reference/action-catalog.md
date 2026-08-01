# Director Action Catalog

The Director may return only reviewed typed actions.

| Action | Purpose | Typical target |
|---|---|---|
| `start_lane` | Start a new search lane | New lane specification |
| `patch_lane` | Change reviewed lane parameters | Active lane |
| `fork_lane` | Branch from a checkpoint while parent continues | Active lane/checkpoint |
| `restart_lane` | Restart from a reviewed state/checkpoint | Lane |
| `stop_lane` | Stop active lane | Active executable lane |
| `reallocate_resources` | Adjust bounded lane shares | Active lane set |
| `promote_candidate` | Retain/promote notable candidate | Executable candidate |
| `schedule_verification` | Queue M4 exact verification | Pinned candidate snapshot |
| `request_diagnostic` | Run reviewed deterministic diagnostic | Evidence/advisory/executable subject |
| `set_review_trigger` | Configure next review events/window | Campaign/lane-independent trigger |

## Applicability

The action space is generated from current runtime state.

Examples:

- `stop_lane` is absent when no active executable lane exists;
- candidate actions enumerate only retained executable candidates;
- historical lanes remain evidence/advisory targets, not executable targets.

## Parameter contract

- algorithm-specific allowed parameters;
- unsupported parameters rejected;
- mutation weights known, non-negative, positive-sum, normalized;
- `proposal_ranking` is optional and, when present, must equal the reviewed
  catalog ID `mutation_forge_stage4r_v1`; it is trajectory-breaking, applies
  only to reviewed mutation starts in an LLM campaign, leaves
  `random_restart` unranked, and is not patchable;
- resource and evaluation windows bounded;
- null transport fields removed during normalization.

## Dispatch contract

1. validate;
2. assign/check workspace-scoped action ID;
3. commit decision/action batch;
4. pin candidate targets when required;
5. dispatch;
6. persist outcome/effect.

No accepted action is dispatched before durable commit.

## Reviewed diagnostics

`seed_generation_efficiency` compares the latest cumulative bounded seed
telemetry for submitted lanes. It reports the lane/family/order with the
highest p95 attempt estimate, generators approaching or exhausting their retry
budget, generator share of measured search-loop time, and random-restart
lanes whose throughput is seed-construction dominated.
