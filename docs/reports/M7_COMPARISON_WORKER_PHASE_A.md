# M7 bounded comparison worker — deterministic Phase A

Date: 2026-07-25

## Result

The M7 comparison control plane now has a bounded, auditable execution worker.
It consumes one prepared and exactly authorized plan, runs only its persisted
arms, and exits after completion, failure, stop, authorization exhaustion, or
lease loss. Browser Start launches a fixed Python entry point without a shell;
browser Stop records a request that the owning worker observes.

This milestone used only a synthetic App Server and fake auth fixture. It made
no model inference, read no real auth file, started no authenticated App Server
turn, and ran no paid comparison. The worker and replay demonstration created
no research lane, graph-search batch, candidate evaluation, action dispatch,
compaction operation, or tool execution.

`ready_for_bounded_authenticated_comparison` is true for a future, separately
authorized bounded smoke comparison. It is not authorization to run one.

## Preserved baseline

- Initial production commit:
  `45c93e3441a2a8e95733d5cf56848a31d8c2b6c3`
- Annotated tag `m6-context-optimization-proven` still targets:
  `110f805e56fac39c241bd33e423ee00324c33caf`
- Preserved M6 JSON report SHA-256:
  `a1f01415059494161b5c0d9feb608160e48afff1e3b23404e234eec87f27883c`
- Preserved M6 Markdown report SHA-256:
  `b339e14e959755ba8fec5f475b443cb1df39652a92af22c5249d722ae82ceef8`
- `planning/` remained the only unrelated untracked content and was not
  modified.
- `stateless_turns` remains the production Director default.
- Explicit `persistent_thread` and `compacted_thread` catalog choices remain.
- Imported historical comparison rows remain read-only and unchanged.

## Execution contract

The worker command is:

```text
sglab comparisons worker --workspace <workspace> --suite-id <suite-id>
```

Before auth access or App Server startup, it:

1. reloads the suite, fixture, arms, exact ordering, dependencies, limits, and
   authorization;
2. recomputes the canonical plan fingerprint;
3. verifies every arm and fixture material hash;
4. verifies authorized model, effort, context mode, arm count, and inference
   maximum;
5. requires `measurement_only=true` and `execute_decisions=false`;
6. rejects `compacted_thread` execution in this milestone;
7. writes a safe pre-execution verification artifact and its SHA-256.

Inference authorization is transactionally reserved before `turn/start`.
The reservation is marked consumed when the request reaches inference and is
never refunded afterward. A failure before inference releases an unused
reservation. Retry notifications are rejected and no replacement arm is
created.

## Persistence and ownership

SQLite schema version 11 adds durable execution attempts, leases, stop
requests, inference reservations, arm transition history, persistent
conversation grouping, and the minimal comparison-to-App-Server lifecycle
bridge. It does not duplicate usage stored by `app_server_turns`.

Worker leases are acquired with an immediate transaction and record worker
instance, suite, PID, process group, host, heartbeat, expiry, release, and
terminal reason. The default maximum number of concurrently running suites is
one. A live or unexpired lease rejects duplicate Start. A web-server restart
reconstructs progress from SQLite; an expired lease with a dead PID is failed
closed and never resumes paid work automatically.

Per-arm transitions are append-only:

```text
planned → preflight → auth_prepared → server_started → thread_ready
        → inference_reserved → inference_started
        → completed | schema_invalid | semantic_invalid | timed_out
        | aborted | failed | blocked | stopped
```

An authoritative turn ID creates or updates `app_server_turns` immediately.
Final answer and usage remain nullable. Request, thread, turn, item, reasoning,
event-sequence, timeout, late-abort, and raw-artifact correlation is retained.

## Context sequencing and isolation

- A stateless arm always starts a fresh thread in its own private runtime.
- A persistent sequence shares a thread only through an explicit
  `conversation_group_id`; later arms resume exactly the successful preceding
  thread.
- Display names do not determine ordering or dependencies.
- Random ordering shuffles conversation groups as blocks.
- A failed required predecessor blocks dependent arms.

Each independent arm or persistent group receives separate private
`CODEX_HOME`, `CODEX_SQLITE_HOME`, empty runtime workspace, wire, stderr, and
audit directories. The future real path copies only the server-configured
regular file named `auth.json`, with mode `0600`, after deterministic plan
verification. The browser cannot supply the auth source, executable, command,
environment, or arbitrary path. Auth is excluded from manifests and UI
responses.

The existing hardened App Server client supplies strict configuration, the
complete skills disable/reload gate, custom base instructions, empty developer
instructions, personality none, read-only sandbox, approval never, and empty
environments, tools, capability roots, and runtime roots. Model and context
contracts must match before inference.

## Stop, failure, and limits

`POST /api/comparisons/<id>/stop` persists a stop request and returns without
accepting or killing a browser-supplied PID. The worker stops before the next
arm when idle, or interrupts the active turn, drains late events, closes the
App Server, records forced termination when required, marks later arms
stopped/blocked, and releases its lease.

Failures in preflight, model/context contract, timeout, interruption,
structured output, schema, semantics, server protocol, tool policy, inference
budget, or lease ownership stop the default fail-closed suite. No later
inference and no retry follows a reached inference.

Plans bound inference starts, turns, per-turn timeout, total authoritative
tokens, estimated client tokens, retained stdout/stderr/wire bytes, artifact
bytes, worker wall time, and concurrent suites. Missing usage remains `null`.
A strict total-token cap with missing usage stops fail closed. Cached input and
reasoning output are never added again to authoritative total tokens.

## Web control plane

The protected Start endpoint uses:

```text
<sys.executable> -m sglab comparisons worker
  --workspace <configured-workspace>
  --suite-id <validated-suite-id>
```

It uses an argv list, `start_new_session=True`, and never `shell=True`.
Progress polling exposes bounded suite, lease, stop, transition, contract,
usage, latency, validity, and decision data. It does not expose credential
data, auth paths or hashes, private runtime paths, or unrestricted logs.
Returned Director decisions remain read-only and are never dispatched.

## Deterministic replay demonstration

The real HTTP control plane launched the production comparison-worker state
machine against the hardened stdio client and synthetic fake server:

- four planned arms;
- three inference starts;
- one stateless fresh thread;
- one persistent fresh-then-resume sequence;
- two completed turns;
- one timed-out turn;
- one later arm blocked by fail-closed sequencing;
- one manual rating;
- one blind pairwise rating.

The fake adapter also covered schema-invalid and semantic-invalid output,
timeout, late abort, missing usage, tool attempt, model mismatch, context
mismatch, malformed JSONL, unsupported request, retry rejection, App Server
crash, graceful shutdown, forced shutdown, persistent resume, and stateless
fresh threads. Tests run this adapter through production worker logic rather
than a simplified execution path.

## Verification

All deterministic gates passed:

- focused comparison-worker tests: 16/16;
- complete safe suite, first pass: 169/169;
- complete safe suite, second pass: 169/169;
- final `make test`: 169/169;
- explicit loopback HTTP tests: 8/8;
- `make doctor`: pass;
- `make check`: pass;
- `make benchmark-smoke`: pass;
- `make dashboard-smoke`: pass;
- SQLite schema: 11;
- SQLite `integrity_check`: `ok`;
- SQLite `foreign_key_check`: no rows;
- v10 → v11 migration through SQLite Online Backup: pass;
- orphan comparison-worker/fake-server processes: 0.

The required complete suite and benchmark smoke exercise existing deterministic
search functionality. This does not change the narrower result that the
comparison worker and replay demonstration themselves created zero search
batches, lanes, evaluations, or dispatches.

## Remaining uncertainties

- No authenticated comparison was executed. The real runtime path still needs
  a separately authorized bounded smoke comparison.
- Safe imported M6 fixture descriptors omit private executable prompt/state
  material and therefore remain historical and non-executable.
- `compacted_thread` execution and any retry policy require a future exact
  plan and separate authorization.
- The stateless default rests on one controlled S2/P2 pair and is not a claim
  of statistical superiority.

## Final status

```text
comparison_worker_created: true
fixed_worker_launch_created: true
worker_lease_created: true
worker_heartbeat_created: true
plan_fingerprint_enforced: true
authorization_consumption_enforced: true
inference_cap_enforced: true
stateless_execution_supported: true
persistent_sequence_supported: true
fail_closed_supported: true
turn_interrupt_supported: true
nullable_usage_preserved: true
stop_control_supported: true
crash_recovery_supported: true
live_web_progress_created: true
fake_server_end_to_end_passed: true
historical_suites_preserved: true
zero_model_inferences: true
zero_real_auth_access: true
zero_graph_search_batches: true
zero_action_dispatches: true
zero_tool_calls: true
http_tests_passed: true
sqlite_integrity_check: ok
ready_for_bounded_authenticated_comparison: true
```
