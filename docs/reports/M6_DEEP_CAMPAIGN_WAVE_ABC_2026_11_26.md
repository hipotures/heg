# M6 Deep Research Campaign Report: Wave A + B + C + `LexCutoff` (2026-11-26)

## Executive Summary

A 4-phase, 16-core deep research campaign was executed on AMD Ryzen 9 7950X3D using the full Wave A + B + C Rust engine (`_build/sglab-rust-engine`, commit `2436da2`) augmented with exact `LexCutoff` short-cycle early pruning and classic ILS return-to-best intensification:

- **Total evaluations**: **`1,965,629,664`** (~**1.97 billion** graph evaluations) in **`579.5 s`** (`9.66 min` wall time).
- **Peak throughput**: **`16.68M ev/s`** on `single_block_41` (`k = 21`, `lex_short`), **`4.56–7.21M ev/s`** on `single_block_41` `total`, **`0.18–0.45M ev/s`** on 1-block cubic `n = 50..62`, and **`0.08–0.11M ev/s`** on `n = 64` (`11×` speedup over pre-`LexCutoff` Wave C).
- **Counterexample verdict**: **No counterexample to the Erdős–Gyárfás conjecture was found.** Every single champion across all phases was independently refuted and cross-checked with **100% agreement** between the M4 C++17 exact verifier (`_build/sglab-cyclecheck`) and Wave C `verify-exact` (MitM `C16` + Forced-Edge B&R `C_n` + single-pass Frontier DP).
- **New strictly 2-connected records**:
  - **1-block strictly 2-connected cubic (`biconn = True, bridges = 0`, strictly inside `C4 = C8 = 0`)**:
    - `n = 54`: exact **`C16 = 71`** (`verify-exact`: `0.4 ms`)
    - `n = 60`: exact **`C16 = 65`** (`verify-exact`: `0.4 ms`)
    - `n = 62`: exact **`C16 = 44`** (`verify-exact`: `0.5 ms`, ~30× below random cubic)
    - `n = 64`: exact **`C16 = 32`** (`verify-exact`: `0.7 ms`, **43.8×** below random cubic `~1,403`)
    - `n = 70`: exact **`C16 = 4, C64 = 0 (ABSENT)`** (`verify-exact`: `0.6 ms`)
    - `n = 78`: exact **`C4 = 0, C8 = 0, C16 = 0 (ABSENT)`** (`verify-exact`: `0.8 ms` — autonomous rediscovery of valid Exoo $G_{78}$ port orientation)
  - **Conjecture 4.1 / Theorem 4.2 strictly legal odd 1-clique-sums (`G = B +_0 B`, 100% strictly 2-connected & 2-degenerate blocks, zero bridges)**:
    - `k = 21 (n = 41)`: `total = 2` per block (`C4 = 2`, M4-certified absent `[8, 16, 32]`)
    - `k = 33 (n = 65)` & `k = 35 (n = 69)`: **`total = 3` per block** (`C4 = 3`, **M4-certified absent `[8, 16, 32, 64]`**)
    - `k = 22..37 (n = 43..73)` strictly inside `C4 = C8 = 0`: down to **`C16 = 111`** (`k = 23, n = 45`), **`C16 = 115`** (`k = 35, n = 69`), **`C16 = 121`** (`k = 29, n = 57`), and **`C16 = 126`** (`k = 25, n = 49`, Markström-25 basin).

## Pre-Campaign Engine Upgrade (`2436da2`)

- **Exact `LexCutoff` (`rust/sglab-engine/src/cycles.rs`, `search.rs`)**: Evaluates lengths in strict ascending order `[4, 8, 16, 32, 64]` under `--objective lex_short` and aborts immediately (~10 ns on `C4 > 0`, ~60 ns on `C8 > 0`, early-stop MitM on `C16 > ref_c16`), boosting `n = 64` `lex_short` from `0.01M` to `0.11M ev/s` (`11×`) while preserving exact ties for Hashimoto plateau breaking.
- **Classic ILS return-to-best (`search.rs`)**: After `10 × perturbation_interval` stagnant evaluations in a worse basin, resets the walk to `best_graph` so subsequent perturbations explore fresh local optima around the champion rather than drifting in random expander space.
- Verified with `13/13` Rust release tests (`0` warnings, `0.13 s`) and `7/7` Python `--serve` v2 parity tests.

## Phase 1: Deep Conjecture 4.1 `single_block_41` Scan (`k = 21..31` + `33, 35, 37`)

All 28 champions (14 orders × 2 objectives) were audited as strictly 2-connected (`biconn = True, bridges = 0`), 2-degenerate blocks `B` whose symmetric gluing `G = B +_0 B` satisfies `PLUGIN.validate_graph` and the closed Ducoffe–Dumitru Theorem 2.3 / Corollary 2.4 / Lemma 3.5 filter, with zero M4 timeouts (`unknown = []`).

| Block `k` | Glued `n` | `total` Run `(C4, C8, C16[, C32])` | `total` Speed | M4 Absent (`total`) | `lex_short` Seed | `lex_short` `(C4, C8, C16[, C32])` | `lex_short` Speed | M4 Absent (`lex_short`) |
|---:|---:|---|---:|---|---|---|---:|---|
| 21 | 41 | `(2, 0, 0)` | `7.21M/s` | `[8, 16, 32]` | random | `(0, 1, 72)` | `16.68M/s` | `[4, 32]` |
| 22 | 43 | `(3, 0, 0)` | `5.73M/s` | `[8, 16, 32]` | random | `(0, 0, 161)` | `14.49M/s` | `[4, 8, 32]` |
| 23 | 45 | `(3, 0, 0)` | `6.67M/s` | `[8, 16, 32]` | `h7_exp` | **`(0, 0, 111)`** | `15.58M/s` | `[4, 8, 32]` |
| 24 | 47 | `(3, 0, 0)` | `5.54M/s` | `[8, 16, 32]` | random | `(0, 0, 177)` | `13.43M/s` | `[4, 8, 32]` |
| 25 | 49 | `(2, 1, 0)` | `6.20M/s` | `[16, 32]` | markstrom | **`(0, 0, 126)`** | `14.41M/s` | `[4, 8, 32]` |
| 26 | 51 | `(2, 1, 0)` | `5.08M/s` | `[16, 32]` | random | `(0, 0, 156)` | `12.44M/s` | `[4, 8, 32]` |
| 27 | 53 | `(2, 1, 0)` | `5.68M/s` | `[16, 32]` | `h7_exp` | **`(0, 0, 124)`** | `13.41M/s` | `[4, 8, 32]` |
| 28 | 55 | `(2, 1, 0)` | `4.75M/s` | `[16, 32]` | random | `(0, 0, 165)` | `11.89M/s` | `[4, 8, 32]` |
| 29 | 57 | `(2, 1, 0)` | `5.33M/s` | `[16, 32]` | `h7_exp` | **`(0, 0, 121)`** | `12.42M/s` | `[4, 8, 32]` |
| 30 | 59 | `(2, 1, 0)` | `4.56M/s` | `[16, 32]` | random | `(0, 0, 171)` | `11.40M/s` | `[4, 8, 32]` |
| 31 | 61 | `(2, 1, 0)` | `5.19M/s` | `[16, 32]` | `h7_exp` | `(0, 0, 138)` | `11.83M/s` | `[4, 8, 32]` |
| 33 | 65 | **`(3, 0, 0, 0)`** | `0.24M/s` | **`[8, 16, 32, 64]`** | `h7_exp` | `(0, 0, 142, 23)` | `0.24M/s` | `[4, 8, 64]` |
| 35 | 69 | **`(3, 0, 0, 0)`** | `0.16M/s` | **`[8, 16, 32, 64]`** | `h7_exp` | **`(0, 0, 115, 512)`** | `0.28M/s` | `[4, 8, 64]` |
| 37 | 73 | `(2, 2, 0, 0)` | `0.17M/s` | `[16, 32, 64]` | `h7_exp` | `(0, 0, 128, 512)` | `0.34M/s` | `[4, 8, 64]` |

## Phase 2 & Phase 3: Deep 1-Block Cubic Frontier (`n = 50..64` + `70, 78`) & Alternating SA/ILS Polish

### Strictly 2-Connected `lex_short` Champions (`biconn = True, bridges = 0`, 100% Certified)

| Order `n` | Phase 2 Exact `C16` | Phase 3 Polish `C16` | Diameter | `verify-exact` Time | Exact Absent Lengths | Structural Audit |
|---:|---:|---:|---:|---:|---|---|
| 50 | `136` | — | 10 | `0.4 ms` | `[4, 8]` | 1 block `[50]`, 0 bridges |
| 52 | `95` | — | 9 | `0.4 ms` | `[4, 8]` | 1 block `[52]`, 0 bridges |
| 54 | `111` | **`71`** | 9 | `0.4 ms` | `[4, 8]` | 1 block `[54]`, 0 bridges |
| 56 | `107` | — | 10 | `0.4 ms` | `[4, 8]` | 1 block `[56]`, 0 bridges |
| 58 | `93` | — (`88` in 2s bench) | 10 | `0.4 ms` | `[4, 8]` | 1 block `[58]`, 0 bridges |
| 60 | **`65`** | — | 10 | `0.4 ms` | `[4, 8]` | 1 block `[60]`, 0 bridges |
| 62 | `76` | **`44`** | 10 | `0.5 ms` | `[4, 8]` | 1 block `[62]`, 0 bridges |
| 64 | `46` | **`32`** | 10 | `0.7 ms` | `[4, 8]` | 1 block `[64]`, 0 bridges |
| 70 | **`4`** | — | 10 | `0.6 ms` | **`[4, 8, 64]`** | 1 block `[70]`, 0 bridges |
| 78 | **`0`** | — | 11 | `0.8 ms` | **`[4, 8, 16]`** | 1 block `[78]`, 0 bridges (Exoo $G_{78}$) |

### Structural Honesty Note on Unconstrained `cubic_first` `total` Runs

In Phase 2 `total` runs under `cubic_first` (which enforces connectivity and 3-regularity, not 2-connectivity), the search drove `C16 = C32 = 0` (`total = 4..8`) on `n = 50..64` by forming `3–6` bridges separating small blocks of size `7..16`. Under Ducoffe–Dumitru Corollary 2.2 / Section 6, multi-bridge decompositions are excluded as minimal general counterexamples (and conjectured excluded for minimal cubic counterexamples). By contrast, **every single `lex_short` champion above (`n = 50..78`) and every single `single_block_41` champion (`k = 21..37`) remained strictly 2-connected with zero bridges**.

## Scientific Takeaways & Next Directions

1. **Alternating SA + 3-edge switches broke deep `C4 = C8 = 0` barriers**: Round 1 of Phase 3 SA (`T = 2.5, p_3edge = 0.30`) immediately dropped strictly 2-connected `C16` by `30%–42%` (`n=54: 111 -> 71`, `n=62: 76 -> 44`, `n=64: 46 -> 32`), after which Rounds 2–4 plateaued — confirming that crossing the next barrier from `C16 = 32..44` toward `C16 = 0` requires multi-edge destroy-and-repair (**Wave D: Micro-SAT-LNS** rewiring 6–10 hot edges simultaneously).
2. **Exact sub-millisecond verification at `n = 50..78`**: Wave C `verify-exact` certified every strictly 2-connected `H_7` champion from `n = 50` all the way to `n = 78` in **`0.4–0.8 ms`**, eliminating all `C64` verification bottlenecks.
3. **Raw artifacts preserved**: Full structured JSON log with every champion's `graph6`, evaluation counts, throughput, and dual M4 + `verify-exact` proofs saved in the session scratch directory (`deep_campaign_wave_abc_results.json`).
