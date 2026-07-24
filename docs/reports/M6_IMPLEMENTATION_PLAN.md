# M6 Active Director Implementation Plan

This plan maps the target package onto the actual `sglab` repository. Every
milestone ends with focused verification, updates to
`docs/IMPLEMENTATION_STATUS.md` and its milestone report, and a local commit
containing only M6 implementation artifacts.

## M6.0 — baseline freeze

Files:

- `docs/reports/M6_BASELINE_AUDIT.md`
- `docs/reports/M6_BASELINE_AUDIT.json`
- this plan

Gate: baseline tag exists, current five repository gates pass, schema v1 and
all real boundaries are recorded.

## M6.1 — installed protocol and isolated app-server client

Add:

- `src/sglab/research/app_server_client.py`
- `src/sglab/research/app_server_protocol.py`
- `src/sglab/research/auth.py`
- `src/sglab/research/__init__.py`
- focused fake-server and installed-server tests
- `docs/reports/M6_APP_SERVER_PREFLIGHT.md/.json`

Extend:

- `cli.py` with `ai-director preflight`, explicit `auth-import`,
  `inspect-session`, and `verify-isolation`
- package data for Director prompt/schema assets

Implementation:

- generate schemas from the installed binary and hash the exact files;
- launch `codex app-server --stdio` directly with a private home/work dir;
- initialize once, disable all discovered skills, start/resume persisted
  threads, correlate interleaved events, parse final output and usage;
- reject unsupported server requests, bound stderr/wire logs, apply timeouts
  and process-group cleanup;
- import only explicitly authorized auth material.

Gate: fake protocol faults pass; live greeting and structured turn are saved;
rollout inspection proves isolation and persistence.

## M6.2 — additive schema v7 and Director contracts

Add:

- `src/sglab/research/protocol.py`
- `src/sglab/research/catalog.py`
- `src/sglab/research/validation.py`
- `src/sglab/research/store.py`
- `src/sglab/research/director.py`
- production schemas and compact base instructions under package data
- `sql/007_active_director.sql`, adapted from schema v1

Extend:

- `db.py` from schema 1 to schema 7 with ordered, idempotent additive
  migrations;
- tests using SQLite online backup snapshots for migration experiments.

The store adds campaign/session/turn/snapshot/trigger/lane/revision/window/
action/outcome/hypothesis/terminal entities without changing current tables.
Strict Python validation narrows the planning schemas to actual algorithms,
graph families, numeric domains, evidence IDs, lane versions, resource
envelopes, idempotency keys, and leases.

Gate: migration integrity, strict contract tests, deterministic and replay
providers, persistent same-thread Director turns.

## M6.3 — stateful lane execution

Add:

- `src/sglab/research/lanes.py`
- `src/sglab/research/telemetry.py`
- `src/sglab/research/actions.py`

Refactor surgically:

- extract the mutation/acceptance loop in `search.py` into a deterministic
  micro-batch function;
- preserve `run_search` and legacy `SearchConfig`;
- represent each lane as one stateful process with RNG/graph/algorithm state,
  a bounded command mailbox, telemetry output, checkpoint lineage, version and
  lease;
- apply patch/fork/restart/stop/resource actions only after a committed
  micro-batch checkpoint;
- route retained candidates to a separate bounded M4 broker invoking the
  unchanged `certify`.

Gate: two lanes progress concurrently; safe patch, fork, stale rejection,
idempotency, lease and restart tests pass; the legacy search tests still pass.

## M6.4 — event-driven campaign supervisor

Add:

- `src/sglab/research/triggers.py`
- `src/sglab/research/snapshot.py`
- `src/sglab/research/hypotheses.py`
- `src/sglab/research/terminal.py`
- `src/sglab/research/orchestrator.py`

Implementation:

- coalesce bounded critical/non-critical triggers;
- commit immutable snapshots with evidence allowlists and high-water marks;
- run app-server inference asynchronously while lanes continue;
- atomically validate/commit action batches before delivery;
- measure expected versus observed effects and surface them in the next turn;
- resume the same thread and lane checkpoints after process restart;
- enforce deadline/M4 success latch and provider lease-expiry fault behavior.

Gate: one deterministic/fake-provider campaign proves observe → hypothesize →
intervene → measure → update, including continued search during provider
latency and recovery without deterministic takeover.

## M6.5 — campaign CLI, dashboard, replay and export

Extend:

- `cli.py` with `research-campaign start/status/pause/resume/stop/export`;
- `web.py` with typed campaign POSTs and read-only Director/lane queries;
- `web/index.html` with only the target and stop selector in the normal
  campaign form;
- `state.py`/`artifacts.py` with bounded audit/export helpers.

Compatibility:

- retain `sglab run`, `resume`, and their tuning flags as explicitly legacy
  baseline/research-engine commands;
- do not expose them in the normal Active Director form.

Gate: mutually exclusive stop modes, no normal tuning inputs, emergency
controls, bounded dashboard payloads, replay and export without auth.

## M6.6 — live acceptance and scientific controls

Add:

- a deliberately false/hidden-witness test target, clearly separated from the
  open Erdős–Gyárfás profile;
- static, random, serial-AI compatibility and M6 active controllers under
  equal budgets;
- multi-seed benchmark and active-control demonstration commands;
- required reports and append-only issue/decision ledgers.

Gate in one live app-server campaign:

- at least two lanes remain live;
- AI patches one lane and forks/reallocates another before completion;
- counters increase during Director inference;
- a later turn evaluates a prior intervention;
- restart resumes the same thread and checkpoints;
- M4 certifies the control witness or the explicit deadline is reached.

No superiority claim is made unless the multi-seed study supports it.

## M6.7 — production hardening

Exercise provider outages, malformed protocol, rollover, stale completions,
lease expiry, crash recovery, bounded database/prompt/wire/archive growth, and
dashboard responsiveness. Run and preserve a two-hour minimum soak.

Final gates:

```text
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

plus all M6-specific preflight, active-control, recovery, export/replay,
hidden-witness, multi-seed and soak gates. M6 is marked complete only after
the single live acceptance campaign and two-hour soak are documented.
