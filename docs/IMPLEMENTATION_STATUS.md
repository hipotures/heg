# Implementation Status

Last implementation audit: **2026-07-24**.

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
