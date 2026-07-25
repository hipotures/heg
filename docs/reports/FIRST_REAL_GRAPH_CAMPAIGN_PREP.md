# First real graph campaign — preparation report

Prepared at: `2026-07-25T20:27:36Z`

## Identity

- Target: Erdős–Gyárfás conjecture
- Workspace: `workspace/first-real-graph-campaign-01`
- Workspace kind: `first_real_graph_campaign`
- Synthetic data: `false`
- Baseline commit: `594dabb8aea8586f02d9e54dbf55e6dae820b721`
- Tested implementation commit: `61ee3771a068e341a1ecf785b67c36c863e8be2d`
- Campaign ID: `campaign-b68ec445388e49b2be0b6fabf8ff6600`
- Plan fingerprint: `827291f2ac5f4f4c591bfb287ad4075c4ef612cf7fa797a5cdf27821bd4c125d`
- Plan artifact SHA-256: `0473320720ddc806dd5ee5a6da7165558b39e50041f605785e92a6701509b960`
- Target-definition SHA-256: `e1f40a0bb11ee46ff54f772a5d4117ea37ac81a3482082a4017836ea2fabd19e`

The durable campaign row is `prepared`, has no deadline yet, and has no
sessions, Director turns, lanes, actions, candidates, or verification jobs.
The one-hour deadline starts only after exact-plan authorization and campaign
start.

## Director contract

- Model: `gpt-5.6-luna`
- Reasoning effort: `high`
- Context: `stateless_turns`
- Maximum scientific cycles: `12`
- Maximum App Server turns including validation replans: `24`
- Maximum turn time: `300` seconds
- Maximum replans for one identical scientific state: `1`
- Replan context: fresh stateless thread
- Model tools: disabled
- Shell/code requests: disabled
- Automatic compaction: disabled
- Provider recovery/retry attempts: `0`

A valid Director decision is dispatched through the existing reviewed action
space. An invalid response is persisted and no action from it is executed. The
same bounded scientific state, together with validation errors, may be sent
once on a fresh stateless thread. A second invalid response stops the campaign
cleanly. Infrastructure, protocol, resource, authentication, and verifier
failures remain fail-closed.

## Stop and scientific contract

The campaign stops at the first of:

1. an exact M4 independent-verifier certificate for a counterexample;
2. `3,600` seconds of campaign wall time.

Heuristic score is never certification. Capped witness counts remain marked
approximate or truncated. Verifier disagreement stops the affected candidate
path and triggers review. Success cannot be reported without the persisted M4
certificate. The campaign is adaptive and contains no fixed experiment
sequence.

## Search and verification limits

- Maximum active search lanes: `8`
- Maximum resource share per lane: `1.0`
- Maximum aggregate resource share: `8.0`
- Memory limit per lane: `536,870,912` bytes
- Event queue: `512`
- Command queue per lane: `32`
- Telemetry windows per lane: `120`
- Checkpoints per lane: `8`
- Pinned checkpoints: `128`
- Verification queue: `32`
- Concurrent verification jobs: `1`
- Timeout per exact verification path: `60` seconds
- Memory per verifier path: `536,870,912` bytes
- Verification broker memory: `1,073,741,824` bytes

The resource-share values are bounded scheduling shares. The host reported 32
logical CPUs and no cgroup CPU hard limit during preparation.

## App Server and runtime limits

- Resource accounting version: `2`
- Runtime scratch: `536,870,912` bytes
- Single runtime file: `268,435,456` bytes
- Wire log: `8,388,608` bytes
- Stderr: `262,144` bytes
- Stdout/JSONL: `2,097,152` bytes
- Symlink policy: `expected_app_server_wrappers_v1`

The installed no-model compliance audit passed for Codex CLI `0.145.0`;
its safe report SHA-256 is
`e3dc19714d90e148d1f8ff1e22c3f80b0d3f1b0d41f67d363ee41850edaace6c`.
The dashboard is reachable only on `127.0.0.1:8788`.

## Deterministic gates

- Focused campaign/protocol tests: `26/26` passed
- Full safe suite: `241/241` passed on the final implementation
- `make doctor`: passed
- `make test`: passed
- `make check`: passed
- `make benchmark-smoke`: passed
- `make dashboard-smoke`: passed
- SQLite schema: `14`
- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: no rows
- Prepared-plan fingerprint recomputation: exact match
- Dashboard campaign API: HTTP `200`, state `prepared`
- Auth imported: `false`
- Model inference starts: `0`
- Auth reads/copies: `0`
- App Server turns: `0`
- Search lanes/actions: `0`
- Graph-search batches: `0`

## Authorization boundary

No credentials have been read or copied and no model runtime has been created.
Starting requires a new explicit authorization naming the campaign ID and exact
plan fingerprint above. After authorization, only the named campaign-private
runtime may receive `auth.json`; start must recompute the fingerprint before
App Server startup.
