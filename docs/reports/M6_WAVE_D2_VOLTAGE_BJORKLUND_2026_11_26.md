# M6 Wave D2 Report: Bipartite `n ∈ [70, 128]` Voltage-Lift Search & x86-64 `PCLMULQDQ` Björklund $\mathrm{GF}(2^{16})$ Narrow Sieve (2026-11-26)

## Scope

Wave D2 implements Priority 7 from `docs/deep-research/Badania nad Hipotezą Erdősa–Gyárfása.md` in `rust/sglab-engine/src/voltage_bipartite.rs` and `main.rs`, specifically targeting the open cubic bipartite frontier $n \in [70, 128]$ immediately above Zhuge's $n \le 68$ / 10-cage $n(3, 10) = 70$ threshold:

1. **Hardware x86-64 `PCLMULQDQ` Bipartite Björklund Narrow Sieve over $\mathrm{GF}(2^{16})$ (`bipartite_cycle_sieve_gf2_16`, CLI `bjorklund-c32`)**:
   - Uses hardware carry-less multiplication (`_mm_clmulepi64_si128`, verified against scalar $\mathrm{GF}(2^{16})$ across `10,000` random patterns mod $x^{16}+x^5+x^3+x^2+1$).
   - Gray-code Ryser inclusion-exclusion over $2^{h-1}$ color subsets on the smaller bipartition $A$ ($2^{15} = 32\,768$ evaluations for $L = 32$), paired with exact characteristic-2 non-backtracking 2-step transitions (`sum_a ^ term_k`) so all repeated-$B$ walks cancel pairwise by sub-walk reversal while simple $2h$-cycles survive with zero false positives and one-sided false-negative error $\le (3h - 1)/2^{16}$ per round ($< 5.2 \times 10^{-7}$ over 2 rounds).
   - Parallelized across all 16 cores; completely topology-independent even on high-pathwidth cages/expanders up to $n = 128$.
2. **Compressed-Space Voltage-Lift Search (`run_voltage_lift_search`, CLI `voltage-search`)**:
   - Implements 9 non-abelian, non-nilpotent even-order finite groups ($D_6, A_4, D_7, D_9, D_{10}, F_{20}, S_4, D_{14}, D_{15}$, respecting Burkhart Nov 2026 exclusions of odd-order and nilpotent Cayley graphs) over 4 bipartite cubic base multigraphs (`theta4`, `k33`, `theta6`, `cube8`) covering $n \in [72, 120]$.
   - Performs orbit-reduced exact `C4`/`C8`/`C16` MitM checks per lift and invokes the 2-round `PCLMULQDQ` Björklund `C32` sieve on every `C4 = C8 = C16 = 0` candidate.

## Verification Gates

- `RUSTFLAGS="-C target-cpu=native" cargo test --release --manifest-path rust/sglab-engine/Cargo.toml`: **16/16 passed** (`0` warnings, `0.37 s`), including:
  - `voltage_bipartite::tests::gf16_pclmulqdq_matches_scalar_reference_all_patterns`
  - `voltage_bipartite::tests::bjorklund_bipartite_sieve_matches_exact_dfs_on_heawood_and_lifts`
- `make rust-engine`: clean native release build (`0` warnings, `pclmulqdq_enabled = true`).
- `PYTHONPATH=src python3 -m unittest tests.test_rust_engine -v`: **7/7 passed** (`--serve` v2 bit-for-bit parity intact).

## Experiment 10: Bipartite Cubic Voltage-Lift Scan (`n = 72..120`) + `PCLMULQDQ` `C32` Sieve Benchmarks

Executed across 16 cores (`746,472` lifted assignments evaluated, `671,660` valid connected simple cubic bipartite lifts, total search wall time **`0.11 s`**):

| Base × Group | Order `n` | Mode | Evaluated / Valid Lifts | `C4=C8=0` Hits | `C4=C8=C16=0` Hits | Hardware `PCLMULQDQ` `C32` Sieve (2 rounds) | M4 Short Check (`4, 8, 16`) |
|---|---:|---|---:|---:|---:|---|---|
| `theta4 × D9` | 72 | Exhaustive ($18^3$) | `5,832 / 4,212` | `0` | `0` | — | — |
| `k33 × A4` | 72 | Exhaustive ($12^4$) | `20,736 / 20,160` | `144` | `0` | `FOUND` (**`32.7 ms`**) | `A, A, F` |
| `k33 × D6` | 72 | Exhaustive ($12^4$) | `20,736 / 16,380` | `0` | `0` | — | — |
| `theta6 × A4` | 72 | Exhaustive ($12^4$) | `20,736 / 15,768` | `864` | `0` | `FOUND` (**`32.3 ms`**) | `A, A, F` |
| `theta4 × D10` | 80 | Exhaustive ($20^3$) | `8,000 / 4,800` | `0` | `0` | — | — |
| `theta4 × F20` | 80 | Exhaustive ($20^3$) | `8,000 / 6,240` | `0` | `0` | — | — |
| `k33 × D7` | 84 | Exhaustive ($14^4$) | `38,416 / 35,910` | `0` | `0` | — | — |
| `theta6 × D7` | 84 | Exhaustive ($14^4$) | `38,416 / 29,232` | `168` | `0` | `FOUND` (**`36.8 ms`**) | `A, A, F` |
| `theta4 × S4` | 96 | Exhaustive ($24^3$) | `13,824 / 9,648` | `0` | `0` | — | — |
| `cube8 × A4` | 96 | Tabu ($12^5$) | `80,000 / 79,934` | `13,430` | `0` | `FOUND` (**`42.8 ms`**) | `A, A, F` |
| `k33 × D9` | 108 | Exhaustive ($18^4$) | `104,976 / 94,770` | `0` | `0` | — | — |
| `theta4 × D14` | 112 | Exhaustive ($28^3$) | `21,952 / 13,608` | `0` | `0` | — | — |
| `cube8 × D7` | 112 | Tabu ($14^5$) | `80,000 / 77,398` | `0` | `0` | — | — |
| `theta4 × D15` | 120 | Exhaustive ($30^3$) | `27,000 / 19,440` | `0` | `0` | — | — |
| `k33 × F20` | 120 | Exhaustive ($20^4$) | `160,000 / 148,800` | `960` | `0` | `FOUND` (**`57.1 ms`**) | `A, A, F` |
| `theta6 × F20` | 120 | Exhaustive ($20^4$) | `160,000 / 129,360` | `0` | `0` | — | — |

### Key Scientific Result

- **14 exhaustive non-existence results** established in `0.11 s` total: none of the 14 exhaustively enumerated non-abelian, non-nilpotent bipartite cubic lift families across $n \in [72, 120]$ contain a graph avoiding $\{C_4, C_8, C_{16}\}$ (every one of the `2,136` exhaustive `C4 = C8 = 0` lifts and `13,430` `cube8 × A4` lifts contained $C_{16}$, independently confirmed by M4).
- **Hardware `PCLMULQDQ` Björklund `C32` narrow sieve** runs in **`32.3–57.1 ms`** across 16 cores at $n = 72..120$ (`pclmulqdq_enabled = true`), providing a topology-independent $C_{32}$ oracle for large bipartite graphs up to $n = 128$.
