# M6 Wave C Report: Exact Bitset MitM `C16`, Forced-Edge Branch-and-Reduce `C_n`, and Single-Pass Frontier DP (2026-11-26)

## Scope

Wave C implements Priorities 5 and 6 from `docs/deep-research/Badania nad Hipotezą Erdősa–Gyárfása.md` in `rust/sglab-engine/`, directly resolving the two bottlenecks identified in Wave B Experiment 7 (`C16` DFS `node_budget` exhaustion on `n = 50..62` and exponential `C64 = 0` verification timeouts on `n = 64`):

1. **Exact Bitset Meet-in-the-Middle for `C16` (`count_c16_mitm_u64` in `rust/sglab-engine/src/cycles.rs`)**:
   - Canonical minimum-vertex decomposition (`s < v1..v7, t`): enumerates simple length-8 half-paths (`<= 384` per start vertex in cubic graphs), buckets 7-vertex interior masks by opposite endpoint `t`, and counts unordered disjoint pairs `(m1 & m2) == 0` (exact bijection, zero double-counting, zero `node_budget` exhaustion).
   - Wired directly into `count_cycles_fast_u64` for `length == 16` (`--serve` protocol v2 `count_cycles` remains untouched and bit-for-bit parity-tested against C++).
2. **Deterministic Forced-Edge Branch-and-Reduce for Cubic Hamiltonian Cycle (`exact_cubic_hamiltonian_bnr_u64` in `rust/sglab-engine/src/exact_verify.rs`)**:
   - Implements Eppstein (2007) / Xiao–Nagamochi (2016) propagation (`ad < 2`, `fd > 2`, `fd == 2` delete incident undecided edges, `ad == 2` force remaining edges, path-endpoint union-find premature-subcycle lookahead deletion, and Tarjan 2-connectivity pruning) with `fd == 1` Eppstein branching.
   - Wired as the deterministic 2nd line after Pósa+Thomason in `count_hamiltonian_u64` (`n >= 32`, `max_deg <= 3`) so non-Hamiltonian `n = 64` graphs certify `C64 = 0, complete = true` in sub-millisecond time instead of exhausting DFS budgets.
3. **Single-Pass Frontier DP Exact Spectrum Verifier (`exact_spectrum_frontier_dp` in `exact_verify.rs` + CLI `verify-exact --graph6 <g6>` in `main.rs`)**:
   - Multi-start greedy min-frontier edge ordering + 4-bit packed `u64` mate-array frontier state mapped to `u128` bitmask of reachable cycle lengths, strictly enforcing single simple cycles (`cycle_spectrum |= shifted` only when no other frontier vertex has degree 1).
   - Independent fast research cross-check CLI (`verify-exact`); M4 (`_build/sglab-cyclecheck`) remains the sole counterexample certification authority in campaigns per `AGENTS.md`.

## Verification Gates

- `cargo test --release --manifest-path rust/sglab-engine/Cargo.toml`: **13/13 passed** (`0` warnings, `0.13s`), including:
  - `cycles::tests::c16_mitm_matches_parity_dfs_exactly` (exact parity against DFS across cubic & mixed-degree `n = 16, 20, 24, 32` plus exact Markström-24 `C16 = 228`),
  - `exact_verify::tests::bnr_exact_cubic_hamiltonian_matches_dfs_and_certifies_snarks` (exact DFS agreement on `n = 8..24` + exact non-Hamiltonian certification on Petersen and Flower Snarks `J_5, J_7, J_9, J_15` (`n = 60`)),
  - `exact_verify::tests::frontier_dp_certifies_exact_spectrum_on_markstrom24_petersen_and_h7_n64` (exact full spectrum `{3..=24}` on Markström-24, `{5, 6, 8, 9}` on Petersen, and full `{C4, C8, C16, C32, C64}` on `Petersen + 9·H7` at `n = 64` agreeing with B&R on `C64`).
- `make rust-engine`: clean native release build (`0` warnings).
- `PYTHONPATH=src python3 -m unittest tests.test_rust_engine tests.test_resources -v`: **11/11 passed**.

## Experiment 8: Wave C Verification Speedup & `n = 50..64` Frontier Re-Scan

### Part 1 — `verify-exact` on all 13 Experiment 7 Graphs (Resolving All Four M4 `C64` Timeouts)

| Graph (from Exp 7) | Order `n` | `verify-exact` Wall Time | Exact `C16` (MitM) | B&R Nodes (`C64`) | Frontier DP (`w`, peak states) | Exact Lengths Status |
|---|---:|---:|---:|---:|---|---|
| `ablate_n64_random_total` | 64 | **`39.60 ms`** | `1,175` | `1` | `COMPLETE (w=11, 91,718)` | `4:F, 8:A, 16:F, 32:F, 64:A` (M4 timed out at 10s!) |
| `ablate_n64_random_hash3e` | 64 | **`23.49 ms`** | `1,096` | `1` | `COMPLETE (w=11, 50,475)` | `4:F, 8:A, 16:F, 32:F, 64:A` (M4 timed out at 10s!) |
| `ablate_n64_h7_lex_hash3e` | 64 | **`0.72 ms`** | `54` | `169` | `COMPLETE (w=8, 192)` | **`4:A, 8:A, 16:F, 32:F, 64:A`** (`14,000×` faster than 10s M4 timeout!) |
| `ablate_n64_h7_total_3e` | 64 | **`0.50 ms`** | `2` | `1` | `COMPLETE (w=7, 119)` | `4:F, 8:F, 16:F, 32:F, 64:A` |
| `waveb_n50..62_h7_lex_3e` | 50..62 | `0.40–45.57 ms` | `354..1,013` | `0` | `COMPLETE (w=7..11)` | `4:A, 8:A, 16:F, 32:F` |
| `waveb_sb41_k25_m25_*` | 25 (`n=49`) | **`0.01–0.03 ms`** | `126` | `0` | `SKIPPED` | `4:A, 8:A, 16:F` |

### Part 2 — 1-Block Cubic `n = 50..64` Re-Scan (`H7 + lex_short + 3-edge + Hashimoto + MitM C16 + B&R C64`, 3s/order, 16 cores)

| Order `n` | Wave B `C16` (DFS-capped) | Wave C Exact `C16` (MitM) | Reduction vs Wave B | `verify-exact` Time | Exact Absent Lengths |
|---:|---:|---:|---:|---:|---|
| 50 | `354` | **`335`** | `-5.4%` | `0.6 ms` | `[4, 8]` |
| 52 | `422` | **`149`** | **`-64.7%`** | `0.4 ms` | `[4, 8]` |
| 54 | `414` | **`93`** | **`-77.5%`** | `0.4 ms` | `[4, 8]` |
| 56 | `389` | **`218`** | **`-44.0%`** | `0.5 ms` | `[4, 8]` |
| 58 | `863` | **`132`** | **`-84.7%`** | `0.5 ms` | `[4, 8]` |
| 60 | `1,013` | **`106`** | **`-89.5%`** | `0.6 ms` | `[4, 8]` |
| 62 | `993` | **`93`** | **`-90.6%`** | `0.5 ms` | `[4, 8]` |
| 64 | `54` | **`54`** | exact `C64=0` | `0.7 ms` | **`[4, 8, 64]`** |

### Scientific Summary

- **No counterexample was found**; every candidate was refuted by exact verification (both M4 and `verify-exact` agreed 100% on every decided length).
- Replacing `C16` DFS with exact Bitset MitM eliminated `node_budget` exhaustion across the entire 1-block cubic `n = 50..64` frontier, cutting true `C16` inside the strict `C4 = C8 = 0` basin by **65%–91%** at `n = 52..62` (down to **`C16 = 93`** at `n = 54` and `n = 62`, **`C16 = 54, C64 = 0`** at `n = 64`).
- Forced-Edge Branch-and-Reduce + Frontier DP resolved every `n = 64` candidate (including all four M4 10-second `C64` timeouts) deterministically in **`0.50–39.60 ms`**.
