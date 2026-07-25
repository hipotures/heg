# M7 First Real Comparison — Runtime

Date: 2026-07-25  
Tested commit: `124d581ede6f31ab74392699af42e03cc0eea419`  
Result: **fail-closed infrastructure failure after one valid arm**

## Exact authorized target

- Suite: `Luna high vs xhigh — A4 worker smoke`
- Suite ID: `comparison-4407a28f8e7c47b89a7226045b61b1b4`
- Plan fingerprint:
  `89e09e8f82428e86f2a75ae24ff51f7187536c22c2ad023152dcb80b60512886`
- Fixture: `m6-executable-preserved-a4`
- Fixture SHA-256:
  `2abb54b631942cd721dfd4bbaa6481135c73d818d35b9046c8f2f15d2c03af77`
- Authorized starts: at most 2
- Consumed starts: 1
- Timeout: 300 seconds per turn
- Total-token cap: 40,000
- Authoritative tokens consumed: 9,755

Before authorization the UI was reloaded and the canonical plan fingerprint,
workspace marker, arm contracts, effective order, limits, and empty worker
lease set were reverified. Playwright CDP clicked Authorize once and Start
once. The persisted authorization permits only `gpt-5.6-luna`, efforts
`high`/`xhigh`, `stateless_turns`, and two starts.

## Lifecycle result

| Order | Arm | Lifecycle | Inference |
|---:|---|---|---|
| 1 | Luna high | completed, valid | started once |
| 2 | Luna xhigh | remained planned | not started |

The high arm completed with a final answer, authoritative usage, and matching
effective contract:

```text
gpt-5.6-luna / high / stateless_turns
```

Immediately afterward the worker failed closed with:

```text
ComparisonWorkerError: comparison artifact directory limit exceeded
```

No retry, replacement arm, second inference, or third inference was created.
The suite is terminal `failed`. This means the requested high-versus-xhigh
comparison did not complete.

## Completed high-arm measurement

- Fresh thread: yes
- Final answer present: yes
- Usage present: yes
- Input tokens: 5,826
- Cached input tokens: 0
- Cache-write input tokens: 0
- Output tokens: 3,929
- Reasoning output tokens: 2,554
- Server-reported total: 9,755
- First-item latency: 1.1561922980472446 seconds
- Final-answer latency: 73.09819388855249 seconds
- Total wall time: 73.63951368629932 seconds
- Schema valid: yes
- Semantic valid: yes
- Validation issues: 0
- Tool calls: 0
- Retries reaching inference: 0
- Measurement only: yes
- Executed: no

Returned action types were `start_lane`, `promote_candidate`,
`schedule_verification`, `request_diagnostic`, and `set_review_trigger`.
The persisted selected action is `start_lane`. None was dispatched.

The App Server session reached `closed`; its turn terminal status is
`completed_valid`. The worker lease was released and its heartbeat stopped.
The control plane was restarted after audit to reap the completed worker
process; no worker or App Server orphan remains.

## Resource-limit failure

The authorized artifact-directory limit was 67,108,864 bytes. The terminal
worker check authoritatively recorded that the runtime exceeded this bound.
After graceful App Server shutdown, the retained non-auth tree occupies
6,083,415 apparent bytes.

The exact transient peak was not persisted, so the individual transient file
responsible cannot be reconstructed from the smaller final tree. No attempt
was made to raise the bound, mutate the terminal suite, or reuse the remaining
authorization capacity.

## Zero-execution and credential evidence

Final schema-v11 database counts:

| Record class | Count |
|---|---:|
| comparison inference reservations | 1 consumed |
| comparison turns | 1 |
| research lanes | 0 |
| Director action batches | 0 |
| Director actions | 0 |
| Director action outcomes | 0 |
| campaign candidates | 0 |

Every persisted comparison decision has `measurement_only=true` and
`executed=false`. There were zero search batches, action dispatches, model
tools, and inference-reaching retries.

Exactly one private auth file was created for the only started arm. No xhigh
runtime home was created. Fifteen text artifacts were scanned after completion;
none mentions the auth filename outside the auth file itself. Credentials,
auth hashes, bearer tokens, and private auth contents are absent from this
report, manifests, and UI.

## Durable artifact hashes

- Plan verification:
  `a1697bb980cec34cadd08b68b56c3cf014311b2aff6dc6e5b6eba3e0fae9273c`
- Request:
  `7c05e9745f2488e27a2a2c814a1c987b28eb75af541caba0e567f4a2e69c10c4`
- DirectorStateV2:
  `ae72cd0e1067fd90c2027e6ae8f9437ee71586551d7d64ca97d0fb1734938d53`
- Response:
  `b3b247d7778beb4b9d83c056c90165895ce4c60f569c6f11229149826c1578b4`
- Wire log:
  `94b8291924da7e888af551e7b1cfa61f71082103d8cc2ec171aa753e25064db5`
- Evidence registry:
  `2b15586edf1e512f9285af13f51d6b2897e154bba9c995404c9b92eaec88048c`

## Blind review

Playwright navigated through the rendered Blind comparison link. The page
shows `Not enough valid responses`, because only one completed valid answer is
available. It keeps model, effort, context, usage, latency, and cost absent
from the blind page. No A, Equal, B, or manual rating was selected.

Therefore the suite is not ready for user blind rating.

## UI follow-up and verification

The first terminal detail render exposed a presentation-only defect: the
structured applicable-action-space object was treated as an array. Commit
`124d581ede6f31ab74392699af42e03cc0eea419` fixes that shape handling without
changing runtime data. Playwright then verified the measured turn, token and
latency cards, zero-execution badges, released lease, and disabled terminal
controls.

- `make doctor`: passed
- `make test`: 194/194 passed
- `make check`: passed
- `make benchmark-smoke`: passed
- `make dashboard-smoke`: passed
- SQLite `integrity_check`: `ok`
- SQLite foreign-key violations: 0

Rendered evidence:

- [Terminal suite](m7-first-real-comparison-runtime/terminal-suite.png)
- [Blind comparison unavailable](m7-first-real-comparison-runtime/blind-unavailable.png)
- [Machine-readable runtime report](M7_FIRST_REAL_COMPARISON_RUNTIME.json)

```text
ready_for_user_blind_rating: false
bounded_authenticated_worker_smoke: failed
```
