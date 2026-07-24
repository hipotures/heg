# Search Throughput and Mutation Ancestry

Date: **2026-07-24**

Baseline commit:
**93f1f4365022ef8644e1c7dde10a1d1ccee4914e**

This was a deterministic replay-only investigation. It made zero model
calls, did not copy `auth.json`, did not start `codex app-server`, and did not
start a research campaign.

## Reproduced batch

The production one-batch path was run with the exact scientific configuration
selected in the authenticated experiment:

- `iterated_local_search_tabu`;
- `connected_cubic`, order 20;
- seed `24072026`;
- 10,000 evaluations and `witness_cap=10000`;
- `tabu_tenure=48`, `perturbation_interval=200`;
- `restart_threshold=1500`, `promotion_penalty=10`.

The replay reproduced all deterministic scientific results:

- 18 global-record improvements;
- initial score `192/860`, best score `3/48`, final score `149/664`;
- best reached at evaluation 921;
- 1,063 accepted mutations, 174 duplicates, and 10,000 legal mutations;
- the same best graph and score with instrumentation enabled or disabled;
- exact reference result `REJECTED` because a forbidden 4-cycle remains;
- SQLite `PRAGMA integrity_check`: `ok`.

The measured instrumented run completed in 22.0685 seconds at 453.14
candidates/second. The previously preserved authenticated run completed in
20.4477 seconds at 489.05 candidates/second; host load changed wall time but
not any deterministic search result.

## Where time is spent

The counters are non-overlapping within the search loop. Telemetry, SQLite,
and exact verification are measured outside that loop.

| Stage | Seconds | Search-loop share |
| --- | ---: | ---: |
| Witness counting | 20.812444 | 94.309% |
| Duplicate detection | 0.661999 | 3.000% |
| Mutation generation | 0.300450 | 1.361% |
| Ancestry construction | 0.075480 | 0.342% |
| Score calculation | 0.055823 | 0.253% |
| Graph validation | 0.049999 | 0.227% |
| Tabu bookkeeping | 0.038979 | 0.177% |
| Unattributed loop overhead | 0.073287 | 0.332% |
| Telemetry construction | 0.001093 | 0.005% |
| SQLite persistence | 0.001245 | 0.006% |
| Exact final verification | 0.000051 | <0.001% |

The dominant cost is therefore the bounded cycle-witness enumeration, not
SQLite, telemetry, exact final verification, or tabu bookkeeping.

Three paired 2,000-evaluation trials produced median throughput of 491.15/s
with instrumentation and 489.11/s without it. The apparent 0.42% advantage
for instrumentation is measurement noise, not a speedup. The trials establish
no measurable aggregate regression at this sample size; the directly timed
ancestry work itself used 0.342% of the full reproduced loop.

## Explanation of the 16.8x difference

The original numbers compared different workloads:

- Phase A: simulated annealing, order 10, `witness_cap=16`, 300 evaluations;
- authenticated batch: ILS-tabu, order 20, `witness_cap=10000`, 10,000
  evaluations.

The preserved rates, 8,202.42/s and 489.05/s, differ by 16.77x. A longer
controlled replay on the current host measured 7,587.62/s for the Phase-A
workload shape and 453.14/s for the reproduced batch, again 16.74x.

The controlled comparisons separate the causes:

| Control | Evaluations | Throughput |
| --- | ---: | ---: |
| SA, order 10, cap 16 | 10,000 | 7,587.62/s |
| ILS-tabu, order 10, cap 16 | 10,000 | 6,777.81/s |
| ILS-tabu, order 20, cap 16 | 10,000 | 1,109.37/s |
| SA, order 20, cap 10,000 | 2,000 | 494.16/s |
| ILS-tabu, order 20, cap 10,000 | 10,000 | 452.68/s |

At the same small workload, SA was only 1.12x faster than ILS-tabu. At order
20 and cap 10,000 it was only 1.09x faster. Reducing only the ILS witness cap
from 10,000 to 16 increased throughput 2.45x. Most of the remaining difference
comes from enumerating cycles on twice as many vertices, with a much larger
witness bound, rather than from the choice of search algorithm.

SQLite persistence took 1.25 ms, telemetry construction 1.09 ms, and exact
verification 0.05 ms. They cannot explain a seconds-scale or 16.8x gap.

## Exact 18 record mutations

Every row is an accepted `two_edge_switch` and a global record. `Score` is
`witness total/weighted penalty`; witness columns are counts for lengths
`4/8/16`. Parent IDs can refer to accepted non-record intermediates, which are
present in the bounded accepted-ancestry tail.

| Eval | Parent candidate | Record candidate | Vertices | Removed | Added | Score | Witnesses 4/8/16 |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | `candidate-10bce11fa2a2b6881b262837` | `candidate-7b1622e428977c4292b140cb` | 1,3,4,19 | 1-19 3-4 | 1-4 3-19 | 192/860 → 181/820 | 1/20/171 → 1/21/159 |
| 3 | `candidate-7b1622e428977c4292b140cb` | `candidate-61c6f111f59280f347a3101b` | 0,5,6,13 | 0-13 5-6 | 0-5 6-13 | 181/820 → 144/684 | 1/21/159 → 3/18/123 |
| 5 | `candidate-61c6f111f59280f347a3101b` | `candidate-265edeb204d26bc847f3e67e` | 9,10,14,15 | 9-10 14-15 | 9-15 10-14 | 144/684 → 127/596 | 3/18/123 → 4/10/113 |
| 6 | `candidate-265edeb204d26bc847f3e67e` | `candidate-915408082bd124ca1300460c` | 1,4,8,15 | 1-4 8-15 | 1-8 4-15 | 127/596 → 121/584 | 4/10/113 → 3/16/102 |
| 9 | `candidate-915408082bd124ca1300460c` | `candidate-9f59bbe02f156cf31cec38f7` | 4,7,10,16 | 4-10 7-16 | 4-7 10-16 | 121/584 → 119/564 | 3/16/102 → 3/13/103 |
| 10 | `candidate-9f59bbe02f156cf31cec38f7` | `candidate-5f56c40bd698ff6aa0244616` | 0,5,6,7 | 0-5 6-7 | 0-6 5-7 | 119/564 → 107/500 | 3/13/103 → 3/9/95 |
| 20 | `candidate-5f56c40bd698ff6aa0244616` | `candidate-96c8b2ad637101b480123d77` | 0,15,16,19 | 0-19 15-16 | 0-15 16-19 | 107/500 → 107/496 | 3/9/95 → 4/5/98 |
| 22 | `candidate-96c8b2ad637101b480123d77` | `candidate-5ca97522918d63949bfe88b3` | 0,3,6,19 | 0-6 3-19 | 0-3 6-19 | 107/496 → 59/344 | 4/5/98 → 5/12/42 |
| 26 | `candidate-5ca97522918d63949bfe88b3` | `candidate-c1fda2e19fc9db7a5db58d17` | 0,3,5,17 | 0-3 5-17 | 0-5 3-17 | 59/344 → 15/160 | 5/12/42 → 5/10/0 |
| 36 | `candidate-45dd71bc7853b011a95a439d` | `candidate-c08d67f1ee1e43c05ebaa0ff` | 2,3,12,19 | 2-3 12-19 | 2-12 3-19 | 15/160 → 13/160 | 5/10/0 → 7/6/0 |
| 44 | `candidate-5120bf0939a48de6d61d72b6` | `candidate-dbdc93275f0aca902c27ba28` | 2,9,13,14 | 2-9 13-14 | 2-13 9-14 | 13/160 → 11/136 | 7/6/0 → 6/5/0 |
| 50 | `candidate-b7189f4330aca5df0400c617` | `candidate-083159ef4284285b7cd07414` | 6,12,13,14 | 6-14 12-13 | 6-12 13-14 | 11/136 → 7/88 | 6/5/0 → 4/3/0 |
| 70 | `candidate-67e086fc7b2b1c37d7e1ce84` | `candidate-eb9b7113d445a1ba53c0719c` | 10,11,12,13 | 10-13 11-12 | 10-12 11-13 | 7/88 → 6/88 | 4/3/0 → 5/1/0 |
| 142 | `candidate-165dc4572c8ce7442a449c1a` | `candidate-2973673b599ecce712b1554a` | 4,10,14,15 | 4-15 10-14 | 4-10 14-15 | 6/88 → 6/72 | 5/1/0 → 3/3/0 |
| 266 | `candidate-658e21875c9e5a7cd4cb8fec` | `candidate-63dd75a6133a0bf41c0d8b73` | 1,7,10,17 | 1-7 10-17 | 1-10 7-17 | 7/112 → 5/80 | 7/0/0 → 5/0/0 |
| 387 | `candidate-8a34ae46daf6619f9cd66ec3` | `candidate-d6a89210d5710df7b9de5a4b` | 0,2,7,17 | 0-17 2-7 | 0-2 7-17 | 5/80 → 5/72 | 5/0/0 → 4/1/0 |
| 705 | `candidate-d32cb1a7c9a5da79c47430b0` | `candidate-9347670b03ec1b49a3aa41c8` | 1,4,6,8 | 1-8 4-6 | 1-6 4-8 | 6/96 → 4/64 | 6/0/0 → 4/0/0 |
| 921 | `candidate-167160863cdd572fa787476b` | `candidate-3c9e8a20d19afa0140b9f6e4` | 5,10,13,16 | 5-10 13-16 | 5-16 10-13 | 5/80 → 3/48 | 5/0/0 → 3/0/0 |

All useful improvements therefore came from the only connected-cubic mutation
operator currently implemented: `two_edge_switch`. The data does not compare
multiple mutation operators; it demonstrates that this operator produced all
18 records.

## Boundedness and persistence

The engine records:

- every global-record transition within a bounded batch;
- no rejected non-record candidate;
- only the last 64 accepted transitions for the current candidate;
- only the last 64 accepted ancestors leading to the final best candidate.

These tails and candidate IDs are checkpointed, so a resumed or forked lane
preserves parent/child correlation. Metric windows persist the global records,
final-best tail, operator totals, timing counters, and a measured SQLite
persistence duration. The reviewed `mutation_ancestry` diagnostic reads this
durable telemetry and returns at most 64 recent records and 64 accepted
ancestors.

The larger checkpoint payload exposed an existing shutdown-queue race in the
one-second static control test. `LaneManager.shutdown` now drains and defers
complete worker events while processes exit, then makes those events available
to the single SQLite writer. This prevents killing a worker halfway through a
large checkpoint message and subsequently blocking on a partial queue frame.

For this 10,000-evaluation batch, the conservative estimate is 9,358,272
bytes: at most 10,128 live record slots, the largest observed compact record
of 462 bytes, and a factor of two for Python object/container overhead. The
actual counted slots were 146. Checkpoint ancestry is independently bounded
to two 64-record tails.

## Plateau assessment

The best score 3 appeared at evaluation 921. The following 9,079 evaluations
produced no new record despite 98.26% hash diversity. This is not duplicate
collapse. It is consistent with a barrier for the current one-step
two-edge-switch neighborhood plus mostly non-worsening tabu acceptance.

It is not proof of a strict local optimum: the engine did not exhaustively
enumerate every neighbor of the best graph, and it moved away from that graph
after later perturbations. In addition, `restart_threshold` is currently
effective only for simulated annealing; it does not restart ILS-tabu.
`promotion_penalty` is carried as campaign policy metadata and does not alter
the batch search loop. Those facts should be explicit in the next Director
snapshot so the model does not infer behavior that the engine does not have.

## Recommended next-turn input

The next Director turn should receive a compact telemetry payload containing:

```text
algorithm, graph_family, order, seed, witness_cap
evaluation_count, elapsed_seconds, throughput, peak_rss_bytes
initial/best/final witness counts and weighted penalties
best_evaluation=921, plateau_evaluations=9079
accepted=1063, duplicates=174, diversity=0.9826
operator=two_edge_switch, global_records=18
timing stage seconds and percentages
final_best_ancestry_length=64, ancestry_memory_estimate_bytes=9358272
verifier_status=REJECTED, forbidden_cycle_length=4
restart_threshold_effective_for_ils=false
promotion_penalty_effective_in_search_loop=false
```

For the next bounded exploration, the evidence supports offering the Director
both implemented strategies rather than claiming that bookkeeping caused the
slowdown. A concrete safe proposal is order 20, 10,000 evaluations, 120
seconds, and `witness_cap=64` for an exploration batch: an offline control
reached the same score 3 at evaluation 108 and ran at 694.61/s, 1.43x faster
than cap 10,000. The payload must flag that scores above the cap may be
truncated and that M4 exact verification remains authoritative.

Alternatively, simulated annealing with order 20, cap 10,000,
`temperature=1.0`, `cooling=0.995`, and `restart_threshold=1500` reached score
3 within its 2,000-evaluation control and was only 1.09x faster than ILS-tabu.
The Director can use these measured alternatives to choose a new lane or
fork. No second batch or model turn was executed during this investigation.

## Verification

- focused search/experiment/diagnostic/action/shutdown tests: 8 passed;
- full test suite: 99 passed;
- `make doctor`: passed;
- `make check`: passed;
- `make benchmark-smoke`: passed;
- `make dashboard-smoke`: passed;
- reproduced SQLite `PRAGMA integrity_check`: `ok`.

The untracked raw measurement report was
`/tmp/heg-search-diagnostics-20260724/search-diagnostics.json`, 140,103 bytes,
SHA-256
`111335b688a9aa3fda6c987ed2ac791b3a0deb01889b5383a90eec30d151cb25`.
It contains no credential, model, app-server, rollout, or normal Codex-home
data.
