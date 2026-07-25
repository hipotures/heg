# Bounded comparison worker

The comparison worker is the execution half of the M7 control plane. It runs
one already-prepared, exactly-authorized comparison suite and exits. It is not
a queue, daemon, research controller, or Director action dispatcher.

## Operator workflow

Install a complete immutable fixture bundle with a local administrative
command:

```bash
sglab comparisons install-fixture \
  --workspace ./workspace \
  --fixture ./director-fixture.json
```

For a preserved scientific campaign, create an isolated live-comparison
workspace and executable A4 fixture without copying the source database or
private runtime homes:

```bash
sglab comparisons import-campaign-snapshot \
  --source-workspace ./workspace/preserved-campaign \
  --workspace ./workspace/model-comparisons-live \
  --snapshot A4 \
  --display-name "M6 executable preserved A4"
```

The importer takes an SQLite Online Backup for consistent read-only
validation, copies only the hash-verified snapshot artifact, creates a fresh
current schema-v13 database, and derives the prompt, schema, registries, action space,
base instructions, and campaign budget deterministically. It rejects
synthetic/demo sources and private or absolute runtime references.

The bundle contains DirectorStateV2, prompt, output schema, applicable action
space, evidence/advisory/executable registries, custom base instructions,
empty developer instructions, and campaign budget. Import calculates and
stores every hash. The browser never accepts this path.

Start the local dashboard:

```bash
SGLAB_DASHBOARD_TOKEN='choose-a-local-token' \
SGLAB_CODEX_AUTH_SOURCE='/server/configured/auth.json' \
sglab serve --workspace ./workspace --host 127.0.0.1 --port 8080
```

Open `/comparisons`, create a suite, prepare it, inspect the immutable plan,
authorize that fingerprint, and click Start. The protected endpoint launches
only:

```text
<sys.executable> -m sglab comparisons worker
  --workspace <configured-workspace>
  --suite-id <validated-suite-id>
```

It uses an argv list, never `shell=True`, and accepts no browser-supplied
executable, command, auth path, or environment variable. Direct administrative
launch uses the same entry point:

```bash
sglab comparisons worker \
  --workspace ./workspace \
  --suite-id comparison-...
```

## Exact plan and authorization

Before auth access or App Server startup, the worker reloads the suite,
fixture, arms, ordering, dependencies, hashes, limits, and authorization. It
recomputes the complete plan fingerprint and verifies:

- every arm is unchanged and authorized;
- models, efforts, modes, arm count, and inference cap match;
- fixture material matches all persisted SHA-256 values;
- DirectorStateV2 is at most 32 KiB and the conservative client estimate is
  within the per-turn cap;
- `measurement_only=true` and `execute_decisions=false`;
- developer instructions are empty and custom base instructions are nonempty;
- `compacted_thread` is not executable in this milestone.

The safe verification artifact is written below
`.sglab/comparisons/<suite-id>/attempts/`. It contains relative references,
not credentials or private absolute paths.

Each inference has a transactional reservation. The reservation is persisted
before `turn/start`, becomes consumed when that request reaches the runtime,
and is never refunded afterward. A reservation released before inference does
not consume the authorization. Server retry notifications are rejected by the
one-inference policy.

## State machines

Suite lifecycle:

```text
draft → prepared → authorized → running
      → completed | failed | stopped
```

Audited arm lifecycle:

```text
planned → preflight → auth_prepared → server_started → thread_ready
        → inference_reserved → inference_started
        → completed | schema_invalid | semantic_invalid | timed_out
        | aborted | failed | blocked | stopped
```

Every transition is append-only in `comparison_arm_transitions`.
`comparison_turns` links to the existing `app_server_turns` row once a real
turn exists. Request/thread/turn/item correlation, reasoning items, late abort,
nullable final answer, nullable usage, and terminal reason therefore use the
same durable lifecycle as the proven M6 client.

## Ordering and context modes

The worker follows persisted `effective_order`; display names carry no
semantics. Randomization shuffles conversation groups as blocks, preserving
their internal sequence.

- `stateless_turns`: every arm has a separate private runtime and fresh thread.
- `persistent_thread`: only explicitly grouped arms may share a runtime.
  The first starts a fresh thread; later arms with
  `resume_prior_thread=true` resume that exact thread and depend on prior
  success.
- `compacted_thread`: remains an explicit catalog alternative, but execution
  is rejected before auth access because this milestone authorizes no
  compaction.

A failed required predecessor blocks its dependent arm. With the default
`fail_closed=true`, any invalid or failed arm blocks every later arm and no
replacement or retry is created.

## Private runtime

Each suite receives a new private execution root. Each independent arm or
persistent conversation group receives separate application data containing:

```text
director/codex-home
director/codex-sqlite-home
director/codex-work
wire
stderr
audit
```

Only the server-configured regular file named `auth.json` is copied, with mode
`0600`, after plan verification. No config, history, sessions, SQLite,
skills, prompts, or AGENTS.md are copied. The original auth-source environment
variable is removed before App Server launch. Credential contents are never
inspected by resource accounting; credential metadata has a redacted private
category and is excluded from manifests and public reports.

The existing hardened client supplies strict config, custom base instructions,
empty developer instructions, personality none, read-only sandbox, approval
never, empty environments/dynamic tools/capability roots/runtime roots, and
the complete skills disable/reload gate. Unsupported server requests, malformed
JSONL, tool items, contract mismatches, and retry notifications fail closed.

## Lease, heartbeat, and recovery

`comparison_worker_leases` records instance ID, suite, attempt, PID, process
group, host, acquisition, heartbeat, expiry, release, and terminal reason.
Acquisition uses `BEGIN IMMEDIATE`. An unexpired lease or a verified live PID
prevents a duplicate worker. Heartbeats refresh every two seconds; the default
lease is 15 seconds.

The default concurrent-suite limit is one. A trusted server operator may set
`SGLAB_COMPARISON_MAX_CONCURRENT` to a locally validated value from 1 through
8; the browser cannot set it.

After web-server restart, progress is reconstructed from SQLite and a second
Start is refused. After an expired lease and dead PID, recovery marks the
attempt and suite failed, releases only reservations that never reached
inference, and never resumes paid work automatically. Consumed starts and
incomplete `app_server_turns` remain inspectable.

Dashboard-launched comparison workers remain in a bounded registry of owned
`Popen` handles. The HTTP server's nonblocking service loop polls only those
children, which performs the equivalent of `waitpid(..., WNOHANG)`, persists
the return code and reaping timestamp, and removes the live registration.
Terminal attempt persistence is owned by the worker and does not depend on
reaping. `/proc` state `Z` is treated as non-live during restart recovery, so
a zombie PID cannot block a future unrelated suite. No global `waitpid` is
used.

## Stop and limits

`POST /api/comparisons/<id>/stop` records a stop request and returns. It accepts
no PID. An idle authorized suite stops immediately. An active worker observes
the request, sends `turn/interrupt`, persists correlation, drains late events,
closes the App Server, and releases its lease. SIGTERM/SIGKILL fallback is
recorded as forced termination.

Plans bound:

- inference starts and turns;
- timeout per turn;
- authoritative total server tokens;
- estimated client tokens per turn;
- App Server stdout, stderr, and wire retention;
- preserved artifacts and each preserved file;
- private runtime scratch and each runtime file;
- worker wall time;
- concurrent suites.

Cached input and reasoning output remain subsets of their parent categories.
Server `totalTokens` is authoritative. Missing usage is `null`; when a strict
total-token cap is configured, missing usage stops the suite fail closed.

## Resource accounting

Schema v12 replaces the ambiguous whole-execution-tree
`maximum_artifact_directory_bytes` check with four stable categories:

- `preserved_artifacts`: immutable request, response, DirectorStateV2,
  registries/schema material, bounded preserved logs, plan verification,
  manifests, reports, and explicitly requested SQLite Online Backups;
- `runtime_scratch`: private Codex homes, SQLite homes, WAL/SHM files,
  sessions, rollouts, work directories, and process temporary files;
- `credential_material`: only the isolated credential file, whose contents
  are never opened by the accounting code;
- `logs`: live App Server wire/stderr/stdout and worker log material before
  final preservation.

New suites default to 64 MiB total preserved artifacts, 512 MiB runtime
scratch, 32 MiB for one preserved file, and 256 MiB for one runtime file.
Wire, stderr, stdout, and worker wall time retain independent configurable
limits. The deprecated artifact-directory field maps only to the preserved
quota; it never also becomes the scratch quota. Every limit is serialized
into the schema-2.1 plan and therefore changes the authorization fingerprint.
Legacy schema-2.0 plans remain reproducible for audit but cannot start a new
worker.

One `lstat`-based traversal supplies both telemetry and enforcement. It never
follows symlinks, classifies them independently of bytes, deduplicates regular files by
device/inode, records apparent and allocated bytes, detects sparse files, and
fails on inaccessible entries or bounded traversal limits. It traverses only
the suite execution root.

Schema v13 separates `byte_quota`, `single_file_quota`, `log_quota`,
`filesystem_policy`, `accounting_error`, `process_lifecycle`, and
`app_server_protocol`. Every sample records byte-quota status, accounting
status, symlink-policy status, failure domain/code, and bounded safe symlink
metadata. A numeric `current > limit` message is constructed only after that
inequality has been checked.

The only accepted escaping links are the four App Server wrappers
`apply_patch`, `applypatch`, `codex-execve-wrapper`, and
`codex-linux-sandbox`, at the reviewed private
`app-server-tmp/arg0/<wrapper>` location. Their target must resolve below a
server-discovered Codex installation root, be a regular executable, be
non-world-writable, and be outside the research workspace. Discovery uses the
server-owned launcher, never browser input, suite metadata, or model output.
Only the safe wrapper label, basename, trust class, root class, and policy
decision are persisted. The target path is never persisted or rendered.

Each link is inspected with `lstat`, `readlink`, target metadata, and a second
`lstat` of both link and trusted target. Type or inode changes become an
explicit accounting error. Internal links remain non-followed and rejected
unless a future reviewed policy explicitly permits them. Broken, unreadable,
wrong-directory, untrusted-target, and unexpected external links fail closed
as filesystem policy, never as scratch-byte exhaustion.

`comparison_resource_samples` retains at most the latest, peak,
threshold-crossing, and terminal row for each category and attempt. Samples
include file count, largest bounded file/directory summaries, the last growth
event, lifecycle stage, enforcement decision, interruption status, and
cleanup result. At a threshold crossing the worker commits the SQLite row and
a bounded private diagnostic before interrupting or cleaning up the runtime.
The diagnostic contains only safe relative labels and never credential
contents or hashes.

Preserved writes with known size are checked before the write. Runtime-scratch
crossings interrupt an active turn when applicable, drain late events, close
the App Server, fail the suite, and block later arms. A turn already persisted
as completed and valid is not rewritten to failed when later shutdown or
preservation infrastructure fails; the suite records the infrastructure
failure separately.

The bounded in-memory log collector retains the original observed byte count
and emits a truncation marker when it discards older bytes. This prevents
silent unbounded log growth while keeping the preserved copy inside its own
limit.

## Web progress

The detail page polls the bounded read APIs:

```text
GET /api/comparisons/<id>/progress
GET /api/comparisons/<id>/turns
```

It displays suite/worker/lease/stop state, completed and consumed counts,
current arm lifecycle, model/context contracts, usage, latency, validity,
decision, and validation issues. It does not expose auth paths, auth hashes,
private absolute paths, or unrestricted logs, and it never dispatches the
returned decision.

Manual and blind ratings continue to use the existing append-only M7 records.
Blind responses omit model, effort, context, token, latency, cost, and worker
usage details until submission.

## Deterministic validation

The production worker state machine is exercised against the existing stdio
App Server client with a synthetic fake executable. Covered outcomes include
success, persistent resume, schema/semantic invalidity, timeout, late abort,
missing usage, tool attempt, model/context mismatch, malformed JSONL,
unsupported request, retry rejection, process crash, graceful close, forced
shutdown, 80 MiB transient scratch below quota, scratch and WAL threshold
crossings, preserved-write and single-file rejection, bounded log growth, and
an infrastructure failure after a valid completed arm. Standalone accounting
tests cover sparse files, hard links, symlink escape, redacted credentials,
and traversal bounds.

The HTTP replay demonstration creates, prepares, authorizes, and starts a
four-arm suite. Stateless S2 and persistent P1 complete, persistent P2 times
out, and the fourth arm is blocked. It then records a manual rating and blind
pairwise rating. It performs zero real model calls, real auth accesses, search
batches, action dispatches, graph evaluations, compactions, or tool
executions.

## Known limitations

- The first bounded authenticated comparison remains an incomplete historical
  high-only measurement. Its suite and consumed authorization are terminal
  and must not be reused.
- Public M6 historical fixtures intentionally contain only safe descriptors
  and hashes; they stay read-only and are not executable. A new executable
  suite needs a complete immutable fixture bundle.
- The corrected runtime path is deterministically covered with the fake App
  Server. Any fresh authenticated smoke requires a new suite, fingerprint,
  authorization, and private runtime homes.
- `compacted_thread` execution and retry policies require new fingerprinted
  authorization.
- Default-context evidence is one controlled S2/P2 pair, not statistical
  superiority.
