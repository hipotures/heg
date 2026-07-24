# Implementation Status

Last implementation audit: **2026-07-24**.

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

### M6.1 app-server integration — in progress

The installed Codex 0.145.0 schemas have been generated and hashed, including
documented compatibility differences from the package examples. A direct
asynchronous stdio JSON-RPC client now implements private-home isolation,
dynamic skill disabling, persisted start/resume, structured turns, event
correlation, usage accounting, bounded diagnostics, unsupported-request
rejection, and process-group cleanup. Five focused tests and a real isolated
app-server initialization pass.

The authenticated live-turn, saved-rollout isolation, and process-restart
resume gates remain pending because the required explicit one-time auth import
has not been authorized. See `docs/reports/M6_APP_SERVER_PREFLIGHT.md`; no
credentials have been copied.

### M6.2 durable Director contracts — offline milestone complete

Schema v1 now migrates additively to schema v7 with campaign, app-server,
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
