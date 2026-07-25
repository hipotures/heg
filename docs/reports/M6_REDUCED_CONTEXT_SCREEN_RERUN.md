# Reduced context-mode screen: successful fresh rerun

Date: **2026-07-25**

The fresh authenticated screen started from
`4be8f745d53a0789e8fe6c2bd02865cc58d21606` and tested production code from
`c96ae04488514349fb0f1644ad3b908f1fb1337c`. The installed runtime was
`codex-cli 0.145.0`.

The operator authorized copying only `/home/xai/.codex/auth.json` into two
new, independent private Codex homes and at most three inference starts in the
strict order S2 → P1 → P2. All three slots used `gpt-5.6-luna` with reasoning
effort `xhigh`.

## Result

All three structured measurement turns completed successfully:

| Slot | Mode | Thread | Turn | First action | Schema | Semantics |
|---|---|---|---|---|---|---|
| S2 | stateless A4 | `019f98c8-123a-7781-aa3c-dfa556d89f92` | `019f98c8-127f-7e53-bbe3-598b316e3765` | `request_diagnostic` | valid | valid |
| P1 | persistent A1 | `019f98c9-df7d-78d1-a134-1a988305d19d` | `019f98c9-df8c-7a32-9b82-391e8be435f7` | `start_lane` | valid | valid |
| P2 | persistent A4 | `019f98c9-df7d-78d1-a134-1a988305d19d` | `019f98ca-9321-7cd3-8fb7-4fd7bc96e508` | `schedule_verification` | valid | valid |

P1 and P2 used exactly the same persisted thread. S2 used a separate fresh
thread. No historical failed thread was resumed.

Every decision remained `measurement_only: true` and `executed: false`. The
machine report preserves every request, turn, final item, reasoning-item and
decision identifier, together with the complete raw and normalized decisions.

## Model contract and isolation

Before inference in each arm, the server-reported effective contract matched:

```text
expected_model: gpt-5.6-luna
expected_reasoning_effort: xhigh
effective_model: gpt-5.6-luna
effective_reasoning_effort: xhigh
model_contract_matched: true
```

The strict preflight and both runtime arms established:

- separate private `CODEX_HOME`, `CODEX_SQLITE_HOME`, and empty runtime work
  directories;
- six absolute bundled skill paths before disable and zero active skills after
  disable/reload, with no `skills/list` error;
- custom 682-byte Director base instructions with SHA-256
  `bb79f9078bf017c9079d10fc1619dfe52072d58172977a7868b5201c2c37f151`;
- empty `agents_md`, disabled app/plugin instructions, and no selected runtime
  environments or workspace roots;
- no normal Codex-home path, repository path, skill instruction block or tool
  item in either rollout.

Platform-owned sandbox/developer instructions and the minimal environment
wrapper remained visible in both complete rollouts. World-state metadata also
retained `skills.includeInstructions: true` and
`host_skills.includeInstructions: true`; this did not activate a skill or add
a skill instruction message.

## Usage and latency

| Slot | Input | Cached | Cache write | Output | Reasoning output | Server total | Wall |
|---|---:|---:|---:|---:|---:|---:|---:|
| S2 | 9,591 | 0 | 0 | 6,215 | 5,438 | 15,806 | 117.191 s |
| P1 | 4,405 | 0 | 0 | 2,093 | 1,384 | 6,498 | 45.910 s |
| P2 | 12,754 | 0 | 0 | 4,245 | 3,421 | 16,999 | 80.439 s |

Persistent-arm total usage was 23,497 server tokens. Stateless-arm total usage
was 15,806 server tokens. Across all three authorized turns the server reported
39,303 total tokens.

For the byte-identical A4 scientific request:

```text
P2 input - S2 input: 3163 tokens
stateless input-token reduction: 24.800062725419476%
stateless total-token reduction: 7.01805988587564%
P2 wall time - S2 wall time: -36.75284232478589 seconds
```

Both A4 decisions were schema-valid and semantically valid. They diverged in
their first recommendation: S2 requested a diagnostic focused on residual
forbidden-cycle structure, while P2 scheduled exact verification of the
retained rejected candidate. P1 recommended an
`iterated_local_search_tabu` lane, but the recommendation was not executed.

This one pair supports `stateless_turns` under the predefined decision rule
because the measured input-token reduction exceeds 20% without loss of
semantic validity or completion reliability. It does not establish statistical
superiority.

## Zero-execution and persistence evidence

```text
inference starts reaching model: 3
successful completed turns: 3
timed out or aborted turns: 0
retries reaching inference: 0
tool calls: 0
search batches: 0
research lanes: 0
action dispatches: 0
candidate evaluations: 0
compaction operations: 0
```

Both App Server processes shut down gracefully. Both measurement databases and
their SQLite Online Backups report schema version 9 and
`integrity_check=ok`. Opaque server-returned rollout paths were inspected
inside their respective private homes.

The private audit manifest contains 610 non-credential artifacts and has
SHA-256
`548c7637e020edca819256767f82621a741e8cccc5c7cc08d421ed630b5081dc`.
The runner report has SHA-256
`a9fbe538f6953f568935345a0a79cbede12475c44acc5b0ec60faeb68cbf9b94`.
Credential hashes and private absolute paths remain only in the private runtime
report and are not committed.

## Final status

```text
canonical_evidence_registry: proven
incomplete_turn_persistence: proven
director_state_v2_bounded: proven
stateless_A4_completed: proven
persistent_A1_completed: proven
persistent_A4_completed: proven
exactly_three_or_fewer_inference_starts: proven
zero_retries_reaching_inference: proven
zero_search_batches: proven
zero_action_dispatches: proven
zero_candidate_evaluations: proven
zero_compaction_operations: proven
zero_tool_calls: proven
usage_accounting_complete: proven
semantic_validity_stateless_A4: proven
semantic_validity_persistent_A4: proven
stateless_token_reduction_percent: 24.800062725419476
completion_reliability_comparison: both_completed
context_mode_comparison: complete_single_pair
recommended_default_context_mode: stateless_turns
```

Machine-readable result:
`docs/reports/M6_REDUCED_CONTEXT_SCREEN_RERUN.json`.
