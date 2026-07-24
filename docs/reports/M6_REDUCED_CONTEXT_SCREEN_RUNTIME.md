# Reduced context-mode screen: authenticated runtime

Date: **2026-07-24**

The tested production commit was
`f1a9575cbf69be79134db796212fb2f3213b587c`. The initial Phase-B commit was
`32cdba7eed07f22f5746555739e9a501087f26e5`. The installed runtime was
`codex-cli 0.145.0`.

The operator explicitly authorized copying only
`/home/xai/.codex/auth.json` into two new, independent private Codex homes and
at most three inference starts in the order S2 → P1 → P2. The authorization
required `gpt-5.6-luna` with reasoning effort `xhigh`.

## Result

The test stopped after S2, as required by its fail-closed contract.

Before inference, the stateless arm persisted:

```text
expected_model: gpt-5.6-luna
expected_reasoning_effort: xhigh
effective_model: gpt-5.6-luna
effective_reasoning_effort: xhigh
model_contract_matched: true
```

S2 returned a final structured decision and complete token usage. Its schema
was valid, but semantic validation failed at:

```text
$.actions[0].lane_id: does not reference an active lane
```

The model recommended `stop_lane` for the historical lane
`lane-36ef6c44aded9d38cfc4dd72`. That lane identifier was visible in the A4
scientific state, but the measurement database intentionally contained no
active lane and `DecisionContext` did not admit it as executable. The raw
response was preserved unchanged; the decision remained
`measurement_only: true` and `executed: false`.

P1 and P2 were not started. No retry or replacement slot was created.

## S2 correlation and usage

| Field | Value |
|---|---|
| thread ID | `019f95b2-5ccb-7e50-8e41-8d9c0cc8996e` |
| turn ID | `019f95b2-5d0e-70b3-9a1e-fa51ee914c5e` |
| request ID | `11` |
| final item ID | `msg_0f54820d364b5a12016a63c3590f588191b924f837de864be2` |
| lifecycle | `completed` |
| schema valid | `true` |
| semantic valid | `false` |
| input tokens | 10,180 |
| cached input tokens | 0 |
| cache-write input tokens | 0 |
| output tokens | 3,001 |
| reasoning output tokens | 2,471 |
| server-reported total tokens | 13,181 |
| first-item latency | 0.983 s |
| final-answer latency | 56.280 s |
| total turn wall time | 59.289 s |

`totalTokens` is authoritative; cached and reasoning categories were not added
to it.

## Isolation and persisted rollout

The pre-disable list contained six absolute skill paths and no errors. The
post-disable/reload list contained zero active skills and no errors. The
complete 17-record rollout was inspected through the opaque `thread.path`
stored in SQLite, and that path was validated inside the private stateless
Codex home.

Observed rollout facts:

- model `gpt-5.6-luna`, effort `xhigh`;
- the 682-byte custom Director base instruction was present;
- the platform-owned read-only sandbox instruction and minimal environment
  wrapper were present;
- `agents_md` was empty;
- app and plugin instructions were disabled;
- selected environments were empty;
- no normal-user Codex-home path, repository path, AGENTS.md, skill
  instruction block, app instruction block, or plugin instruction block
  appeared;
- response items consisted only of messages and reasoning items;
- no tool-call item or unsupported server request occurred.

The world-state metadata retained `host_skills.includeInstructions: true` and
`skills.includeInstructions: true`; this is reported rather than hidden.
Because all six discovered skills were disabled and no skill instruction
message was present, it did not introduce an active skill into this turn.

## Zero-execution evidence

```text
inference starts reaching model: 1
successful completed turns: 1
timed out or aborted turns: 0
retries reaching inference: 0
tool calls: 0
search batches: 0
research lanes: 0
action dispatches: 0
candidate evaluations: 0
compaction operations: 0
```

The App Server exited through the graceful path. The measurement database and
its SQLite Online Backup both reported `user_version=9` and
`integrity_check=ok`.

## Comparison and status

S2 and the planned P2 retained identical A4 DirectorStateV2, prompt, output
schema, evidence registry, action space, target, budget, artifact references,
and request template. P2 did not run, so no direct token, cache, latency,
reliability, or semantic comparison exists.

```text
canonical_evidence_registry: proven
incomplete_turn_persistence: proven_deterministically
director_state_v2_bounded: proven
stateless_A4_completed: false
persistent_A1_completed: false
persistent_A4_completed: false
exactly_three_or_fewer_inference_starts: true
zero_retries_reaching_inference: true
zero_search_batches: true
zero_action_dispatches: true
zero_candidate_evaluations: true
zero_compaction_operations: true
zero_tool_calls: true
usage_accounting_complete: false
semantic_validity_stateless_A4: false
semantic_validity_persistent_A4: unavailable
stateless_token_reduction_percent: null
completion_reliability_comparison: inconclusive
context_mode_comparison: inconclusive
recommended_default_context_mode: inconclusive
```

The private runtime report retains the authorization hashes, full artifact
paths, decisions, and complete artifact manifest. Credentials, private runtime
artifacts, rollouts, wire logs, and auth hashes are not committed.
