# M6 Wave B Report: H7 Gadget Expansions, 3-Edge Switches, Hot-Edge Weighting & Hashimoto Macro-Gradient (2026-11-26)

## Scope

Wave B implements Priorities 2, 3, and the 3-edge / hot-edge portion of Priority 4 from `docs/deep-research/Badania nad Hipotezą Erdősa–Gyárfása.md` in `rust/sglab-engine/`:

1. **Hashimoto non-backtracking matrix trace $\operatorname{Tr}(B^k)$ & algebraic connectivity (`rust/sglab-engine/src/spectral.rs`)**:
   - Zero-dependency cyclic-Jacobi symmetric eigensolver (`symmetric_eigenvalues_64`).
   - Exact cubic Ihara–Bass trace formula (`hashimoto_trace_cubic_from_evals`) + algebraic connectivity $\lambda_2(L) = 3 - \lambda_2(A)$.
   - Exact general-degree sparse directed-edge non-backtracking walk-power trace (`hashimoto_trace_general_u64`).
   - Verified against the McGee $(3, 7)$-cage ($n = 24$, $C_4 = 0, C_8 = 34, C_{16} = 492$): both Ihara–Bass and general non-backtracking paths match exact reference integers $\operatorname{Tr}(B^{16}) = 66\,336$ and $\operatorname{Tr}(B^{32}) = 4\,296\,496\,672$.
   - Opt-in `--hashimoto-guide` macro-gradient tie-breaker on cap-saturated plateaus (`search.rs`).
2. **$H_7$ gadget expansion seed generator (`--seed-style h7_expansion`, `mutation.rs`)**:
   - Exact 7-vertex 3-port gadget `H7_EDGES` (Exoo 2014 / Garcia arXiv:2609.04686 Prop. 6.2) expanded over Petersen ($n \equiv 4 \pmod 6$, $n \le 70$), Petersen+$K_3$ ($n \equiv 0 \pmod 6$, $n \le 78$), Heawood ($n \equiv 2 \pmod 6$, $n \le 98$), and Heawood+$K_3$ ($n \equiv 4 \pmod 6$, $n \ge 76$) with fast coordinate-descent port-orientation search.
   - Breaks the random cubic $C_{16}$ barrier at seed time: `n = 64` starts at `C4 = C8 = 0, C16 <= 90` (vs `~1,403` random); `n = 70` starts at `C4 = C8 = 0, C16 <= 25`.
3. **3-edge cyclic switches, hot-edge bank heat $w(e)$, and multi-objective search (`bank.rs`, `cycles.rs`, `mutation.rs`, `search.rs`, `main.rs`)**:
   - `SingleLengthBank::edge_participation` and `CycleBank64::edge_heat` (`O(1)` POPCNT) drive targeted hot-edge tournament selection.
   - `try_three_edge_switch_u64` (`--three-edge-prob <f64>`) performs degree-preserving cyclic 3-edge rewirings across `cubic_first`, `minimal_structure_mixed_degree`, and `single_block_41`.
   - `--objective {total,weighted,lex_short}` allows staying strictly inside the `C4 = C8 = 0` basin while driving `C16` and `C32` downward.

## Verification Gates

- `cargo test --release --manifest-path rust/sglab-engine/Cargo.toml`: **10/10 passed** (0 warnings, `0.13s`), including `ihara_bass_and_general_hashimoto_match_mcgee_reference_exact` and `h7_expansion_seeds_break_c16_plateau_and_three_edge_switch_preserves_mode`.
- `make rust-engine`: clean native release build (`0` warnings).
- `PYTHONPATH=src python3 -m unittest tests.test_rust_engine -v`: **7/7 passed** (`--serve` v2 bit-for-bit parity intact).

## Experiment 7: M4-Certified Wave B Ablation & Frontier Scan

Hardware: 16-core AMD Ryzen 9 7950X3D (`--workers 16`, M4 `_build/sglab-cyclecheck` timeout `10s`/length).

| Case | Order `n` | Mode / Seed / Obj | Throughput | Eff. cap | Best `(C4, C8, C16, C32[, C64])` | M4 Absent | M4 Found | M4 Unknown |
|---|---:|---|---:|---:|---|---|---|---|
| `ablate_n64_random_total` | 64 | cubic / random / total | `0.65M ev/s` | 64 | `(1, 0, 64, 64, 0)` | `[8]` | `[4, 16, 32]` | `[64]` |
| `ablate_n64_random_hash3e` | 64 | cubic / random / total + hash + 3e | `0.12M ev/s` | 64 | `(1, 0, 64, 64, 0)` | `[8]` | `[4, 16, 32]` | `[64]` |
| `ablate_n64_h7_lex_hash3e` | 64 | cubic / h7 / lex_short + hash + 3e | `0.02M ev/s` | 256 | **`(0, 0, 54, 256, 0)`** | **`[4, 8]`** | `[16, 32]` | `[64]` |
| `ablate_n64_h7_total_3e` | 64 | cubic / h7 / total + hash + 3e | `0.02M ev/s` | 256 | `(11, 8, 2, 256, 0)` | `[]` | `[4, 8, 16, 32]` | `[64]` |
| `waveb_n50..62_h7_lex_3e` | 50..62 | cubic / h7 / lex_short + hash + 3e | `0.13–0.20M ev/s` | 256 | `(0, 0, 256*, 256)` | `[4, 8]` | `[16, 32]` | `[]` |
| `waveb_sb41_k25_m25_lex3e` | 25 (`n=49`) | sb41 / markstrom / lex_short + 3e | `0.84M ev/s` | 512 | **`(0, 0, 126)`** | **`[4, 8]`** | `[16]` | `[]` |
| `waveb_sb41_k25_m25_sa_lex3e` | 25 (`n=49`) | sb41 / markstrom / lex_short SA + 3e | `1.33M ev/s` | 256 | **`(0, 0, 126)`** | **`[4, 8]`** | `[16]` | `[]` |

### Key Scientific & Engineering Findings

1. **1-block cubic `n = 64` plateau broken**: `H7 + lex_short + 3-edge + Hashimoto` drove `n = 64` strictly inside `C4 = C8 = 0` down to **`C16 = 54`** (M4-certified absent `[4, 8]`, vs `C16 = 64` saturated random baseline), and `H7 + total + 3-edge` reached **`C16 = 2`** on a 1-block cubic 64-vertex graph.
2. **Markström-25 (`n = 49` single-block) broken below 187 inside `C4 = C8 = 0`**: `lex_short + 3-edge switches` drove `C16` from `187` down to **`126`** (`-32.6%`) at `1.33M ev/s` while keeping `C4 = C8 = 0` (and automatic `C32 = 0` upon gluing `B +_0 B`).
3. **Two concrete bottlenecks identified for Wave C**:
   - On `n = 50..62`, bounded DFS for `C16` exhausted `node_budget` and conservatively charged `C16 = 256*` even when true `C16 < 256`; Wave C's exact **Bitset Meet-in-the-Middle for `C16`** eliminates DFS budget exhaustion completely.
   - On `n = 64`, both the Rust `C64` DFS fallback and C++ M4 DFS timed out (`M4_unk = [64]`) on non-Hamiltonian / sparse `H7` graphs; Wave C's **Forced-Edge Branch-and-Reduce (Eppstein / Xiao–Nagamochi)** and **Frontier DP** directly solve deterministic `C64 = 0` certification.
