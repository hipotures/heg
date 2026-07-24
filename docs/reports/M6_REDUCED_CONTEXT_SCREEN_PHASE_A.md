# Reduced context-mode screen: deterministic Phase A

Date: **2026-07-24**

Phase A prepared a fresh reduced context screen without reading or copying
`auth.json`, starting the installed Codex App Server, calling a model, resuming
the historical failed thread, changing preserved failure artifacts, or running
a graph-search batch. The tested baseline was
`fd151508fafe9ec5b69ac5af444dc43ee5297e27`; `planning/` remained the only
unrelated untracked content.

## Preserved baseline

The preserved failure report, unchanged P1 response, and complete rollout
retain their recorded SHA-256 values:

- failure report:
  `dba6963f017a134beb5a8b04aa3f5a4d3db653dd0b44e230b95fc9d855fd5d2f`;
- P1 response:
  `860a5ca9344ac713a82654f3a077cb7a5e2244ffb504f09796abf901fa55c804`;
- rollout:
  `ec3837ec17808f080cfab915fe18dee073d13993bdc11cdc866aa3e6ddea3614`.

Offline validation used the preserved request, response, and corrected
canonical registry without changing the model output:

```text
persistent_P1_schema_valid: true
persistent_P1_semantic_revalidation: valid
```

Both disputed references remain visible in the submitted A1
DirectorStateV2. SQLite production schema version is 9. The runtime plan
explicitly prohibits reuse of the historical failed thread.

## Three-slot contract

The prepared order is fixed:

1. S2 — fresh `stateless_turns` A4 thread;
2. P1 — fresh `persistent_thread` A1 thread;
3. P2 — A4 on exactly the thread created by P1.

There is no fourth slot. Fake-server tests prove fail-closed sequencing:
failure or timeout at S2 prevents P1 and P2; failure or timeout at P1 prevents
P2; and P2 timeout persists its incomplete lifecycle, interrupts the
authoritative turn, drains late abort events, and terminates the screen.
Requests that reached inference are never retried or replaced.

All slots use the same model, reasoning effort, base instructions, empty
developer instructions, `personality: none`, output schema, serializer,
semantic validator, action space, read-only sandbox, `approvalPolicy: never`,
and empty environments, dynamic tools, capability roots, and workspace roots.
The hard timeout is 300 seconds.

The screen contains no `LaneManager`, search kernel, candidate evaluator,
action dispatcher, graph verifier, search worker, or batch executor. Every
decision is wrapped as `measurement_only: true`, `executed: false`.

## S2/P2 equivalence

S2 and P2 have identical A4 scientific input before any runtime-generated
request, thread, turn, or item identifiers:

| Input | SHA-256 |
|---|---|
| DirectorStateV2 | `cb714203abc8ead33c746704a1f9ed01c67f19c6d1c08217ee74b4c8da77fe0b` |
| prompt | `839ca51fb2a458b6f54702d99c8f91811d211c1c85e11df3d2c15a30f6831f05` |
| output schema | `cf577dcde83b7f33e2106f327aaa970d4878e1635c7cf1f5b2dba4e3c06b1049` |
| evidence registry | `0c230a07895c9da021e5111a08e4797e4452a01c88e6cd62556f310a018a8f1a` |
| allowed action space | `02e9e228b098f8cd32611cfc77fd9574f4b24e5cf1fa0852784ee4144fe02e10` |
| target metadata | `6db3a2a05e6ad7e66100f3c337618023eed19095e7d94ac4272fce2373f72ce5` |
| campaign budget | `31e7fad5b6cb280aab8dfbc86ebd356fdd65e9821da0b542c5f7cfaa0527ce84` |
| artifact references | `1110750775df3b4efc47316f3a93443e5eb05490c151e28e2fd04c5ff385c32a` |
| complete request template | `b865409f85458bfdf3678682091bb8d05403d6b1b0f67b321e74d289f614edc8` |

The only intended difference is conversation history retained from P1 by the
P2 thread.

## Context budgets

| Slot | State | Ancestry | History | Prompt | Schema | Request | Estimated input |
|---|---:|---:|---:|---:|---:|---:|---:|
| S2 | 16,709 B | 5,611 B | 3,593 B | 17,544 B | 20,855 B | 40,377 B | 9,771 tokens |
| P1 | 3,033 B | 65 B | 2 B | 3,868 B | 20,855 B | 25,421 B | 6,352 tokens |
| P2 | 16,709 B | 5,611 B | 3,593 B | 17,544 B | 20,855 B | 40,377 B | 9,771 tokens |

Every request stays below the 32 KiB Director state, 8 KiB ancestry, 12 KiB
historical outcome, and 12,000 estimated client-token limits. The canonical
registry is built only after final deterministic state compaction and remains
stable through JSON round-trip and SQLite reopen.

## Deterministic verification

- focused evidence-registry, incomplete-turn, timeout, late-abort,
  nullable-usage, restart-inspection, and no-continuation tests: passed;
- complete safe suite: 125 tests, passed twice;
- installed app-server compliance test: deliberately omitted because Phase A
  forbids starting the installed App Server;
- `make doctor`: passed;
- `make check`: passed;
- `make benchmark-smoke`: passed;
- `make dashboard-smoke`: passed;
- preserved v8 SQLite Online Backup SHA-256:
  `e121468da08aab95237592c2a774633bef6562cb251e67196dc82f29714937af`;
- backup before migration: `user_version=8`, `integrity_check=ok`;
- migrated backup: `user_version=9`, `integrity_check=ok`;
- original database SHA-256 remained
  `9333d63394baa8ab3a98a8c2236fcaa7ccff77b727e8a1d2c8115dc166c20a29`.

The deterministic phase generated no model inference, auth access, installed
App Server process, search batch, lane, action dispatch, candidate evaluation,
compaction operation, or tool call.

Machine-readable result:
`docs/reports/M6_REDUCED_CONTEXT_SCREEN_PHASE_A.json`.

## Phase B boundary

Phase B remains blocked until explicit authorization to copy only
`/home/xai/.codex/auth.json` into two new, separate private runtime homes and
perform at most three inference starts in the strict order S2 → P1 → P2.
Authorization must retain zero search batches, compaction operations, and tool
calls. No statistical-superiority claim can be supported by one S2/P2 pair.
