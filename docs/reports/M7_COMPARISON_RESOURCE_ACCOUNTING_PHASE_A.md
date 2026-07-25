# M7 Comparison Resource Accounting — Phase A

Date: 2026-07-25
Base HEAD: `492bc5f1f8d24d840dde65f7a3034e5ae8429357`
Production UI fix in history:
`124d581ede6f31ab74392699af42e03cc0eea419`
Result: **deterministic repair complete; no model or credential access**

## Outcome

The comparison worker no longer treats its complete private execution tree as
one artifact directory. Schema v12, plan schema 2.1, the worker, API, and UI
now distinguish:

| Category | Ownership and enforcement |
|---|---|
| `preserved_artifacts` | Immutable safe audit material; logical apparent-byte quota and per-file cap |
| `runtime_scratch` | Private homes, SQLite/WAL/SHM, sessions, rollouts, work and temporary files; independent apparent-byte quota and per-file cap |
| `credential_material` | Credential metadata only; contents never opened by accounting and never published |
| `logs` | Live stdout, stderr, wire and worker logs with independent bounds and truncation provenance |

New comparison defaults are:

| Limit | Default |
|---|---:|
| Preserved artifacts | 67,108,864 B (64 MiB) |
| Runtime scratch | 536,870,912 B (512 MiB) |
| One preserved file | 33,554,432 B (32 MiB) |
| One runtime file | 268,435,456 B (256 MiB) |
| Wire log | 8,388,608 B |
| Stderr | 262,144 B |
| Stdout/JSONL | 1,048,576 B |

All quotas and worker wall time are part of the prepared plan fingerprint. The
deprecated `maximum_artifact_directory_bytes` input maps only to
`max_preserved_artifact_bytes`; it never becomes the scratch quota. Existing
schema-2.0 plans remain byte-for-byte reproducible for audit but are refused
by the worker if someone attempts a new execution.

## Preserved historical failure

The terminal suite
`comparison-4407a28f8e7c47b89a7226045b61b1b4` was not resumed or modified:

- suite status: `failed`;
- consumed inference starts: 1;
- Luna high: `completed`, valid, measurement-only, unexecuted;
- Luna xhigh: persisted status `planned`, no actual order, never started;
- active worker leases: 0;
- new resource sample rows for this suite: 0;
- stored and recomputed plan fingerprint:
  `89e09e8f82428e86f2a75ae24ff51f7187536c22c2ad023152dcb80b60512886`.

The UI derives the safe display label `Blocked / Not Started` for the planned
xhigh arm because the suite is terminal failed with unused planned starts.
This does not alter the historical database row.

The previous runtime report and retained safe artifacts still have their
original SHA-256 values:

| Artifact | SHA-256 |
|---|---|
| Runtime Markdown report | `13101b1b8c1d9454fd827b7c748eb41806f0e6c8d1d4f85b189c9de68ad36ad1` |
| Runtime JSON report | `e058596283801f742762aca158b8c5b2470f4134c17ede4a0097ffb7b017eb76` |
| Plan verification | `a1697bb980cec34cadd08b68b56c3cf014311b2aff6dc6e5b6eba3e0fae9273c` |
| Request | `7c05e9745f2488e27a2a2c814a1c987b28eb75af541caba0e567f4a2e69c10c4` |
| DirectorStateV2 | `ae72cd0e1067fd90c2027e6ae8f9437ee71586551d7d64ca97d0fb1734938d53` |
| Response | `b3b247d7778beb4b9d83c056c90165895ce4c60f569c6f11229149826c1578b4` |
| Wire log | `94b8291924da7e888af551e7b1cfa61f71082103d8cc2ec171aa753e25064db5` |

No preserved file was altered. `planning/` was left untouched.

## Terminal-tree audit

The reviewed accounting function inspected only filesystem metadata with
`lstat`. It did not open credential contents. Public values exclude credential
metadata.

| Category | Apparent bytes | Allocated bytes | Files |
|---|---:|---:|---:|
| Preserved artifacts | 490,240 | 499,712 | 6 |
| Runtime scratch | 5,593,175 | 5,746,688 | 73 |
| Non-credential total | 6,083,415 | 6,246,400 | 79 |

The largest retained contributors were:

- runtime SQLite log WAL: 2,311,352 apparent bytes;
- runtime SQLite state WAL: 2,163,032 apparent bytes;
- model cache: 304,145 apparent bytes;
- preserved wire log: 424,804 apparent bytes;
- rollout JSONL: 64,992 apparent bytes.

The retained tree contains no symlinks, hard-link duplicates, or sparse files.
There is no retained temporary file above the former 64 MiB limit. Therefore
the exact historical transient peak and its individual path cannot be proven
from the post-shutdown tree.

The three top-level directories are `attempts` (574 apparent non-credential
bytes), `arms` (489,666 B), and `runtime-groups` (5,593,175 B excluding
credential metadata). The retained runtime group contains the private home,
SQLite home, one rollout, audit metadata, SQLite/WAL/SHM files, and no
remaining live stdout/stderr/wire temporary directory. The final preserved
arm contains request, DirectorStateV2, response, bounded wire log, and empty
stderr log. No unrelated workspace was traversed.

## Root-cause classification

The code defect is **proven**: the former `_check_artifact_limit` recursively
summed every regular file below the suite execution root, including private
Codex homes, runtime SQLite databases and WALs, rollouts, and temporary state.
It used `stat`, followed symlinks, did not deduplicate hard links, and stored
neither the peak nor its attribution.

A closest-shape deterministic reproduction places 6 MiB in preserved material
and 70 MiB in a runtime WAL. The old sum exceeds 64 MiB; the corrected
preserved total remains 6 MiB and the WAL is charged only to scratch. This
proves that counting the whole private runtime as artifacts can reproduce the
failure.

For the original authenticated attempt, transient runtime scratch—most
plausibly App Server SQLite/WAL growth—is **strongly supported**, not proven.
The exact transient contributor is unresolved because it was removed or
shrunk before the retained tree was inspected. No claim is made that a
specific WAL, rollout, sparse file, link, or temporary file was the historical
trigger.

## Accounting and persistence

`account_execution_root` is the single implementation used by telemetry and
enforcement. It:

- uses `lstat` and never traverses a symlink;
- explicitly reports an escaping link;
- deduplicates regular files by device/inode;
- records apparent and allocated bytes and sparse status;
- treats inaccessible entries and traversal entry/time limits as errors;
- assigns one stable ownership category;
- redacts the credential path label and never opens its contents;
- traverses only the validated suite execution root.

`comparison_resource_samples` retains only `latest`, `peak`,
`threshold_crossing`, and `terminal` rows per category/attempt. Rows preserve
current and peak apparent/allocated bytes, file count, bounded largest
files/directories, last growth, stage, decision, limit, interruption, cleanup,
and safe accounting errors.

At threshold crossing, the worker commits the crossing row and a bounded
private diagnostic before interruption or cleanup. It samples before auth
preparation, after private-home creation, App Server/thread/turn stages,
during wire growth and runtime polling, after final answer and usage, around
shutdown draining, and after cleanup.

Known preserved writes are preflighted before creation. Runtime-scratch
crossing interrupts an active turn when applicable and blocks later arms.
Log truncation stores a marker and the original observed byte count. A
completed valid arm remains completed if a later shutdown-stage infrastructure
failure occurs; the suite records the resource failure separately.

## Deterministic reproductions

The production worker state machine and fake stdio App Server cover:

| Case | Result |
|---|---|
| A. 80 MiB transient scratch, 512 MiB quota | Both arms complete; preserved quota unaffected; scratch removed on shutdown |
| B. Scratch quota exceeded | Exact contributor and peak persisted; interruption recorded; later arm blocked |
| C. Preserved quota exceeded | Large response rejected before write; preserved category recorded |
| D. Single-file cap | Pending response path and per-file limit recorded |
| E. Sparse file | Apparent and allocated bytes differ deterministically |
| F. Hard link | One inode counted once |
| G. Symlink escape | Target not followed; escape explicitly reported and worker rejects it |
| H. SQLite WAL growth | WAL charged to scratch; peak survives cleanup |
| I. Log growth | Bounded copy contains truncation marker and original observed bytes |
| J. Two valid arms | Both complete sequentially; lease released; no orphan |

An additional shutdown-growth case proves that a valid completed arm is not
retroactively invalidated when scratch crosses its quota during later
infrastructure shutdown.

## Schema and compatibility

The migration was first run on an SQLite Online Backup of the v11 production
workspace. It reached v12 with `integrity_check=ok` and zero
`foreign_key_check` rows. The production workspace was migrated only after the
old loopback dashboard closed.

Historical rows retain `resource_accounting_version=1`, original values, and
original fingerprints. New suites use version 2 and schema-2.1 plan payloads.
The failed suite received no resource sample or terminal-summary mutation.

## UI and HTTP verification

Playwright CDP verified the rendered New suite page and terminal historical
detail page on loopback without configuring an auth source:

- separate preserved, scratch, single-file, wire, stderr, stdout, and wall
  limits are visible;
- the historical plan is labelled as the legacy ambiguous v1 contract;
- high is completed and valid;
- xhigh is blocked/not started;
- the infrastructure category is legacy/ambiguous, peak and contributor are
  explicitly unavailable, and the comparison is incomplete;
- terminal Prepare, Authorize, Start, and Stop controls are disabled;
- no credential path or content is rendered.

Loopback HTTP tests passed. No Authorize or Start action was invoked.

## Verification

- focused accounting/quota/worker/client tests: 63 passed;
- complete safe suite, first run: 209 passed;
- complete safe suite, second run: 209 passed;
- complete safe suite after final hard-link/symlink worker cases: 211 passed;
- two-valid-arm fake soak: 10/10 passed;
- `make doctor`: passed;
- `make check`: passed;
- `make benchmark-smoke`: passed;
- `make dashboard-smoke`: passed;
- loopback HTTP tests: passed;
- SQLite v11→v12 Online Backup migration: passed;
- production SQLite `integrity_check`: `ok`;
- production SQLite foreign-key violations: 0;
- fake worker/App Server orphan processes: 0;
- real model inference starts in this phase: 0;
- real credential accesses in this phase: 0;
- authenticated App Server turns in this phase: 0;
- graph-search batches: 0;
- action dispatches: 0;
- model tool calls: 0.

```text
resource_categories_separated: true
preserved_artifact_quota_enforced: true
runtime_scratch_quota_enforced: true
log_quotas_enforced: true
symlink_escape_prevented: true
hardlink_deduplication: true
sparse_file_accounting: true
peak_resource_attribution_persisted: true
quota_crossing_diagnostic_persisted: true
completed_arm_preserved_on_suite_failure: true
two_fake_arms_complete: true
historical_failed_suite_unchanged: true
zero_model_inferences: true
zero_real_auth_access: true
zero_graph_search_batches: true
zero_action_dispatches: true
zero_tool_calls: true
http_tests_passed: true
sqlite_schema_version: 12
sqlite_integrity_check: ok
root_cause_classification: strongly_supported
ready_for_fresh_bounded_comparison: true
```
