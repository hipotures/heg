# Campaign Resume and Scientific Memory — Phase A

Date: 2026-07-26

Tested worktree base: `f1c21c0ac906cdaf732ad1ef0f280ad55a8fbe2c`

Branch: `m7-ui-review-phase-a`

SQLite schema: 15

## Outcome

Campaign continuity is implemented end to end without a real model or auth
access. One durable campaign now owns immutable execution attempts, cumulative
scientific state, candidate pins/snapshots, resume-safe checkpoints, and
versioned bounded scientific-memory snapshots. CLI, protected HTTP APIs, and
the rendered dashboard all operate on the same resume contract.

## Execution attempts and Resume

Every start/Resume records an immutable attempt ID/index, reason, code commit,
requested/effective resources, additional wall-time, starting memory
ID/SHA-256, verified checkpoint references, inherited/local counters,
provenance, repair acknowledgement, process ID, and terminal result.

Supported recovery covers operator pause/stop, deadline/budget exhaustion,
repaired infrastructure faults, interruption, and host restart. Live,
certified-success, and scientifically invalidated campaigns are refused.
Resume from `paused_fault` requires a repair acknowledgement and preserves the
original failed attempt.

Per-attempt changes cover CPU worker slots, active lanes, aggregate share,
lane/verifier memory, verifier concurrency, and queue depth. CPU workers are
explicitly application-level concurrency, not OS isolation. Target, target
definition, Director model/effort/context, and authenticated-versus-control
contract cannot change silently.

## Candidate lifetime and stale targets

Candidate-target actions validate against the current executable registry and
transactionally acquire a pin plus immutable graph snapshot. `ON DELETE
RESTRICT` and pruning filters protect referenced candidates. M4 consumes the
snapshot, not a later candidate-row lookup. The pin releases only when all
referencing actions/jobs are terminal.

An ID that becomes stale before acceptance is persisted with
`validation_status=stale_target`; no action executes. One fresh stateless
replan receives the stale ID and current valid registry. A valid replan
continues the campaign; a second stale/invalid replan ends it cleanly.
Infrastructure exceptions remain fail-closed.

## Scientific memory

The plan fingerprints deterministic memory policy:

- soft trigger: 24,576 canonical UTF-8 bytes;
- hard limit: 32,768 canonical UTF-8 bytes;
- periodic snapshot: every 5 valid scientific cycles;
- snapshots at pause, stop, budget/deadline, fault, Resume, and as required
  before inference.

Immutable snapshots store parent/version, source high-water marks/counts,
canonical JSON, byte size, token estimate, SHA-256, trigger, and timestamp.
Every Director turn and attempt records the snapshot used. Exact-verifier
facts and current executable IDs are non-droppable. Full raw SQLite/artifact
history is not deleted.

## 65+65 second production-state-machine demonstration

The real local search kernel and deterministic `continuity_demo` Director ran
in a disposable workspace:

- campaign: `campaign-aff6dd6bc0ab47868528c9dce87ce9c4`;
- attempt 1: `execution-attempt-51a857fac4f246deb1ab9253fe9d2a3d`,
  2 CPU slots / 2 lanes / 65 seconds;
- attempt 2: `execution-attempt-5023265dfd2a4b232a2f0c13`,
  16 CPU slots / 8 lanes / 65 seconds;
- cumulative evaluations: 69,995 → 140,918;
- attempt-local evaluations: 69,995 and 70,923;
- two checkpoint hashes were verified and reused;
- attempt 2 used terminal memory
  `scientific-memory-538ef9cc56b44941985990f3bfa7ae74`
  (`4cd961109ac899883755fbb67cc70f430518aabd6c9f280c2a42810a024d4a0c`);
- the hypothesis and four prior M4 `INVALID_CANDIDATE` outcomes survived;
- six terminal M4 outcomes were present after attempt 2;
- all 14 idempotency keys were unique;
- final memory v16 was 19,962 bytes, below the 32,768-byte hard limit;
- SQLite integrity was `ok`, foreign-key violations were zero;
- model inferences and auth accesses were zero.

The first long run exposed a deterministic test-adapter defect: an
advisory-only historical best candidate could be selected for verification.
The adapter now requires executable-target membership. A focused regression
test and the repeated 65+65 run prove the correction.

## Real campaign compatibility preview

Source campaign (read-only):
`campaign-b68ec445388e49b2be0b6fabf8ff6600`.

The deterministic preview, computed from the database rather than hardcoded,
reports:

- same campaign ID, state `paused_fault`, state version 25;
- proposed attempt index 2 and ID
  `execution-attempt-bc7969056a83960392937a78` for the documented preview
  inputs and tested base commit;
- reason `infrastructure_recovery`;
- 6 completed Director turns, 21 accepted/persisted actions, 6 lanes,
  109,937 evaluations, 2 retained candidates, 2 terminal verifier jobs, and
  51,340 server tokens;
- six hash-valid checkpoints;
- reusable legacy memory projection
  `legacy:snapshot-a2a273b939f34d5f83640ee7712f75bc`,
  SHA-256
  `8e5a6acb73c137cb455c4e3674a7a7951274192c52b619aa5a5ad8e9abaf3699`,
  6,619 bytes;
- current executable candidate IDs: none;
- historical action `verify-retained-candidate-01`, targeting the absent
  candidate, excluded from execution and scheduled to become terminal
  `stale_target` only on an authorized actual Resume;
- zero database writes, auth access, model inference, and search batches.

An SQLite Online Backup of the schema-v14 source migrated to schema 15 with
`integrity_check=ok` and zero foreign-key violations. The source campaign
remains schema 14 and its scientific rows are unchanged: state/version/fault,
record counts, maximum scientific timestamps, campaign plan/pointer hashes,
and all six checkpoint hashes match. The physical main-database file hash
changed while an independently existing port-8788 dashboard was attached to
the WAL database; this is not used as a logical scientific-state identity.
No campaign row, action, checkpoint, candidate, verifier result, or artifact
was rewritten by this work.

## HTTP and rendered UI

Protected Resume preview/start endpoints use the same CLI contract and do not
accept browser-supplied process commands. The dashboard shows:

- campaign ID separately from attempt IDs;
- attempts 1–3 and proposed attempt 4 in the UI fixture;
- cumulative 5,110 evaluations versus current-attempt 0;
- prior fault and repair acknowledgement;
- resource changes CPU 16→4, lanes 8→3, lane memory
  536,870,912→268,435,456, verifier concurrency 1→2;
- two verified checkpoint references and memory reuse;
- scientific-memory v7, 9,084 bytes / 2,271 estimated tokens.

Playwright CDP passed at 1440×1000 and 390×844 with no console failures and
only successful observed HTTP requests. It did not click Start.

- Desktop screenshot SHA-256:
  `f545929bfb5ccd7998436ab24c2d1857ee257f74e5c5bf5afb181518d691bca1`
- Mobile screenshot SHA-256:
  `822d11620f6dc8a036eb0b49e7d1953397a8af0cbe6eefdf8abbef43c636719d`

## Verification

- focused campaign continuity, stale-target, pin, migration, HTTP, and UI
  tests: pass;
- full safe suite: 255/255 pass, twice;
- `make doctor`: pass;
- `make test`: pass, twice;
- `make check`: pass;
- `make benchmark-smoke`: pass;
- `make dashboard-smoke`: pass;
- loopback HTTP tests: 8/8 pass;
- schema-v14→v15 Online Backup migration: pass;
- SQLite integrity/FK checks: `ok` / zero rows;
- 65+65 fake-Director real-kernel demo: pass;
- test dashboard stopped; no campaign/search/App Server test orphan remains.

The process table contains old `chromedriver` zombies owned by the unrelated
`/home/xai/DEV/ttracker` Selenium monitor. They predate this task, are not
children of sglab, and were not reaped or modified. The pre-existing real
campaign dashboard on port 8788 was also left running and untouched.

## Final fields

```text
campaign_execution_attempts_created: true
same_campaign_resume_supported: true
resume_after_pause_supported: true
resume_after_budget_exhaustion_supported: true
resume_after_repaired_fault_supported: true
resource_change_on_resume_supported: true
cpu_worker_limit_effective: true
cumulative_state_preserved: true
checkpoint_restore_supported: true
candidate_reference_lifetime_fixed: true
candidate_pinning_proven: true
stale_target_replan_supported: true
historical_stale_action_not_reexecuted: true
automatic_compaction_created: true
compaction_soft_threshold_bytes: 24576
compaction_hard_limit_bytes: 32768
compaction_interval_cycles: 5
deterministic_memory_snapshots: true
full_raw_history_preserved: true
director_state_bounded: true
short_two_attempt_demo_passed: true
resource_change_demo_passed: true
playwright_resume_ui_passed: true
real_campaign_resume_preview_created: true
source_real_campaign_unchanged: true
zero_real_model_inferences: true
zero_real_auth_access: true
sqlite_integrity_check: ok
ready_to_resume_real_campaign: true
```
