# Implementation Status

Last implementation audit: **2026-07-26**.

## Scientific observatory

The live campaign dashboard now includes a bounded read-only scientific
observatory. It renders the global-best graph, a 10-second configurable live
search-frontier sample, a lane-best graph, the immutable candidate currently
consumed by M4, or a retained historical candidate.
Server-side `graph6` decoding keeps raw encodings and artifact paths out of the
browser contract. Distinct overlays show bounded non-certifying cycle examples
and hash-checked persisted M4 witnesses without conflating heuristic evidence
with certification. Live frontier checkpoints are size-bounded, opened without
following symlinks, integrity-checked, and explicitly labelled transient
heuristic telemetry.

Supporting tabs show weighted-penalty history, cycle profiles, lane telemetry,
verification state, and retained-candidate history. SQLite reads and browser
lists are bounded. Desktop and phone Playwright-CDP checks confirm responsive
layout, no page-wide horizontal overflow, and preservation of the selected
tab, graph viewport, and scroll position across repeated dashboard polls. The
observatory is read-only and creates no model, search, action, or verifier side
effect. See `docs/SCIENTIFIC_OBSERVATORY.md`.

## Campaign execution attempts, candidate lifetime, and scientific memory

SQLite schema v15 separates a durable scientific campaign from immutable
execution attempts. Start and Resume record attempt reason, code commit,
requested/effective application resources, incremental wall time, starting
memory/checkpoints, inherited and local counters, provenance, and terminal
outcome. The campaign ID and scientific contract remain stable while CPU
worker slots, active lanes, lane/verifier memory, verifier concurrency, and
queue bounds may change per attempt. Resume supports operator, budget,
repaired-infrastructure, interrupted-process, and host-restart continuity and
rejects live, certified, or scientifically invalidated campaigns.

Candidate-target actions now validate against the current executable registry,
transactionally create an immutable graph snapshot and durable pin, and make
M4 consume that snapshot. Pinned candidates cannot be pruned or deleted.
Pins release only after all references are terminal. A stale target is
persisted specifically, never executed, and permits one fresh stateless replan
with the current valid registry. Historical stale actions are excluded from
Resume execution.

Deterministic scientific-memory snapshots bound the canonical Director state
at 32,768 bytes, compact at a 24,576-byte soft threshold, and snapshot every
five valid cycles plus every terminal/Resume boundary. Exact-verifier facts
and current executable IDs are non-droppable; full raw history remains in
SQLite/artifacts. Every Director turn and execution attempt records the
snapshot it used.

The production state machine completed a model-free 65+65 second continuation:
the same campaign advanced from 69,995 to 140,918 cumulative evaluations,
reused two verified checkpoints and its terminal memory snapshot, preserved
four prior M4 outcomes and its hypothesis, and changed application worker
slots from 2 to 16 without duplicate actions. Protected HTTP controls and
Playwright CDP verify attempt history, cumulative/local metrics, repair
acknowledgement, resource differences, and desktop/mobile Resume preview.
The real paused campaign produces a read-only Resume preview with the current
set of hash-valid reusable checkpoints and its historical missing-candidate
action excluded. No real model or auth access occurred. See
`docs/CAMPAIGN_RESUME.md`,
`docs/CAMPAIGN_SCIENTIFIC_MEMORY.md`, and
`docs/reports/CAMPAIGN_RESUME_AND_MEMORY_PHASE_A.md`.

The first production Resume exposed a legacy-shape boundary missed by the
fake/replay demonstrations: raw stored lane mutation ancestry made the
pre-Resume snapshot 368,573 bytes, above its 256 KiB artifact contract.
Snapshot construction now derives the same bounded telemetry summary used for
live lanes while leaving every raw metric row unchanged. The exact preserved
campaign shape now produces a 69,803-byte snapshot and a 15,861-byte
scientific-memory projection. The dashboard now waits for the immutable
execution-attempt row before claiming that Resume started and reports a
pre-attempt subprocess exit instead of returning a misleading PID. Resume
previews continue to report historical stale actions after they are already
terminalized.

The first attempt-scoped production Resume then exposed a second compatibility
boundary: expected App Server wrappers were accepted below the legacy
`runtime-groups` tree but not below the new immutable attempt
`application-data` tree. The same strict four-name, `codex-arg0-*`,
trusted-executable policy now recognizes both private layouts. Targets remain
non-followed for accounting, wrong-directory/untrusted links remain rejected,
and the failed execution attempt remains immutable historical evidence.

A later production attempt completed a valid Director turn but the stateless
response reused four descriptive `action_id` values from an earlier batch
with new idempotency keys. SQLite therefore raised the workspace-wide primary
key constraint before any of those returned actions executed. The Director
contract now supplies a deterministic per-snapshot action-ID namespace, the
semantic context rejects every durable workspace collision, and decision
persistence performs an atomic collision preflight. A race discovered only at
commit time is recorded as `rejected_action_id_collision` and receives at most
one fresh stateless replan; it is no longer surfaced as a raw
`IntegrityError`. The historical failed attempt and its records remain
unchanged.

## First real graph campaign authorization gate

The production campaign CLI now has a deterministic `prepare` boundary for a
fresh non-synthetic workspace. It creates a durable `prepared` campaign row,
an exact plan artifact, campaign ID, and canonical fingerprint before any
credential access. Campaign-specific auth import and start both require that
exact fingerprint. The fixed one-hour contract binds Luna/high/stateless,
twelve scientific cycles, at most twenty-four App Server turns including one
possible replan per state, eight bounded search lanes, M4 verifier limits, and
App Server diagnostic/runtime quotas. Per-lane and aggregate CPU-share bounds
are explicit in the fingerprinted search contract.

The existing production orchestrator and action space remain authoritative;
there is no scripted experiment sequence. Valid Director actions are
dispatched. Invalid responses are persisted and never executed. One invalid
response may be replanned only on a fresh stateless thread with the identical
DirectorStateV2 and validation errors; a second invalid response stops the
runtime fail-closed. Prepared campaigns disable App Server retries and provider
recovery.

The campaign's private App Server tree now uses the reviewed no-follow
resource-accounting and expected-wrapper policy. Scratch and single-file
limits, bounded wire/stderr/stdout, safe peak telemetry, strict model/effort
matching, and graceful shutdown are part of the fingerprinted contract.
Preparation and installed protocol compliance perform no model turn and do
not access authentication.

## M7 hypothesis and independent-arm contracts

SQLite schema v14 adds a nullable, fingerprinted arm-failure policy. Historical
suite rows remain null, retain plan schema 2.1, and recompute to their original
fingerprints. New measurement-only comparison plans use schema 2.2 and
`independent_invalid_continue_v1`: a schema-invalid or semantic-invalid
independent result is retained and the next independent arm runs, while
infrastructure, security, protocol, resource, and model-contract failures
still stop later arms. A persistent dependent arm still requires a completed
predecessor. All returned actions remain unexecuted.

The Director prompt, generated schema, and semantic validator now share an
operation-specific hypothesis-update contract. `create` requires a new,
response-unique ID. `confirm`, `weaken`, `reject`, `retain`, and `revise`
require an ID from the submitted hypothesis registry. The preserved Luna-high
response used `revise` for unknown `H0`; it therefore remains semantically
invalid and the new generated schema rejects that shape structurally.

Focused production-worker tests cover both invalid-result classes continuing
to a second independent arm, infrastructure fail-closed behavior, dependent
persistent blocking, and zero action execution. The complete 236-test safe
suite, doctor, compile checks, benchmark/dashboard smoke, schema-v14 Online
Backup migration, SQLite integrity, and foreign-key checks pass. No model,
auth, graph-search, or action-dispatch path was used. See
`docs/reports/M7_HYPOTHESIS_CONTRACT_FIX.md`.

## M7 comparison symlink policy and worker reaping

Schema v13 separates byte inequalities, single-file and log caps, filesystem
policy, accounting errors, process lifecycle, and App Server protocol
failures. The four reviewed App Server `arg0` wrapper names are accepted only
at the exact private runtime location and only when their target is a stable,
regular, executable, non-world-writable file below the server-discovered
Codex installation root and outside the research workspace. Accounting never
follows a target or charges its bytes, and persists only safe relative labels
and trust classes.

Deterministic production-worker tests cover the exact four wrappers, unexpected
external and wrong-directory links, untrusted and broken targets, link inode
races, genuine aggregate and single-file crossings, two successful arms, and
a ten-run wrapper soak. Filesystem failures no longer carry scratch limits or
false `current > limit` messages. The historical second suite remains
terminal and unchanged; its UI derives the corrected legacy explanation from
the v12 crossing sample.

The dashboard now polls only its owned comparison `Popen` handles, persists
the reaping result, removes completed registrations, and treats Linux zombie
state as non-live. HTTP tests prove successful and failed workers are reaped
while the dashboard remains responsive and terminal detail remains readable.

The installed no-auth lifecycle smoke starts, initializes, accounts, shuts
down, and reaps Codex without `thread/start` or `turn/start`. The installed
build creates no `arg0` wrapper symlinks in that bounded phase, so direct
classification of real installed wrappers remains unproven without crossing
the explicitly forbidden thread boundary. Consequently a fresh authenticated
comparison is not yet declared ready.

## M7 second real comparison failed before inference

Fresh authorization bound the schema-2.1/accounting-v2 Luna high-versus-xhigh
suite to its unchanged fingerprint and exact two-start contract. The plan
verification passed, a private runtime was prepared, and the App Server
process started. The worker then failed closed at
`after_app_server_start`, before thread creation, inference reservation, or
model inference. Luna high is an infrastructure failure and Luna xhigh is
blocked/not started. No authoritative tokens, search batches, actions, model
tools, or ratings exist.

Persisted telemetry proves that no byte quota was exceeded: scratch peaked at
2,274,115 apparent bytes against 536,870,912, while preserved artifacts peaked
at 4,878 against 67,108,864. Instead, the App Server created four transient
executable-wrapper symlinks in its private `arg0` directory. Accounting
correctly did not follow them, but worker enforcement converted any escaping
symlink into an aggregate `runtime_scratch` quota violation. The terminal
message and UI therefore show the false numeric comparison
`2,274,115 > 536,870,912`.

The diagnostic was persisted before shutdown, the lease was released, SQLite
integrity and foreign keys remain clean, and final process checks show no
worker, App Server, dashboard, or zombie. The suite is terminal and must not
be reused. A deterministic fix for normal App Server transient symlinks and
the misleading failure classification is required before another authorized
comparison. See
`docs/reports/M7_SECOND_REAL_COMPARISON_RUNTIME.md`.

## M7 comparison resource accounting repaired deterministically

SQLite schema v12 and the comparison worker now separate preserved artifacts,
private runtime scratch, credential material, and logs. New plans fingerprint
independent 64 MiB preserved, 512 MiB scratch, 32 MiB single-preserved-file,
256 MiB single-runtime-file, wire, stderr, stdout, and wall-time limits. The
deprecated artifact-directory limit maps only to preserved artifacts. Legacy
plans remain hash-stable and cannot be executed again.

One bounded `lstat` traversal supplies enforcement and telemetry, does not
follow symlinks, rejects escape, deduplicates hard links by device/inode,
reports apparent and allocated bytes, identifies sparse files, redacts
credential paths, and fails closed on inaccessible or over-bound traversal.
The worker persists bounded latest/peak/crossing/terminal summaries and a
private threshold diagnostic before interruption or cleanup. A valid completed
arm remains valid when later shutdown infrastructure fails.

The fake App Server proves 80 MiB transient scratch no longer consumes the
preserved quota; scratch/WAL crossings retain exact attribution after cleanup;
large preserved writes fail before creation; single-file and log bounds work;
two valid arms complete sequentially; the lease is released and no fake
process remains. The closest original-shape reproduction proves the old code
incorrectly combined runtime scratch with artifacts. The exact historical
transient contributor is unresolved because only the 6,083,415-byte
post-shutdown non-auth tree remains.

The failed Luna suite is unchanged: one consumed inference, high completed
valid, xhigh never started, and the original fingerprint recomputes exactly.
The UI now renders that history as an incomplete legacy infrastructure
failure and shows separated resource controls for future suites. See
`docs/reports/M7_COMPARISON_RESOURCE_ACCOUNTING_PHASE_A.md`.

## M7 first real comparison runtime failed closed

Fresh explicit authorization bound the prepared Luna high-versus-xhigh suite
to its unchanged fingerprint, two stateless contracts, and at most two
inference starts. The randomized high arm ran first and completed with a final
answer, matching effective model/effort/context, schema and semantic validity,
9,755 authoritative tokens, and 73.64 seconds total latency. Its returned
actions remained measurement-only and unexecuted.

The worker then failed closed on the 64 MiB comparison artifact-directory
limit before starting xhigh. Exactly one inference start was consumed; there
was no retry, replacement, second/third inference, search batch, lane, action
dispatch, candidate evaluation, compaction, or model tool call. The App Server
closed gracefully, the lease was released, and no worker/App Server orphan
remains. Because only one valid response exists, blind pairwise rating is not
available and no user rating was recorded.

The terminal UI exposed and then received a focused fix for rendering a
structured action-space object; the corrected page renders the completed turn
and disables all terminal controls. The complete 194-test suite, doctor,
compile checks, benchmark/dashboard smoke, SQLite integrity, and foreign-key
checks pass. See `docs/reports/M7_FIRST_REAL_COMPARISON_RUNTIME.md`.

## M7 first real comparison deterministic preparation complete

The dedicated non-synthetic `model_comparison_live` workspace now contains a
complete executable preserved-A4 fixture and one immutable prepared suite for
`gpt-5.6-luna` high versus xhigh in fresh `stateless_turns`. The schema-v11
workspace was built with SQLite Online Backup and a safe scientific-artifact
import; it contains no auth, sessions, Codex homes, rollouts, or wire logs.
All arm-input hashes match and the fixture's conservative client-owned input
estimate is 6,516 tokens under the 12,000-token limit.

The exact plan permits at most two 300-second inference starts and 40,000
authoritative server tokens, with measurement-only, no decision execution,
fail-closed sequencing, seed 20260725, zero search batches, zero action
dispatches, zero model tools, zero compactions, and zero retries reaching
inference. Playwright CDP created and prepared the suite through the rendered
UI and verified the safe API response. The plan remains unauthorized with zero
turns, reservations, attempts, leases, lanes, batches, and actions.

The complete 194-test suite, doctor, compile checks, benchmark/dashboard smoke,
schema-v11 integrity, and foreign-key checks pass. No auth content was read or
copied and no model inference occurred. Phase B remains stopped at the fresh
explicit authorization boundary. See
`docs/reports/M7_FIRST_REAL_COMPARISON_PREP.md`.

## M7 preserved A4 comparison import complete

The `sglab comparisons import-campaign-snapshot` administrative command now
creates a dedicated `model_comparison_live` workspace from one hash-verified
preserved campaign snapshot. It validates a read-only SQLite Online Backup,
copies only the scientific snapshot artifact, derives the complete executable
Director fixture, creates a fresh schema-v11 database, and records a
non-synthetic marker without credential hashes or private runtime paths.
Synthetic/demo sources, absolute paths, auth references, Codex homes,
sessions, rollouts, and wire references are rejected.

The redesigned comparison form and detail view retain every bounded-worker
resource limit, persistent-thread dependency field, fixed Start/Stop controls,
and bounded live progress polling while keeping semantic cards and responsive
layouts. Focused importer, worker, persistence, and UI tests cover the merged
behavior.

## M7 browser UI redesign complete

The research dashboard and controlled-comparison pages now use semantic
decision, effect, lane, candidate, plan, usage, and cost views. Raw protocol
JSON remains available as secondary technical evidence. Primary lists are
bounded, long identifiers are abbreviated without losing the complete value,
tables are locally contained, and narrow viewports use responsive card
layouts.

All pages now provide light and dark themes through shared design tokens. The
header toggle persists the browser preference in `localStorage` and falls back
to the operating-system color-scheme preference when unset. Typography,
focus visibility, field grouping, empty/error states, and status labelling
were normalized without adding a frontend framework or build step.

The user-started port-8787 demo server was inspected through Playwright-CDP at
1920×1080, 1440×900, 1280×720, 1024×768, and 390×844. All route shapes,
comparison lifecycle states, empty/error states, both themes, technical
disclosures, and deterministic forms were exercised. The phone layout has no
page-wide overflow and its primary controls provide 44-pixel touch targets.
Normal routes produced no console or network failures; the intentional unknown
route produced the expected styled 404.

The complete 175-test safe suite passes twice, as do focused HTTP/UI tests,
doctor, compile checks, benchmark/dashboard smoke, and SQLite v10 integrity.
See `docs/reports/M7_UI_PLAYWRIGHT_AUDIT_BEFORE.md` and
`docs/reports/M7_UI_PLAYWRIGHT_AUDIT_AFTER.md`.

## M7 deterministic UI-review fixture complete

The `sglab ui-fixture create` command now creates a rich, isolated and
reproducible `ui_demo` workspace for browser review. Fixed IDs, timestamps and
seeded content cover campaign, Director action/effect, lane, candidate,
hypothesis, telemetry, App Server lifecycle, event, comparison, rating and
cost-profile states without model calls, auth access, external network or a
production search campaign. Replacement is allowed only for a workspace with
the exact synthetic demo marker.

The generated review workspace contains 8 campaigns, 24 decisions, 12 lanes,
40 campaign candidates, 110 metric windows, 12 hypotheses, 12 App Server
turns and 9 comparison suites, including the unchanged read-only M6 S2/P1/P2
result. Two same-seed generations produce byte-identical SQLite databases and
the same logical SHA-256. The fixture is 0.72 MiB, schema v10 integrity is
`ok`, and view-data construction remains below 20 ms maximum in the recorded
local sample.

Focused fixture tests pass 5/5, the complete safe suite passes 158/158, and
doctor, check, benchmark/dashboard smoke and SQLite foreign-key checks pass.
Phase A deliberately stops before starting the port-8787 server or any
Playwright-CDP inspection. See
`docs/reports/M7_UI_REVIEW_FIXTURE.md`.

## M7 bounded comparison worker complete

SQLite schema v11 now persists comparison execution attempts, exclusive worker
leases and heartbeats, stop requests, inference reservations, explicit
persistent-conversation dependencies, and append-only arm transitions. The
worker consumes one immutable authorized plan, verifies its fingerprint before
auth access, reserves each inference transactionally, and never exceeds the
authorized cap. It supports fresh stateless arms and explicit persistent
sequences; compacted execution remains disabled pending a future exact plan.

The bearer-protected Start endpoint launches only the fixed
`sys.executable -m sglab comparisons worker` argv in a separate process group,
without a shell or browser-controlled executable, auth path, command, or
environment. The detail page polls bounded progress APIs for lease, heartbeat,
stop, lifecycle, contracts, usage, latency, and validity. Stop is a durable
request observed by the worker, which interrupts and drains an active turn
before bounded shutdown.

The real worker state machine was tested through the hardened App Server client
and a synthetic stdio server, including persistent resume, stateless fresh
threads, invalid output, timeout and late abort, nullable usage, tool/retry
rejection, protocol errors, crashes, forced shutdown, lease loss, and
fail-closed dependency blocking. The replay HTTP demonstration planned four
arms, reached three fake inference starts, completed two, timed out one, and
blocked the last; it also preserved manual and blind ratings.

Focused tests pass 16/16, two complete safe-suite runs and final `make test`
pass 169/169, explicit loopback tests pass 8/8, and doctor, check,
benchmark/dashboard smoke, SQLite
v10→v11 Online Backup migration, integrity and foreign-key checks pass. The
demonstration made zero real model calls or auth accesses and the comparison
worker created zero search batches, lanes, evaluations, action dispatches,
compactions, or tool executions. See
`docs/reports/M7_COMPARISON_WORKER_PHASE_A.md`,
`docs/COMPARISON_WORKER.md`, and `docs/COMPARISON_UI.md`.

## M7 controlled comparison UI and persistence complete

SQLite schema v10 now provides a comparison subsystem separate from research
campaigns: immutable fixtures and plans, bounded arms and turns, exact-plan
authorizations, append-only manual and blind pairwise ratings, and immutable
cost-profile snapshots. The standard-library dashboard exposes suite list,
creation, preflight/authorization, detail, blind comparison, and cost-profile
pages with bearer-protected POST endpoints.

The production Director default is now `stateless_turns`, based on the single
controlled S2/P2 pair. Explicit `persistent_thread` and `compacted_thread`
remain available; persistent selection emits a token-growth warning. Context
mode and fresh/resumed thread provenance are persisted without rewriting
historical rows.

The deterministic M6 importer renders the real S2/P1/P2 results without
private paths or another model call. Usage accounting does not double-count
cached input or reasoning output, missing usage remains null, and human,
automatic-validity, and downstream-science metrics stay separate.

The deterministic replay dry run made zero model calls, auth accesses, search
batches, lanes, or action dispatches. Focused tests, two complete 153-test
runs, doctor, compile checks, benchmark/dashboard smoke, loopback HTTP, and
SQLite v10 migration/integrity checks pass. See
`docs/reports/M7_COMPARISON_UI_PHASE_A.md` and `docs/COMPARISON_UI.md`.

## Fresh reduced context-mode screen completed

The corrected three-slot authenticated screen completed S2, P1 and P2 with
exactly three successful `gpt-5.6-luna:xhigh` inference starts. S2 used a
fresh stateless A4 thread; P1 and P2 used one separate persistent thread. All
three decisions were schema-valid, semantically valid, measurement-only and
unexecuted.

The A4 scientific state, prompt, schema, evidence registry and applicable
action space were identical for S2 and P2. S2 used 9,591 input tokens versus
12,754 for P2, a measured stateless reduction of 24.800062725419476%. Both
completed reliably; the predefined single-pair decision rule therefore
recommends `stateless_turns`, without claiming statistical superiority.

The run used exactly three inference starts and zero retries, search batches,
lanes, action dispatches, candidate evaluations, compactions or tool calls.
Both App Server processes shut down gracefully, all skill reload gates ended
with zero active skills, and both SQLite databases and Online Backups passed
schema-v9 integrity checks. See
`docs/reports/M6_REDUCED_CONTEXT_SCREEN_RERUN.md`.

## Action-applicability contract repaired deterministically

DirectorStateV2 now separates visible evidence, advisory targets, and
executable targets into independently hashed registries derived from the final
submitted state. The same dynamic applicable-action space drives the prompt,
structured output schema, and semantic validator. Lane-bound actions and lane
ID enums appear only when an active executable lane exists; historical lanes
remain explicitly visible as non-executable evidence.

The fresh offline reduced-screen plan retains exactly S2 → P1 → P2. A1 offers
`start_lane`, `request_diagnostic`, and `set_review_trigger`; A4 additionally
offers candidate promotion and M4 verification, but no lane-bound action.
S2/P2 remain byte-identical across state, prompt, schema, all three registries,
and applicable action space. Context limits pass, and no inference, auth
access, authenticated App Server turn, or graph-search batch occurred.

The preserved S2 result is now correctly classified as
`indeterminate_due_to_action_applicability_contract_mismatch`. Its raw
`stop_lane` output is not valid under the corrected space because that action
should not have been offered; it is not classified as an independent
model-quality failure.

Focused tests, SQLite v9 migration/integrity tests, and two 128-test
non-network safe-suite runs pass. Doctor, compile checks, benchmark smoke, all
five previously blocked HTTP/dashboard tests, `make dashboard-smoke`, and the
complete 133-test Phase-A-safe suite pass. See
`docs/reports/M6_ACTION_APPLICABILITY_PHASE_A.md`.

## Reduced context-mode screen — deterministic Phase A complete

The replacement measurement screen now has exactly three fail-closed slots in
the fixed order S2 (fresh stateless A4), P1 (fresh persistent A1), and P2
(persistent A4 on the P1 thread). It has no fourth slot, compaction operation,
search lane, batch, candidate evaluation, or action dispatch. Decisions remain
`measurement_only` and are never executed. A 300-second per-turn hard timeout
persists incomplete correlation, uses `turn/interrupt`, drains late events, and
prevents every later slot after a failure.

The authorized runtime contract is now exactly `gpt-5.6-luna` with reasoning
effort `xhigh`. Before each arm's first inference, the client persists the
expected and server-reported effective values and refuses `turn/start` unless
both match. A deterministic mismatch test proves S2 is not submitted when the
server reports another model.

S2 and P2 use byte-identical A4 scientific state, prompt, output schema,
canonical evidence registry, action space, target, budget, artifact references,
and complete request template. Their only intended difference is P1 history
retained by the P2 thread. The A4 state is 16,709 bytes, ancestry is 5,611
bytes, historical outcomes are 3,593 bytes, and the conservative complete
client-input estimate is 9,771 tokens; all hard context gates pass.

Focused evidence/lifecycle/timeout tests and two complete 125-test safe-suite
runs pass. The one installed-app-server compliance test was deliberately
excluded because this phase prohibits starting the installed server.
`make doctor`, `make check`, `make benchmark-smoke`, `make dashboard-smoke`,
and v8-to-v9 migration/integrity checks on an SQLite Online Backup pass.
Historical failure artifacts and the P1 response retain their recorded hashes,
and offline P1 revalidation remains schema-valid and semantically valid. No
auth access, model inference, installed App Server start, or graph-search batch
occurred. See `docs/reports/M6_REDUCED_CONTEXT_SCREEN_PHASE_A.md`.

## Reduced context-mode screen — authenticated run stopped at S2

With explicit authorization, the runtime imported only `auth.json` into two
separate private homes and started the strict stateless arm first. The
server-reported model contract matched `gpt-5.6-luna:xhigh` before inference.
S2 completed with a final structured response and authoritative usage. Its
original semantic result is classified as
`indeterminate_due_to_action_applicability_contract_mismatch`: the submitted
schema exposed `stop_lane` even though its only referenced lane was historical
and non-executable. The preserved output is not valid under the corrected
action space, but this is a client-contract defect rather than an independent
model-quality failure.

Fail-closed sequencing then stopped before P1 and P2. The run therefore used
exactly one inference start, no retries, and zero search batches, lanes,
dispatches, candidate evaluations, compactions, or tool calls. Shutdown was
graceful and SQLite integrity was `ok`. The S2/P2 token comparison is
unavailable and the context-mode result remains inconclusive. See
`docs/reports/M6_REDUCED_CONTEXT_SCREEN_RUNTIME.md`.

## Context-screen deterministic failure fixes complete

The aborted persistent P1 output was revalidated offline without changing the
model response. Both disputed snapshot references were present in the exact
submitted DirectorStateV2, so the corrected canonical registry makes P1
schema-valid and semantically valid. The original semantic result is retained
as `indeterminate_due_to_validator_contract_mismatch`.

Schema v9 durably records requested, started, in-progress, completed, failed,
aborted, and timed-out app-server turn lifecycles. Request/thread/turn/item
correlation, reasoning IDs, event sequence, terminal reason, raw wire
reference, and nullable usage survive timeout and SQLite reopen. The timeout
path uses installed `turn/interrupt`, bounded event draining, and does not
continue to the stateless arm after a persistent-arm failure. See
`docs/reports/M6_CONTEXT_SCREEN_FAILURE_REVALIDATION.md`.

Focused lifecycle and evidence tests pass, as do two complete 121-test runs,
doctor, compile checks, benchmark smoke, dashboard smoke, and v8-to-v9
migration/integrity checks on an SQLite Online Backup. No inference, auth
access, app-server runtime start, or search batch was used for this repair.

## Low-cost context-mode screen — deterministic Phase A complete

A measurement-only A/B harness is prepared for `persistent_thread` versus
`stateless_turns`. It reconstructs preserved A1 and A4 through
DirectorStateV2, schedules exactly P1/P2/S1/S2, and contains no fifth turn,
search lane, search batch, decision dispatcher or compaction operation.
Corresponding P/S prompts are byte-identical. A1 is 3,033 bytes and A4 is
16,655 bytes; conservative complete-input estimates are 6,336 and 9,742
tokens.

The existing static-control timing flake now synchronizes on the first durable
lane evaluation and then uses normal operator stop. It passed 20 consecutive
runs, and the complete 115-test suite passed twice. No auth was read or copied
and no model turn occurred. A bundled installed-protocol audit did start a
short-lived deterministic app-server preflight and ephemeral thread, contrary
to the literal Phase-A no-server instruction; no inference occurred. Phase B
remains blocked on explicit authorization. See
`docs/reports/M6_CONTEXT_MODE_SCREEN_PHASE_A.md`.

## Director context management — deterministic preparation complete

The proven adaptive-loop baseline is preserved by annotated tag
`m6-adaptive-ai-loop-proven`, which points to
`a9ea28bcf9a86fd5d2332343a26fb3a7e56a3df6`. The Phase-B production-code
commit `a460dd752119eea9340d01e872956eab1b6c2580` is its ancestor; the only
intervening changes were the final runtime report and status. Director prompts
now use a strict, versioned `DirectorStateV2` containing at most three
outcomes, eight record summaries and eight accepted final-best ancestors,
with immutable hashes pointing to full artifacts. Full graphs, raw outcomes,
checkpoints, RNG state, metric windows and prior prompts are excluded.

A pre-turn gate persists pre/post compaction measurements and enforces 32 KiB
state, 8 KiB ancestry, 12 KiB historical outcomes and a conservative
12,000-token client-owned estimate. The four preserved Phase-B states compact
to 3.0–16.7 KiB and estimated total client inputs of 6.5–10.1 thousand tokens.
A 100-batch replay remains bounded at 16,682 bytes, preserves outcome hashes,
reconstructs after restart, validates all four decisions and still creates no
B4.

Three infrastructure modes are implemented without selecting a winner:
`persistent_thread`, installed-protocol `compacted_thread`, and
`stateless_turns`. No authenticated call was made. See
`docs/reports/M6_DIRECTOR_TOKEN_ATTRIBUTION.md`,
`docs/reports/M6_DIRECTOR_CONTEXT_GROWTH.md`, and
`docs/reports/M6_DIRECTOR_CONTEXT_MODES.md`.

## Adaptive multi-batch Director — authenticated Phase B complete

After explicit authorization, the bounded runtime campaign completed exactly
four authenticated turns on one persisted app-server thread and exactly three
10,000-evaluation search batches. O1 informed A2, O1/O2 informed A3, and
O1/O2/O3 informed the accepted final A4 decision. A4 stopped without creating
B4. Every search batch has a durable decision-committed event at evaluation
zero, stayed below 120 seconds, and ended with complete reference-verifier
rejection because a forbidden 4-cycle remained.

The Director changed from order-20 ILS-tabu to exact-score order-22 simulated
annealing, then to faster cap-64 order-22 ILS-tabu with adjusted mutation
weights and perturbation cadence. B3 improved the recorded lexicographic score
from `[0,3,48,0,30]` to `[0,3,40,0,33]`; this is a heuristic improvement, not
a counterexample or statistical-superiority claim.

One local 256 KiB snapshot-bound defect stopped the first app-server after B2
and before A3 inference. Historical snapshot ancestry is now compact while
complete outcome artifacts remain hashed and retained, and authenticated
execution can resume only from a verified durable boundary. The same thread
then completed the remaining two turns and one batch without another auth
copy. Both strict app-server processes shut down gracefully, no tool calls or
inference retries occurred, zero skills were active, and SQLite integrity is
`ok`. See `docs/reports/M6_ADAPTIVE_CAMPAIGN_RUNTIME.md`.

## Adaptive multi-batch Director — deterministic Phase A complete

The Director action space is now semantically enforced: ILS-tabu rejects
`restart_threshold`, `promotion_penalty` is campaign metadata rather than an
executable control, accepted actions durably record effective/ignored/rejected
parameters and parameter effects, and snapshots list implemented controls per
algorithm.

Search lanes support normalized weighted choice between the existing uniform
connected-cubic two-edge switch and a safe switch targeted at an edge of a
detected forbidden-cycle witness. Telemetry now includes per-operator uses,
accepted moves, global records and yield, a deterministic plateau signal,
witness truncation, actual restarts, bounded ancestry, timing and
expected-versus-measured outcome context.

The no-model adaptive replay completed four decisions and exactly three
300-evaluation order-20 batches on one replay thread. Each decision was
durable before its batch, every measured prior outcome appeared in the next
snapshot, A4 received all three outcomes, no B4 was created, the dashboard
exposed the state, and SQLite integrity was `ok`. The authenticated runner
subsequently passed the same four-turn/three-batch hard gates. See
`docs/reports/M6_ADAPTIVE_CAMPAIGN_PHASE_A.md` and
`docs/reports/M6_ADAPTIVE_CAMPAIGN_RUNTIME.md`.

## Search timing and mutation ancestry — offline complete

The authenticated order-20 ILS-tabu configuration was reproduced without
auth or model inference. It again produced the same 18 global records, best
score 3 at evaluation 921, final score 149, and exact-verifier rejection. An
instrumented and uninstrumented replay produced the same graph and score for
the same seed.

Search telemetry now separates mutation generation, graph validation, witness
counting, score calculation, duplicate detection, tabu bookkeeping, ancestry
construction, telemetry construction, SQLite persistence, and exact final
verification. The reproduced run spent 94.3% of its search-loop time counting
cycle witnesses; persistence and telemetry were each about one millisecond.
Controlled comparisons show that graph order and witness bound, not
instrumentation or SQLite, explain nearly all of the previous 16.8x
throughput difference.

Every global record now carries its parent candidate, mutation operator,
vertices and edge delta, before/after scores and witnesses, evaluation, and
record flag. Checkpoints retain at most 64 accepted transitions for the
current and best candidates, rejected non-records are not retained, and the
reviewed `mutation_ancestry` diagnostic reads bounded durable telemetry. See
`docs/reports/M6_SEARCH_MUTATION_ANCESTRY.md`.

The larger checkpoint messages also exposed and fixed a shutdown queue race:
the manager now drains complete worker events before joining or terminating a
lane, while deferring those events for the coordinator's single SQLite writer.
All 99 tests and the five repository gates pass.

## First AI-directed search experiment — live gate complete

The no-model Phase A gate now exercises the complete decision-to-search
boundary with the durable replay provider. It commits one validated
`start_lane` decision and a zero-evaluation application event before creating
the search kernel, runs exactly one wall/evaluation-bounded batch, persists
the checkpoint, candidate, telemetry, resource use, score trajectory,
operator statistics and reference-verifier result, publishes those measured
facts in the next Director snapshot, and persists a second validated decision
without dispatching it.

The preserved Phase A run used 300 simulated-annealing evaluations and ended
at its evaluation limit. SQLite integrity was `ok`; the database contained
two Director turns, two decision batches, one lane metric window and one
search lane. The campaign status API exposed the Director decision, selected
parameters, batch progress and measured outcome. The post-integration
Codex app-server no-model compliance audit also passed with `ok: true`,
zero active skills and an empty failure list.

The focused test additionally executes `random_restart`,
`simulated_annealing`, and `iterated_local_search_tabu` through the same
bounded one-batch primitive.

After explicit authorization, Phase B copied only the selected `auth.json`
into a new private home and completed exactly two app-server turns on one
thread. The first selected a 10,000-evaluation
`iterated_local_search_tabu` batch over order-20 connected cubic graphs. The
validated decision and zero-evaluation application event were durable before
the search kernel started. The bounded batch completed once, and its measured
outcome appeared in the second snapshot. The second turn classified the
result as `CHANGE_STRATEGY` and proposed a diagnostic; that decision was
validated and persisted but not dispatched.

There were no retry notifications, tool calls, unsupported server requests or
third turn. Only one lane metric window exists, the second action has no
outcome, app-server exited naturally, and SQLite integrity is `ok`. The best
candidate reduced the cheap-score witness total from 192 to 3, but the exact
reference verifier found a forbidden 4-cycle and rejected it; this is not a
counterexample claim. See
`docs/reports/M6_FIRST_AI_SEARCH_RUNTIME.md`.

## M6 Active Director — Phase 0 complete

The separately specified Active AI Research Director initiative has completed
its baseline freeze at commit
`bdacdb34b12086fe3f906bf3794397d81f4427ab`, tagged
`m6-baseline-bdacdb3`. The authoritative audit and actual-module
implementation plan are in `docs/reports/M6_BASELINE_AUDIT.md` and
`docs/reports/M6_IMPLEMENTATION_PLAN.md`.

The planning package assumed a different `gilab` M5 AI architecture and schema
v6. The real repository is `sglab`, has schema v1, and has no prior AI
provider. The Active Director work will therefore be an additive migration
around the existing stateful search workers and unchanged M4 certification
boundary. All five existing completion gates passed before implementation.
This is an implementation status only; no M6 Active Director completion claim
has been made.

### M6.1 app-server integration — deterministic compliance complete

The installed Codex 0.145.0 experimental schemas have been generated with
`--experimental` and hashed. The direct stdio JSON-RPC client now uses strict
configuration, distinct private Codex/config and SQLite homes, complete
two-pass skill disabling, explicit empty experimental isolation fields,
request/thread/turn/item correlation, schema-v8 cache-write token persistence,
opaque SQLite-backed rollout inspection, bounded final-usage collection, and
stdin-first graceful shutdown.

The deterministic no-model acceptance command passes every required condition
with zero active skills after reload and an empty failure list. See
`docs/reports/M6_APP_SERVER_PREFLIGHT.md` and
`docs/reports/M6_APP_SERVER_COMPLIANCE.json`.

The explicitly authorized runtime smoke then completed exactly two structured
model turns on one persisted thread, with a natural shutdown and fresh
app-server process between them. Both decisions passed the local semantic
validator, all token fields were captured, the opaque SQLite-backed rollout
inspection succeeded, and the resumed turn used new turn/item identifiers.

The smoke also exposed and fixed a concrete Structured Outputs compatibility
defect in the Director schema. Protocol/configuration compliance, local runtime
isolation, skill isolation, tool isolation, workspace isolation, structured
decision execution, and persisted thread resume are demonstrated. Absence of
platform-owned instructions is **unsupported**: the complete rollout contained
Codex multi-agent developer instructions and a `world_state` with
skill-instruction inclusion flags. Those instructions were not loaded from the
normal user Codex home, the repository, project `AGENTS.md`, active skills,
dynamic tools, or runtime workspace roots. The deprecated aggregate
`authenticated_runtime_isolation` is therefore recorded only as
`proven_for_local_inputs`. See
`docs/reports/M6_APP_SERVER_RUNTIME_SMOKE.md`. This is not a live research
campaign or an M6 completion claim.

### M6.2 durable Director contracts — offline milestone complete

Schema v1 now migrates additively to schema v8 with campaign, app-server,
snapshot, trigger, lane, action, hypothesis, verification-job, and terminal
state while preserving all existing tables. A migration of an SQLite
Online-Backup snapshot of the real workspace passed integrity checking and
left the original database unchanged.

The reviewed action catalog, exact output schema, strict semantic validator,
private audit artifacts, one-repair-turn Director lifecycle, optimistic
transactional decision commit, normalized usage, and replay provider are
implemented. The full suite now has 52 passing tests. See
`docs/reports/M6_DIRECTOR_CONTRACTS.md`. Live model acceptance remains coupled
to the explicit M6.1 authentication gate; no live-completion claim is made.

### M6.3 concurrent stateful lanes — offline milestone complete

The Active Director execution layer now exposes simulated annealing and
iterated local search as independent, long-lived spawned lane processes.
Every lane has an installed target, graph family, deterministic seed lineage,
immutable parent/checkpoint provenance, monotonically increasing version,
bounded mailbox and telemetry, retained hashed checkpoints, and a per-process
address-space limit. Actions are applied only between micro-batches.

Accepted actions are committed before delivery. The durable dispatcher covers
start, patch, fork, restart, stop, and atomic multi-lane resource allocation;
worker outcomes and lane revisions are then committed transactionally through
the single-writer store. Forking leaves the parent running. Database telemetry
and in-memory/file checkpoints have explicit retention limits.

The integration gate starts two concurrent lanes, patches one, forks the
other, reallocates all three, restarts one, and stops one. It also verifies
that candidate progress continues during a simulated Director inference
window. The measured focused gate completed in 0.34 seconds at 146% aggregate
CPU on this host. See `docs/reports/M6_CONCURRENT_LANES.md`.

This is not M6 completion. Event-triggered orchestration, candidate/M4
brokering, crash-resume campaign recovery, dashboard/API work, authenticated
live Director turns, the live intervention campaign, and the two-hour soak
remain pending.

### M6.4 event-driven scientific loop — offline milestone complete

The coordinator now coalesces bounded triggers, publishes hashed research
snapshot v3 artifacts, invokes a durable decision provider asynchronously, and
continues pumping lane telemetry and actions while inference is pending.
Critical verifier/fault/resource triggers bypass debounce; ordinary triggers
respect AI-selected reviewed intervals, candidate deltas, and event types.

Snapshots include current lane parameters and versions, telemetry slopes,
resources, verifier authority, recent action expectations/outcomes, current
hypotheses, and an exact evidence allowlist. Checkpoints admitted by a
committed snapshot are pinned for delayed actions. A bounded effect evaluator
persists pre/post windows, score/diversity/throughput/operator-yield changes,
and expectation results for the next Director turn.

The offline three-turn integration uses a deterministic durable provider: it
starts two lanes, delays the intervention turn while both keep searching,
patches and forks, measures the patch, then confirms that the next snapshot
contains the observed effect before reallocating resources. The focused gate
completed in 0.49 seconds at 137% aggregate CPU; the full suite passes 62
tests. See `docs/reports/M6_EVENT_DRIVEN_LOOP.md`.

Production still requires the app-server authentication gate and one live
campaign demonstrating the same loop. M4 brokering and the later recovery,
operator, dashboard, replay, and soak milestones remain pending.

### M6.5 retained candidates and M4 broker — offline milestone complete

Improvement events can now retain a bounded, hashed campaign candidate outside
the model prompt. Snapshots expose only candidate IDs and structural/score
summaries; graph bodies and paths are never model-controlled. Candidate
promotion and verification scheduling create a bounded, priority-ordered M4
queue.

The broker runs the existing bounded Python reference verifier and independent
C++17 verifier in a dedicated process, re-reads and validates the persisted
two-path manifest, and maps timeout/memory/tool failures to non-terminal
unknown states. Only a complete `COUNTEREXAMPLE_VERIFIED` manifest from both
expected implementations can quiesce lanes and atomically create the campaign
success terminal event. Director text, heuristic score, one verifier, malformed
output, or timeout cannot do so.

Reviewed deterministic diagnostics and explicit review-trigger actions are
also implemented, so all ten typed action variants have bounded executors.
The real M4 focused gate rejects K4 as `INVALID_CANDIDATE`, preserves both
verifier reports, and proves the campaign remains running with zero terminal
events. The full suite passes 65 tests. See
`docs/reports/M6_M4_BROKER.md`.

A positive certified terminal path will be demonstrated later with the
required deliberately false/hidden-witness control target, never by claiming a
result for the open research target.

### M6.6 recovery, replay, and export — offline milestone complete

Campaign recovery now checks SQLite integrity, marks interrupted app-server
turns/sessions, requeues interrupted M4 jobs, verifies checkpoint path and
content hashes, restores exact lane graph/RNG/tabu/counters/high-water, bumps
process generation, and redispatches only accepted actions without outcomes.
It returns the persisted Director thread ID for production `thread/resume`.

The worker durability boundary was tightened to emit a post-batch checkpoint
before its matching telemetry window, preventing SQLite high-water from
advancing beyond durable RNG state. The restart gate proves that the first
recovered checkpoint has the same ID, SHA, and high-water and that subsequent
search resumes from there.

Decision replay can now create durable commit-compatible turns. Scientific
replay deterministically reproduces bounded micro-batches from a checkpoint.
Artifact audit verifies snapshot and response hashes. Reproducibility export
uses SQLite Online Backup API, checks the snapshot database, applies file/byte
limits, uses deterministic ZIP metadata, and excludes authentication/private
homes. The full suite passes 69 tests. See
`docs/reports/M6_RECOVERY_REPLAY_EXPORT.md`.

The authenticated process-kill proof must still resume the actual persisted
app-server thread and is intentionally pending the explicit auth gate.

### M6.7 operator campaign and dashboard — offline milestone complete

The production foreground supervisor now assembles the persistent app-server
provider, event-driven orchestrator, bounded concurrent lane manager, retained
candidate archive, scientific diagnostics, and M4 verification broker around
one durable campaign. A nonblocking workspace lock prevents a second campaign
coordinator. Deadline, emergency pause/resume/stop, and M4-success states are
checked outside the Director turn task, so operational controls remain
responsive while inference is running.

The normal CLI and HTTP start contracts accept exactly one operator choice:
`--time-limit` or `--until-success`. The installed Erdős–Gyárfás target is
read-only; normal inputs expose no order, algorithm, worker, seed, mutation,
lane-allocation, or Director-cadence controls. The old parameterized `run`
command remains available as an explicitly legacy engine interface.

The standard-library dashboard now reports the persistent Director session and
turns, usage and latency, assessment and hypotheses, typed decisions and
measured effects, lane parameters and telemetry, revision history, verifier
queue, stop contract, resources, and fault state. Campaign exports still use
the SQLite Online Backup path and omit credentials.

The focused operator/API tests, full 74-test suite, and all five repository
gates pass. See `docs/reports/M6_OPERATOR_INTERFACE.md`. This remains an
offline milestone:
authenticated production turns, the hidden-witness live acceptance,
multi-controller study, outage hardening, and the two-hour Active Director
soak remain pending.

### M6.8 control target and provider resilience — offline milestone complete

A deliberately false, control-only target is now registered separately from
the Erdős–Gyárfás profile. Its statement is restricted to connected cubic
graphs on ten vertices and its finite witness is never included in the
Director prompt. The existing Python DFS and C++17 bitset verifier both check
the target-specific forbidden length; only their complete agreement through
the M4 broker can latch campaign success. Initial lane checkpoints can enter
the bounded candidate archive, closing the case where a seed is already a
counterexample.

Production provider failure now causes bounded app-server restart attempts and
`thread/resume` on the same persisted thread while lane telemetry and the M4
queue continue to be pumped. Current AI policies are never replaced by a
deterministic controller. If an active lane's AI-issued lease expires during
the outage, recovery aborts and the campaign enters `paused_fault`.

Long sessions roll over after bounded turn/token thresholds into a new
persisted thread with a hashed durable continuity brief and parent-thread
lineage. Raw app-server token usage is preserved alongside normalized
per-turn categories. Wire diagnostics are drained per turn and retained at a
fixed maximum of 64 files rather than repeatedly copying cumulative logs.

The focused control, recovery, rollover, and M4 gates pass; the full suite now
has 81 passing tests. See `docs/reports/M6_HARDENING_CONTROL.md`. The control
target has not yet been run with authenticated AI, so the live active-control
acceptance, equal-budget comparison, and two-hour soak remain pending.

### M6.9 equal-budget control harness — offline milestone complete

The executable multi-seed harness now compares static deterministic, seeded
random, serial-AI compatibility, and production Active app-server controllers
through the same durable campaign and M4 boundaries. Every trial has the same
wall, lane, verifier, Director-turn, and action-schema caps. The serial arm is
the documented compatibility construction required by the baseline
discrepancy: it pauses all lanes while the same app-server Director reasons
and is never a production fallback.

The normal campaign UI remains free of scientific tuning. The harness records
M4 success/time, best-score time area, efficiency, structure/finalist yield,
action effects/regret, stale actions, and provider usage, and it emits no
superiority claim. A real-lane static control reached the hidden witness
through M4, and the full suite now has 84 passing tests; the four-controller
authenticated multi-seed run still requires the explicit auth gate. See
`docs/reports/M6_CONTROL_STUDY_HARNESS.md`.

## M0 — complete

- installable standard `src/` package and CLI entry point;
- layered TOML configuration;
- `doctor`, `init`, `serve`, `verify`, and smoke commands;
- versioned SQLite schema in WAL mode, without an ORM;
- atomic, directory-synced state snapshots and bounded JSONL event rotation;
- required workspace artifact directories.

Evidence: focused unit tests plus `make doctor`, `make test`, `make check`, and
`make dashboard-smoke`.

## M1 — complete

- immutable integer-bitset graph representation through at least 128 vertices;
- invariant checks, edge iteration, degrees, connectivity, graph6 round trip,
  and stable non-canonical hash;
- exact DFS cycle witness detector;
- independent subset-DP detector with agreement tests on deterministic small
  random graphs;
- Erdős–Gyárfás structural validation and witness-returning exact result.

## M2 — implemented

- bounded multiprocessing coordinator with master-only SQLite writes;
- simulated annealing and iterated local search with deterministic seeds;
- cubic swaps, minimal-structure mixed-degree seeds, and unrestricted
  add/remove/swap moves;
- lexicographic structural, witness, weighted, novelty, and simplicity score;
- bounded top archive, improvement-only persistence, worker telemetry and
  recycling;
- a deterministic per-length DFS-node budget for the explicitly incomplete
  hot-loop scorer;
- hashed checkpoints, same-run resume, and file-based pause/resume/stop;
- one-coordinator workspace locking and bounded SQLite/event-log retention;
- finalist submission to both exact verifier paths.

The production two-hour, 12-worker soak exercised pause/resume, post-resume
progress, 180 controlled worker restarts, bounded queues, SQLite growth, and
RSS plateau. It completed with zero worker failures and all gates passing.

## M3 — implemented and benchmark-gated

- one C++17 integer-bitset helper with `FOUND`, `ABSENT`, `TIMEOUT`, and
  `ERROR` JSON results and cycle witnesses;
- subprocess process-group, output, and wall limits;
- deterministic cross-checks against the Python oracle;
- standalone two-verifier certificate manifest.

The smoke profile shows process startup dominates easy early-witness cases.
The C++ helper is therefore used for independent finalist verification, not
silently inserted into the heuristic loop.

## M4 — implemented as an optional path

- edge-variable CNF and minimum-degree cardinality clauses;
- lazy connectedness cuts and witness-backed forbidden-cycle clauses;
- preserved final CNF, learned JSONL, metadata, hashes, and optional proof;
- tiny deterministic DPLL/CEGAR ground truth at `n=4`;
- optional nauty overlap adapter;
- conservative timeout and unchecked-UNSAT semantics.

PySAT 1.9.dev7 with the `cadical195` backend was exercised on Python 3.12 at
`n=4`, including proof preservation, and with a forced timeout at `n=8`.
The UNSAT proof remains deliberately unchecked and therefore unclaimed.
nauty is not installed on the host, but Debian Bookworm's `nauty-geng`
enumeration was run at `n=4`: it checked the sole connected minimum-degree-3
class, found zero counterexamples, and agreed with the built-in CEGAR ground
truth.

## M5 — complete

- standard-library threaded HTTP server and static HTML/JavaScript;
- overview, candidates, experiments, bounded logs, graph downloads, and
  deterministic SVGs;
- validated start form and POST pause/resume/stop;
- local binding by default and optional bearer protection;
- bearer protection for every API route when configured;
- path traversal, request size, response size, action, and numeric guards.

## M6 — implemented

- raw-sample microbenchmarks with p50/p90/p95/max and peak RSS;
- deterministic calibration at `n=20,24,28,32` for both baseline algorithms;
- adjacent-order factors, candidates/day ranges, 24-hour and 7-day forecasts;
- hardware metadata and explicit heavy-tail SAT warning;
- configurable soak runner that exercises pause/resume, recycling, RSS plateau,
  database growth, and bounded queues.

The corrected 15-minute calibration completed all 16 cases under Python 3.12
and bases forecasts only on the `n=32` frontier. The full two-hour soak passed
all duration, control, progress, recycling, queue, database, dashboard, and
RSS gates. Superseded calibrations, short smokes, and a failed 265-second soak
attempt remain preserved as labeled evidence.

## M7 — optional adapters complete

- bounded adapters and availability/version reporting for nauty/Traces, SAT
  Modulo Symmetries, and Glasgow;
- nauty canonical-label path with a clearly marked non-authoritative fallback;
- `tools.lock.json` refuses to pretend absent tools have pinned commits.

Installed external tools must receive exact commits and overlap tests before
their lock entries are enabled.

## Completion pilot

The documented `n=8` integration pilot in `docs/20_PILOT_RUN.md` was started
from the HTTP dashboard, observed in Chromium, paused with a stable candidate
counter, resumed with renewed progress, stopped cleanly, and independently
verified by both exact paths. As expected at this validation order, both
verifiers found the same forbidden 4-cycle and rejected the candidate.

Engineering completion is not a mathematical result. No counterexample or
exhaustive nonexistence claim has been made.
