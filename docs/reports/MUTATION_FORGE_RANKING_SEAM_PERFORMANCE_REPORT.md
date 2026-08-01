# Issue #16 — Mutation Forge ranking-seam performance

## Scope and pins

This report is the implementation and acceptance record for issue #16. The
authoritative issue body is the specification. The performance branch starts
from HEG `b701cabffab6d249a5cd647d1b339d2c653edcb9`; the read-only
Mutation Forge reference is `92915d614ee8ec414406b631246a5e9f85770aaf`.
The issue #15 frozen implementation, tag, report, and evidence remain
historical and are not rewritten.

The reviewed catalog remains `mutation_forge_stage4r_v1`, policy
`program-d5ad1c8203e0d9f25f03aabd`, with unchanged source, normalized-AST, and
behavior hashes. The frozen Stage 2B contract remains lengths 4–9, witness cap
32, cycle budget 20,000, distance budget 256, local-risk budget 2,048, k in
{2,3,4}, pool size 12, retry limit 96, matching limit 105, and the existing
selector weights. Activation remains explicit and disabled by default.

## Phase A — retained reproduction and profile

The retained issue #15 baseline/ranked reproduction was run once, serially,
before optimization. The preserved artifact is
`/tmp/issue16-retained-repro.json` (copied into the issue-16 evidence root at
finalization). It recorded worker p99 116,899 ns, zero worker failures/orphans,
order-14 ratio 0.0090269, and order-16 ratio 0.0118472.

The fixed-width profile (`stage7.heg.profile.v1`) was added before the root
cause was selected. Its categories are listed in
`MUTATION_FORGE_RANKING_SEAM_PROFILE.md`; it records aggregate phase
nanoseconds/counters only and never a per-proposal history.

## Root cause and exact optimizations

The retained profile showed repeated graph-invariant witness discovery and
distance work, matching-shape construction, per-proposal Python copying, and
one worker framing crossing for every proposal. The implementation therefore
adds only exact optimizations: graph-local feature caching with explicit
invalidation, cached perfect-matching shapes, copy-on-write local-risk
adjacency, trusted internal candidate construction with a defensive public
validation boundary, and one bounded worker batch request. No policy bytes,
AST/behavior identity, schema, feature limit, pool/retry/matching limit,
selector/RNG rule, scorer/M4 authority, fallback, or default activation was
changed. A missing host score witness length is completed from the bounded
host context, never mapped to scientific zero.

The batch extension is `stage2a.worker.batch.v1`; it is included in the exact
ranking checkpoint identity while the base worker protocol remains
`stage2a.worker.v1`.

## Preregistered fresh gate (Phase D)

After the optimized implementation/configuration/protocol/manifest is frozen,
tagged, pushed, and the required issue comment records
`Authoritative optimized HEG E2E results observed: false`, the coordinator
will run exactly one serial matrix:

| dimension | preregistered values |
|---|---|
| orders | 18, 24, 30 |
| seeds | 801, 802, 803, 804, 805 |
| repetitions | 3 paired repetitions |
| evaluations | 2,000 per arm/seed/repetition |
| arms | ranking parameter omitted; explicit `mutation_forge_stage4r_v1` |

The gate requires pooled median ratio ≥0.90, each order median ≥0.85, paired
seed median ≥0.75, worker policy p99 ≤5 ms, zero failures/orphans,
zero unauthorized calls/non-selected scorer calls, exact replay/checkpoint
state, and profile residual ≤2%. A phase regression above 20% is reported
unless the total gate passes.

## Terminal decision

The frozen serial matrix completed all 45 paired rows (3 orders × 5 seeds × 3
repetitions), with 2,000 evaluations in every arm and zero failures/orphans.
The observed ratios were:

| reduction | median ranked/baseline |
|---|---:|
| pooled | 0.03790645 |
| order 18 | 0.03606911 |
| order 24 | 0.03957182 |
| order 30 | 0.03792431 |
| paired seed 801 | 0.03897687 |
| paired seed 802 | 0.03792041 |
| paired seed 803 | 0.03880485 |
| paired seed 804 | 0.03764863 |
| paired seed 805 | 0.03734612 |

The pooled, per-order, and paired-seed thresholds therefore failed. The
100,000-call worker gate passed at p99 122,920 ns, with zero failures and
orphans. The profile gate passed: residual fraction was 0 across the fresh
rows; median cache hits/misses were 1,930/70 and the single-batch worker IPC
count was 2,000 per 2,000-evaluation ranked arm. Replay (2,048 records), the
30-case red-team suite, v17→v18 Online Backup migration, exact checkpoint /
Resume identity, default-disabled refusal, M4/scorer isolation, and all six
standard repository commands passed. The faithful performance gate is the
only failed gate, and it is a measured scientific result rather than an
infrastructure failure.

The authoritative terminal decision is **`NO_GO`**. The policy remains
explicitly opt-in and disabled by default. No merge is performed and no future
Stage 7R issue is created. Repository evidence is under
`runs/mutation-forge-ranking-seam-performance/issue-16`; the byte-manifested
external evidence root is
`/home/user/DEV/heg-evidence/mutation-forge-ranking-seam-performance-issue-16-final`
with a sorted SHA-256 `manifest.json`.
