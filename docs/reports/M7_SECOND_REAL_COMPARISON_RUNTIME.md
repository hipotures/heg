# M7 second real comparison runtime

Date: 2026-07-25

Tested implementation commit:
`e9ebe39e9ec51cec1002f4677c77eb1900a5ba9a`

Preparation evidence commit: `418f5f7`

## Outcome

The freshly authorized comparison failed closed before any model inference:

- suite ID: `comparison-aaabfae5a010445e9d966ea50a0958a8`
- plan fingerprint:
  `a44e96f67628cb9afcacbc6c76b8f0e6e65696ba075a62c587d5f02b9b41c6d7`
- attempt ID:
  `comparison-attempt-23651fb3ec094bdda338c98a74f43581`
- terminal suite status: `failed`
- inference starts consumed: `0 / 2`
- authoritative server tokens: `0`
- completed arms: `0 / 2`
- ready for blind rating: no

The exact plan fingerprint was recomputed and matched immediately before
authorization. Authorization was bound to the expected model, efforts,
context mode, and two-start maximum. Playwright CDP clicked Authorize once and
Start once. No retry, replacement arm, third inference, or manual worker
command was used.

## Lifecycle

| Stage | Result |
|---|---|
| Plan verification | passed |
| Private runtime-home preparation | completed |
| App Server process start | completed |
| Resource sample after App Server start | failed closed |
| Thread start | not reached |
| Inference reservation | not reached |
| Model inference | not reached |
| Graceful App Server shutdown | completed |
| Worker lease release | completed |
| Later arm | blocked |

The retained plan-verification artifact records the same stored and
recomputed fingerprint, the exact two arm IDs, `measurement_only: true`, and
`execute_decisions: false`.

## Proven failure cause

This was not a byte-quota crossing.

At `after_app_server_start`, resource accounting measured:

| Category | Apparent bytes | Allocated bytes | Configured limit |
|---|---:|---:|---:|
| Runtime scratch | 2,274,115 | 2,420,736 | 536,870,912 |
| Preserved artifacts | 4,878 | 12,288 | 67,108,864 |

The largest regular scratch file was a state SQLite WAL at 1,404,952 apparent
bytes. Every regular file remained below its single-file limit.

The accounting sample also recorded four escaping symbolic links created in
the App Server's transient `arg0` directory:

- `apply_patch`
- `applypatch`
- `codex-execve-wrapper`
- `codex-linux-sandbox`

The shared accounting function correctly used `lstat` and did not follow
these links. The worker then treated the presence of any escaping symlink as
a `runtime_scratch` violation and attached the 512 MiB scratch quota to that
policy failure. Consequently, the terminal message claimed
`2,274,115 > 536,870,912`, which is numerically false.

The root cause is therefore proven: the v2 worker rejects normal transient
App Server executable-wrapper symlinks as if the aggregate scratch byte quota
had been exceeded. The symlinks disappeared during shutdown, while the
threshold sample retained their safe relative labels. The UI accurately
rendered the persisted fields but currently describes this accounting-policy
failure as a byte-quota crossing.

This suite is terminal and must not be resumed or reauthorized. Any future
run requires a code fix, deterministic fake-App-Server reproduction, a new
suite ID, a new fingerprint, and new explicit authorization.

## Arm results

| Effective order | Arm | Runtime result |
|---:|---|---|
| 1 | `gpt-5.6-luna / high / stateless_turns` | infrastructure failure before thread/inference |
| 2 | `gpt-5.6-luna / xhigh / stateless_turns` | blocked, not started |

No effective model, effort, context, final answer, token usage, latency,
schema validity, semantic validity, or selected action exists because no turn
was started.

## Fail-closed and zero-execution checks

- inference reservations: 0
- authenticated inference starts: 0
- retries reaching inference: 0
- graph-search batches: 0
- research lanes: 0
- returned-action dispatches: 0
- model tool calls: 0
- comparison turns: 0
- executed Director decisions: 0
- later arms blocked: yes
- active-turn interruption sent: no; no turn existed

The workspace still contains no research lane, action batch, action, outcome,
or candidate record. Credential material was copied only into the authorized
private runtime home; its contents, metadata, path, and hash are excluded from
this report and from rendered UI evidence.

## Shutdown and database checks

The worker released its lease one second after acquisition and shut down the
App Server before returning the terminal failure. The worker process was
initially visible as a defunct child retained by the dedicated dashboard
process. Stopping that controlled dashboard reaped it. Final checks found:

- no active worker lease;
- no worker or App Server process;
- no orphan or zombie process;
- no listener on port 8788;
- SQLite schema version 12;
- `PRAGMA integrity_check`: `ok`;
- `PRAGMA foreign_key_check`: no rows.

The transient zombie indicates a separate control-plane child-reaping issue,
although final cleanup is complete.

## Blind comparison

Playwright CDP opened the Blind comparison page. It displayed `Not enough
valid responses`; there were no A/Equal/B controls to use. No rating was
submitted.

## Safe artifacts

| Artifact | SHA-256 |
|---|---|
| Plan verification | `e4837ec5fb4d291389e0f37c2633bb3631cd258cf1bd447c772f50dff755acc2` |
| Resource diagnostic | `054c869579cb95e4a55b4b344749939c457f99e0df96e00d00a07db7289588ab` |
| Bounded worker log | `f3f0f62595f6df3b31b9461f48a119d1cee14bb0d621eb02312f253c6fe05022` |
| [Terminal suite screenshot](m7-second-real-comparison-runtime/terminal-suite.png) | `3ce624be4a73795783b2354256127cf889a1239e936d35743e768c6545a22cd0` |
| [Resource failure screenshot](m7-second-real-comparison-runtime/resource-failure.png) | `795946f5259b24b7bc56ca89ac8ac8a45ab2c4b7437981bb311010a30bfac59e` |
| [Blind unavailable screenshot](m7-second-real-comparison-runtime/blind-unavailable.png) | `e3234fed0fc8359078e33d987f68c6635e0b256dec414c7dbc2aaf833344a91c` |

The screenshots and public artifacts contain no bearer token, credential
content, credential hash, or private absolute runtime path.

## Final status

```text
ready_for_user_blind_rating: false
bounded_authenticated_worker_smoke: failed
model_inference_starts: 0
root_cause_classification: proven
actual_byte_quota_exceeded: false
fail_closed_behavior: proven
fresh_fix_required_before_another_comparison: true
```
