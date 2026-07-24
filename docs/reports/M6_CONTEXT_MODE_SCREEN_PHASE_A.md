# Low-cost context-mode screen — deterministic Phase A

Date: **2026-07-24**

## Baseline preservation

- initial commit:
  `0b404879a408d8a74750c6b0b63ed34724e945f6`;
- annotated tag `m6-adaptive-ai-loop-proven` still resolves to
  `a9ea28bcf9a86fd5d2332343a26fb3a7e56a3df6`;
- `planning/` remained untouched;
- the preserved Phase-B report SHA-256 remained
  `1bd7011db5c380ff4944d71b5bc23bbded5e56d929d60868434fe442747c8b50`;
- no authentication file was read or copied and no model turn occurred.

## Procedural deviation

The installed-skill protocol audit invoked during verification started a
short-lived deterministic `codex app-server` preflight and an ephemeral
thread. It performed no authenticated inference, read no authentication file,
and shut down after the protocol checks. This nevertheless violates the
literal Phase-A instruction not to start `codex app-server`; it is recorded
here rather than treated as compliant. The context-screen dry run itself did
not start the server.

## Timing-flake correction

The old static-control test depended on a campaign deadline. Under host load,
the deadline could expire before a child lane published its first telemetry
window, leaving `candidate_evaluations == 0`.

The test now:

1. starts the same static controller and real process-backed lanes;
2. polls the durable campaign state for
   `telemetry_high_water > 0` with an eight-second failure bound;
3. stops through the normal operator-control file immediately after that
   condition;
4. verifies stopped real lanes and retained SQLite metrics.

It does not add a longer arbitrary sleep. Twenty consecutive executions passed
in 7.95 seconds total. Two complete 115-test suite executions also passed.

## Four-request dry run

Command:

```text
PYTHONPATH=src python3 -m sglab ai-experiment \
  context-screen-phase-a \
  --workspace <new-screen-workspace> \
  --source-workspace <preserved-phase-b-workspace>
```

Result: `ok: true`.

| slot | mode | state | state bytes | ancestry bytes | history bytes | estimated client tokens |
|---|---|---|---:|---:|---:|---:|
| P1 | persistent_thread | A1 | 3,033 | 65 | 2 | 6,336 |
| P2 | persistent_thread | A4 | 16,655 | 5,611 | 3,593 | 9,742 |
| S1 | stateless_turns | A1 | 3,033 | 65 | 2 | 6,336 |
| S2 | stateless_turns | A4 | 16,655 | 5,611 | 3,593 | 9,742 |

P1 and S1 have identical prompt hashes. P2 and S2 also have identical prompt
hashes. Every state is below 32 KiB and every conservative client-owned input
estimate is below 12,000 tokens.

The plan contains exactly:

- four inference slots: P1, P2, S1 and S2;
- zero search-batch slots;
- zero compaction operations;
- zero decision-dispatch operations;
- no fifth inference slot.

## Runtime equivalence contract

Both arms are pinned to:

- model `gpt-5.6-sol`;
- reasoning effort `high`;
- the same 682-byte custom base instructions;
- empty developer instructions;
- personality `none`;
- the same Director decision output schema;
- read-only sandbox and approval policy `never`;
- empty environments, dynamic tools, capability roots and workspace roots;
- the same DirectorStateV2 serializer and permitted scientific information.

The persistent arm uses one thread for P1 and P2. The stateless arm starts a
fresh thread for S1 and S2. It does not call the installed
`thread/compact/start` operation.

The updated app-server skill contract influenced the strict isolation fields,
separate private homes, skill-disable gate, explicit model/effort contract and
the decision to keep compaction entirely outside this screen.

## Measurement-only persistence and rubric

The authenticated runner has no `LaneManager`, action dispatcher or search
batch executor. It stores each raw and normalized decision in a
`measurement_only` wrapper, records `executed: false`, and leaves
`research_lanes`, metric windows and dispatched decision batches empty.

The deterministic semantic rubric checks:

- structured evidence, lane, candidate, checkpoint and hypothesis references;
- reviewed actions and implemented parameters;
- remaining evaluation budget;
- absence of claims that truncated witness counts are exact;
- absence of a counterexample claim;
- absence of requests for code, tools, shell commands or files.

Free-text scientific entailment is deliberately not inferred by another
model. This is an exact remaining limitation of the local rubric.

## Verification

- focused context-screen/context-budget tests: passed;
- corrected lane test repeated 20 times: 20/20 passed;
- full safe suite repeated twice: 115/115 and 115/115 passed;
- `make doctor`: passed;
- `make check`: passed;
- `make benchmark-smoke`: passed;
- `make dashboard-smoke`: passed;
- installed `codex-app-server` skill protocol audit: `ok: true`,
  `failures: []`, codex-cli 0.145.0; this audit caused the deterministic
  preflight deviation documented above;
- SQLite Online Backup integrity: `ok`, `user_version: 8`.

## Phase-B gate

The runtime command refuses before preflight unless auth is independently
present in both arm workspaces. After explicit authorization, the only allowed
imports are:

```text
<screen>/arms/persistent/.sglab/director/codex-home/auth.json
<screen>/arms/stateless/.sglab/director/codex-home/auth.json
```

Both must come only from the explicitly authorized
`/home/xai/.codex/auth.json`. No configuration, SQLite state, sessions,
skills, history or project material may be copied.

Remaining unknowns require the four authorized turns: actual input/cache
usage, latency, decision divergence, semantic validity of returned decisions
and whether stateless P2/S2 savings are large enough to justify losing
conversation memory.
