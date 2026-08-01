# Issue #15 — Mutation Forge Stage 4R proposal-ranking seam

## Preregistration and pins

- HEG implementation base: `fd97451b0f3d87400d1d955a2c6b1b18303344ff`.
- Read-only Mutation Forge reference: `92915d614ee8ec414406b631246a5e9f85770aaf`.
- Catalog: `mutation_forge_stage4r_v1`.
- Policy: `program-d5ad1c8203e0d9f25f03aabd`.
- Source SHA-256: `e444562c1b308e3b23cb732be5f769ea1923ac1809501cea8571318c4aff0a7b`.
- Normalized AST SHA-256: `2243214df58c805e9a9343dc31ed082279e1c2ac31b21243bf889dbc9a19e165`.
- Behavior SHA-256: `8c2bdaa213f11b253d3ffcae1653bd01536879bb5c254a1586ded9ae522a868e`.
- Validator/runtime: `stage2a.validator.v2` / `stage2a.worker.v1`.
- Context/proposal/pool: `stage2b.context.v1`, `stage2b.proposal.v1`,
  `stage2b.pool.v1`.
- Integration contract SHA-256: `fb8e0d609a691655ba969a64b4affb7fd8781aa5dd485c42b9402829a9d4a439`.
- Preregistered replay corpus: `configs/stage7-heg-replay-corpus-v1.json`,
  SHA-256 `ecf22a8a43ad3cb0534f41dbae3c8dbe435e0044f1a4dbefd5217fab2b46ac30`.
- Frozen feature limits: lengths 4–9, witness cap 32, cycle budget 20,000,
  distance budget 256, local-risk budget 2,048.

The policy is not enabled by default. The Director can submit only the reviewed
catalog ID, and the parameter cannot be patched. No source path, source text,
model tool, shell command, scorer, database, network, or M4 handle crosses the
worker boundary.

## Gates

The acceptance gate is terminal and preregistered:

1. exact packaged-source and identity verification;
2. deterministic compatibility/replay corpus of 2,048 records;
3. 30-case red-team boundary suite;
4. additive v17→v18 Online Backup migration with integrity/FK checks;
5. checkpoint/resume identity and disabled-lane refusal;
6. process-group timeout/crash/reap and no-fallback checks;
7. scorer/M4 isolation and selected-plan-only scoring;
8. 100,000 persistent worker calls, p99 ≤5 ms, zero failures/orphans;
9. faithful HEG baseline-vs-ranked throughput projection, median regression
   ≤10% and each preregistered stratum ≤15%.

Any failed or unavailable gate yields `NO_GO`; it does not enable rollout and
does not create a future Stage 7R issue. Results, command lines, hashes, and
artifacts are recorded in the adjacent evidence manifest.

## Terminal result

The frozen implementation is commit `7bff0a816196ea6fe780677b9ded5433b5641e1d`,
tagged `heg-mutation-forge-ranking-seam-frozen-v1`. The authoritative gate
artifact was produced from that commit on 2026-08-01 and is retained at
`/home/user/DEV/heg-evidence/mutation-forge-ranking-seam-final/authoritative-gates.json`.

- Exact identity/source, checkpoint/resume, disabled-by-default refusal,
  process-group reap, scorer/M4 isolation, and selected-plan-only scoring:
  **PASS** (the 30-case red-team suite passed 30/30).
- Replay corpus: **PASS**, 2,048 records and zero canonical, priority, rank,
  selection, or policy-identity mismatches.
- v17→v18 SQLite migration: **PASS** using `sqlite3.Connection.backup`, with
  `PRAGMA integrity_check = ok`, zero foreign-key violations, and the durable
  policy-identity ledger present. The process-safety evidence reports one
  worker call, zero failures, and zero orphans. Artifact:
  `/home/user/DEV/heg-evidence/mutation-forge-ranking-seam-final/migration-process.json`.
- Persistent policy worker: **PASS**, 100,000 calls, p99 116,330 ns against the
  5,000,000 ns gate, zero failures, and zero orphans.
- Repository verification: **PASS** for `make doctor`, `make test`, `make
  check`, `make benchmark-smoke`, `make dashboard-smoke`, the focused proposal,
  protocol, lane, and recovery tests, and `git diff --check`.
- Faithful HEG end-to-end projection: **FAIL**. Order 14 measured baseline
  15,075.0434 versus ranked 135.8712 evaluations/s (ratio 0.009013); order 16
  measured baseline 11,923.0069 versus ranked 127.3887 evaluations/s (ratio
  0.010684). Both preregistered strata exceed the allowed 10% median / 15%
  per-stratum regression.

The authoritative terminal decision is **`NO_GO`**. The policy remains opt-in
and disabled by default; no rollout is enabled and no future Stage 7R issue is
created. The gate runner wrote the complete artifact before its compact status
printer raised a non-authoritative `TypeError` while taking `len()` of the
integer red-team pass count; the recorded gate fields above are the source of
truth.

See `MUTATION_FORGE_RANKING_SEAM_EVIDENCE.json` for the compact evidence
manifest and hashes.
