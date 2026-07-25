# M7 comparison symlink policy and child reaping — Phase A

Date: 2026-07-25

Tested base commit: `c18770483faf91153621cf5b6be209162ab19aa8`

Branch: `m7-ui-review-phase-a`

Workspace: `workspace/model-comparisons-live`

## Outcome

The worker now treats filesystem byte accounting and symlink policy as
independent results. The four reviewed transient App Server `arg0` wrappers
are accepted only at their exact private runtime location and only when the
target satisfies a server-owned trusted-installation contract. Accounting
uses `lstat`, never follows a symlink or charges target bytes, and persists
only bounded safe labels and trust classifications.

The dashboard now retains bounded `Popen` ownership for workers and polls only
those handles. Completed children are reaped without stopping the HTTP server,
the reaping result is persisted, and the live-process registration is removed.
A Linux zombie PID is not considered an active worker.

All deterministic policy, accounting, worker, migration, HTTP, and reaper
tests passed. The installed no-auth lifecycle smoke started, initialized,
sampled, shut down, and reaped the installed App Server without
`thread/start`, `turn/start`, credential access, or inference. That permitted
pre-thread phase created no wrapper symlinks, so direct classification of the
installed runtime's real wrappers could not be observed without crossing the
explicitly forbidden thread boundary. Therefore
`ready_for_fresh_bounded_comparison` remains `false`.

## Preserved authenticated failure evidence

Neither historical terminal suite was resumed, reauthorized, or mutated.

- `comparison-4407a28f8e7c47b89a7226045b61b1b4` remains terminal with its
  original fingerprint
  `89e09e8f82428e86f2a75ae24ff51f7187536c22c2ad023152dcb80b60512886`.
- `comparison-aaabfae5a010445e9d966ea50a0958a8` remains terminal failed with
  fingerprint
  `a44e96f67628cb9afcacbc6c76b8f0e6e65696ba075a62c587d5f02b9b41c6d7`.
- The second suite still has zero consumed inference starts. Luna high failed
  at `after_app_server_start`, before `thread/start`; Luna xhigh remains
  blocked/not started.
- Its twelve historical schema-v12 resource samples were not rewritten.
- Its stored diagnostic, plan-verification, worker-log, and runtime-report
  hashes remain unchanged:

  - plan verification:
    `e4837ec5fb4d291389e0f37c2633bb3631cd258cf1bd447c772f50dff755acc2`
  - threshold diagnostic:
    `054c869579cb95e4a55b4b344749939c457f99e0df96e00d00a07db7289588ab`
  - worker log:
    `f3f0f62595f6df3b31b9461f48a119d1cee14bb0d621eb02312f253c6fe05022`
  - runtime report Markdown:
    `32917d77148c74cce9b875d16d055f7bbea0b5b39190d2b5b766b9e626096505`
  - runtime report JSON:
    `631065c63041e0c68282e4ac375155dbccc60f7313d0319a35afffb3631eaba0`

The persisted evidence proves the authenticated failure was not a byte-quota
crossing: runtime scratch was 2,274,115 apparent bytes against a
536,870,912-byte limit. The historical v12 worker incorrectly converted the
four normal wrapper symlinks into a scratch-quota failure. This classification
is proven from the threshold diagnostic and terminal samples; no private
target path is needed or published.

## Corrected accounting and policy contract

Each sample now persists these independent outcomes:

- `byte_quota_status` and `byte_quota_exceeded`;
- `accounting_status`;
- `symlink_policy_status` and `policy_violation_code`;
- `failure_domain` and `failure_code`.

Failure domains distinguish aggregate byte quotas, single-file quotas, log
quotas, filesystem policy, accounting errors, process lifecycle, and App
Server protocol errors. A quota exception cannot be constructed unless the
measured current or peak value is numerically greater than its limit.

For every symlink, the traversal:

1. calls `lstat`;
2. reads only bounded link metadata with `readlink`;
3. never opens or recursively follows the target;
4. never charges target bytes;
5. rechecks link and target identity before accepting a trusted wrapper;
6. reports a deterministic race if type, device, or inode changed.

Symlink classifications are `internal_nonfollowed`,
`expected_runtime_wrapper`, `unexpected_external`, `broken`, and
`malformed_or_unreadable`.

The reviewed runtime location is represented publicly as
`app-server-tmp/arg0/<wrapper-name>`. The only accepted basenames are:

- `apply_patch`
- `applypatch`
- `codex-execve-wrapper`
- `codex-linux-sandbox`

The target root is derived from the server-owned launcher configuration, not
browser data, suite metadata, or model output. A trusted target must resolve
under that installation root, be a stable regular executable, be outside the
research workspace, and not be world-writable. Expected basenames in another
directory and expected paths with untrusted targets fail closed.

An unexpected escape now yields:

```text
failure_domain = filesystem_policy
failure_code = unexpected_external_symlink
```

It carries no byte limit or false `current_bytes > limit_bytes` statement.

## Enforcement and persistence

The production sample path now:

1. performs one bounded accounting traversal;
2. computes actual aggregate, single-file, and log inequalities;
3. evaluates the separately recorded filesystem observations;
4. persists both byte and policy results;
5. enforces the applicable domain.

Schema v13 adds nullable bounded summaries to suites, resource samples, and
execution attempts. The v12→v13 migration adds columns only and leaves
historical values null. Migration testing uses SQLite Online Backup and passes
both `integrity_check` and `foreign_key_check`.

## Dashboard child reaping

The dashboard keeps a bounded registry of worker `Popen` handles it created.
Its normal nonblocking server service loop calls `poll()` only on those owned
handles, which reaps exited children without a global `waitpid`. Terminal
attempt persistence remains the worker's responsibility and is independent of
the reaper. The dashboard then records the reaping time and return code and
removes the live registration.

Restart recovery uses persisted PID/lease inspection and treats `/proc` state
`Z` as not live. It never assumes ownership of an unrelated process.
Deterministic HTTP tests cover successful and failed worker exits, terminal
detail availability, duplicate-start prevention while actually active, and
continued dashboard responsiveness.

## Deterministic reproductions

The production worker state machine with the fake App Server verifies:

- all four exact wrappers classify as `expected_runtime_wrapper`;
- both comparison arms complete with wrappers present;
- an unexpected external symlink fails as filesystem policy and blocks the
  later arm;
- an allowlisted basename in the wrong directory is rejected;
- an allowlisted path with an untrusted target is rejected;
- a broken link has a deterministic explicit classification;
- link metadata replacement is detected without following the target;
- a genuine aggregate scratch crossing reports `byte_quota` with a true
  inequality;
- a genuine one-file crossing reports `single_file_quota`;
- successful and failed worker children are automatically reaped;
- the two-arm wrapper soak completed ten consecutive runs.

The complete safe suite passed twice with 227 tests per run. Focused policy,
accounting, worker, reaper, HTTP, and migration tests passed, as did
`make doctor`, `make test`, `make check`, `make benchmark-smoke`, and
`make dashboard-smoke`.

## Rendered UI verification

Playwright CDP rendered the unchanged historical second suite through the
real loopback dashboard. It visibly reports:

- `Filesystem policy violation`;
- `Normal App Server wrapper symlinks were incorrectly rejected`;
- `Actual Byte Quota Exceeded: No`;
- `2,274,115 B / 536,870,912 B`;
- safe label `app-server-tmp/arg0/apply_patch`;
- zero inference starts;
- Luna xhigh blocked;
- comparison incomplete.

The screenshot is
`docs/reports/m7-comparison-symlink-policy/historical-second-suite.png`
with SHA-256
`f8e5eecc6890cc24f410356d4231a3b97b9d944b761bcead88e8870ce1c8d413`.
It contains no credential path, bearer token, or private symlink target.

## Installed-runtime smoke and remaining uncertainty

The bounded installed-runtime smoke deliberately stops before
`thread/start`. It proved no credential access, no model inference, no turn,
graceful shutdown, return code zero, and automatic process reaping. The
installed build produced zero transient `arg0` wrapper symlinks during that
phase. Consequently the exact installed-wrapper classification remains
unobserved under the allowed boundary, even though the same production
accounting path and four exact names pass deterministic real-state-machine
tests.

A separate prerequisite protocol audit used an isolated synthetic home and
performed an unauthenticated ephemeral `thread/start`, but no `turn/start`.
That audit was not used as the requested installed-wrapper smoke and observed
no authenticated activity or model inference.

## Final status

```text
expected_app_server_wrappers_allowed: true
symlink_targets_not_followed: true
unexpected_external_symlinks_fail_closed: true
filesystem_policy_separate_from_byte_quota: true
false_numeric_quota_messages_prevented: true
trusted_target_contract_enforced: true
symlink_race_detected: true
worker_children_reaped: true
zombie_worker_prevented: true
two_fake_arms_complete_with_wrappers: true
installed_app_server_wrapper_smoke_passed: false
historical_suites_unchanged: true
zero_model_inferences: true
zero_real_auth_access: true
zero_graph_search_batches: true
zero_action_dispatches: true
zero_tool_calls: true
http_tests_passed: true
sqlite_schema_version: 13
sqlite_integrity_check: ok
ready_for_fresh_bounded_comparison: false
```
