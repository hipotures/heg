# M7 third real comparison runtime

Date: 2026-07-25

## Outcome

The exact authorized plan ran once and failed closed after the first arm.
`Luna high` reached authenticated inference and returned a structurally valid
response, but semantic validation rejected it because:

```text
$.hypothesis_updates[1].hypothesis_id: must reference an existing hypothesis
```

The suite is terminal `failed`. `Luna xhigh` was blocked and never started.
The comparison pair is incomplete and no blind rating is available.

The schema-v13 installed-wrapper compatibility objective did pass: all four
observed App Server wrapper symlinks were accepted as trusted, non-followed
runtime wrappers, byte accounting remained below its limits, the App Server
session closed, and the dashboard reaped the worker without requiring
dashboard shutdown.

## Authorized target

| Field | Value |
| --- | --- |
| Tested production commit | `76b6b33c15c8584003f780220b7080b320163de5` |
| Preparation report commit | `92a9b70c2723346dcdc023320a65910f014414bc` |
| Workspace | `workspace/model-comparisons-live` |
| Suite | `comparison-24c99e0539684b9ca488cdaba4f2486b` |
| Plan fingerprint | `062bc657ccd45f56808b741c042a9685f0f8b7e7135b5cc5f7af2ce4edef1790` |
| Fixture | `m6-executable-preserved-a4` |
| Fixture SHA-256 | `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77` |
| Plan schema / resource accounting | `2.1` / `2` |
| SQLite schema | `13` |

The fingerprint was recomputed immediately before authorization and matched
the authorized value. Authorization and Start were each invoked once through
the rendered dashboard. One credential file was copied into the isolated
private runtime for the reached arm. Credential contents, hashes, and private
paths are not included in this report or its screenshots.

## Arm lifecycle

| Effective order | Arm | Contract | Result |
| ---: | --- | --- | --- |
| 1 | Luna high | `gpt-5.6-luna / high / stateless_turns` | `semantic_invalid`; inference reached |
| 2 | Luna xhigh | `gpt-5.6-luna / xhigh / stateless_turns` | blocked / not started |

For the first arm, the effective model, effort, and context all matched the
authorized contract. It used a fresh thread. The App Server turn completed,
the session state became `closed`, and the second arm received no reservation.

The first arm had:

- final answer present: yes;
- authoritative usage present: yes;
- schema valid: yes;
- semantic valid: no;
- measurement only: yes;
- executed: no;
- inference-reaching retries: `0`;
- model tool calls: `0`.

The response selected `start_lane` with `simulated_annealing` as its primary
action and also returned two diagnostic requests and one review-trigger
request. None was dispatched.

## Authoritative usage and latency

| Metric | Luna high |
| --- | ---: |
| Input tokens | 5,826 |
| Cached input tokens | 0 |
| Cache-write input tokens | 0 |
| Output tokens | 3,273 |
| Reasoning output tokens | 2,010 |
| Server-reported total tokens | 9,099 |
| First item latency | 1.093833 s |
| Final answer latency | 61.480035 s |
| Total wall time | 62.110855 s |

Only `1 / 2` authorized inference starts was consumed. Total authoritative
server usage remained below the 40,000-token cap. No retry, replacement arm,
third inference, model change, effort change, or context change occurred.

## Zero-execution proof

Terminal database counts were:

| Record type | Count |
| --- | ---: |
| Research lanes | 0 |
| Director action batches | 0 |
| Director actions | 0 |
| Director action outcomes | 0 |
| Campaign candidates | 0 |

The comparison turn has `measurement_only=1`, `executed=0`, no decision batch,
and `tool_call_count=0`. Therefore the run performed zero graph-search
batches, zero returned-action dispatches, and zero model tool calls.

## Resource accounting and installed wrappers

No resource or filesystem-policy failure occurred.

| Category | Peak apparent | Peak allocated | Limit | Status |
| --- | ---: | ---: | ---: | --- |
| Runtime scratch | 5,196,165 B | 5,345,280 B | 536,870,912 B | within limit |
| Preserved artifacts | 460,076 B | 471,040 B | 67,108,864 B | within limit |
| Bounded logs category | 0 B | 0 B | independently bounded | within limit |

The largest runtime contributor was the safe relative label
`runtime-scratch/state_5.sqlite-wal` at 2,097,112 apparent bytes. Cleanup was
sampled after shutdown. Accounting reported no errors and no policy violation.

The real installed App Server produced exactly these reviewed observations:

- `app-server-tmp/arg0/apply_patch`
- `app-server-tmp/arg0/applypatch`
- `app-server-tmp/arg0/codex-execve-wrapper`
- `app-server-tmp/arg0/codex-linux-sandbox`

Each was classified `expected_runtime_wrapper`, target trust was
`trusted_executable`, target root class was `codex_installation`, policy status
was `allowed`, and `no_follow_confirmed=true`. No absolute target was persisted
or rendered.

## Lease, shutdown, and reaping

| Field | Value |
| --- | --- |
| Attempt | `comparison-attempt-411215ce54b7434e992e42a450661178` |
| Lease | `comparison-lease-94c70aa69bab420ca440190236219057` |
| Attempt status | `failed` |
| Worker return code | `1` |
| Process reap status | `reaped` |
| Lease released | yes |
| App Server session | `closed` |
| Cleanup status | `sampled_after_cleanup` |

After termination there was no comparison worker process, App Server process,
zombie worker, orphan worker, or stale active lease. The dashboard remained
responsive on its dedicated loopback listener.

## Integrity and historical preservation

- `PRAGMA integrity_check`: `ok`
- `PRAGMA foreign_key_check`: no rows
- `make doctor`: passed
- `make test`: passed, 227 tests
- `make check`: passed
- `make benchmark-smoke`: passed
- `make dashboard-smoke`: passed
- historical suite fingerprints and consumed-start counts remained unchanged;
- both historical suites remained terminal `failed`;
- committed historical runtime reports remained unchanged;
- the second historical worker-log SHA-256 remained
  `f3f0f62595f6df3b31b9461f48a119d1cee14bb0d621eb02312f253c6fe05022`;
- neither historical suite was resumed, reauthorized, or mutated.

## Safe evidence hashes

| Artifact | SHA-256 |
| --- | --- |
| Plan verification | `2785dba16252c1dfb3255c963966c044356a119bd482aa885effa3128cb8d0cc` |
| App Server request | `7c05e9745f2488e27a2a2c814a1c987b28eb75af541caba0e567f4a2e69c10c4` |
| App Server response | `743f8ecdb463e6221bd135e1a54b9a11a148e06d9c1c4958281d5e97e8c455b2` |
| Bounded wire log | `5746e40676e7fdffe0351a474a50b4f3fc29ca7ce93cde013524f398bf1af421` |
| Bounded worker log | `8165e111d28b08821c2446a6c91fc1f9e95467e6e6284e27e200f79093eb2ced` |
| Terminal suite screenshot | `a53d7d2f4b7a09c56720c074f675f29afeb98bb5b6d4374666d7328449261e5c` |
| Blind-unavailable screenshot | `e3234fed0fc8359078e33d987f68c6635e0b256dec414c7dbc2aaf833344a91c` |
| Terminal detail API response | `350a316343cb627db10b4fa96190588d6196fdbe0cdac3bc928fe428d8723af4` |
| Terminal progress API response | `cee0d8f779be77bbc466848e8055c7f86d0209fc159c3676dbcdf5686ed25788` |

Screenshots:

- [terminal suite](m7-third-real-comparison/terminal-suite.png)
- [blind review unavailable](m7-third-real-comparison/blind-unavailable.png)

## Final status

```text
installed_app_server_wrapper_smoke_passed: true
expected_app_server_wrappers_allowed: true
symlink_targets_not_followed: true
resource_limits_respected: true
worker_child_reaped: true
lease_released: true
graceful_app_server_shutdown: true
inference_starts_consumed: 1
second_arm_started: false
zero_inference_reaching_retries: true
zero_graph_search_batches: true
zero_action_dispatches: true
zero_model_tool_calls: true
safe_repository_gates_passed: true
ready_for_user_blind_rating: false
bounded_authenticated_worker_smoke: failed
```

`bounded_authenticated_worker_smoke` is `failed` because the authorized
two-arm comparison did not produce a valid pair. The installed-wrapper,
resource-accounting, fail-closed, shutdown, and reaping paths are nevertheless
proven by this real bounded run.
