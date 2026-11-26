# M6 Wave A Report: Closed Ducoffe–Dumitru Filter & Conjecture 4.1 Single-Block Mode (2026-11-26)

## Scope

Wave A implements Priority 1 from the November 2026 Deep Research synthesis (`docs/deep-research/Badania nad Hipotezą Erdősa–Gyárfása.md`) in the native Rust engine (`rust/sglab-engine/`):

1. **Closed Ducoffe–Dumitru structural filter (`graph.rs`)** matching arXiv:2609.28594:
   - Strict 2-connectivity (`is_biconnected()`) for every even order `n` (Theorem 2.3 & Corollary 2.4; rejects even-order 2-block cut-vertex artifacts such as `[25, 12]` on `n = 36` and bridges under Corollary 2.2).
   - For odd orders `n`, admits only strictly 2-connected graphs or symmetric 1-clique-sums of two equal-order `(n+1)/2`, equal-edge-count, 2-degenerate blocks sharing a single cut-vertex of exact degree `4`.
   - Doubling-reduction Lemma 3.5 (`auxiliary_m_valid()`): auxiliary graph `M` on `H = {d >= 4}` induced by `L_2` vertices must be simple (no parallel edges), satisfy `|L_2| <= max(0, 2h - 3)`, and be 2-degenerate.
   - Theorem 3.7 global bounds for `n >= 13`: `h <= floor(n/3) - 1` and `m <= 2n - 2`.
2. **Conjecture 4.1 / Theorem 4.2 single-block search mode (`--mode single_block_41`, `mutation.rs`, `search.rs`, `main.rs`)**:
   - Directly searches a single 2-connected, 2-degenerate block `B` of order `k` with vertex `0` of exact degree `2` (both neighbors of degree `3`) and all other vertices of degree `>= 3`, independent `H`, and Lemma 3.5 validity.
   - Gluing two copies `B +_0 B` yields a strictly legal odd Ducoffe–Dumitru candidate of order `n = 2k - 1` with identical cycle spectrum (multiplicity ×2) and automatic `C32 = C64 = 0` for `k in [21, 31]` (`n in [41, 61]`).
3. **Exact Markström-24 & 1-edge subdivision seed (`--seed-style markstrom`, `mutation.rs`)**:
   - Constructed exact `K4 -> K3 + 3·H7` Markström-24 (`C4 = 0, C8 = 0, C16 = 228`) and verified optimal edge `(3, 12)` subdivision for `k = 25` (`n = 49`) yielding exact `C4 = 0, C8 = 0, C16 = 187` per block (`C4 = 0, C8 = 0, C16 = 374, C32 = 0` when glued).

## Verification Gates

- `cargo test --release --manifest-path rust/sglab-engine/Cargo.toml`: **8/8 passed** (0 warnings, `0.09s`), including:
  - `closed_ducoffe_filter_enforces_parity_symmetry_and_lemma35`
  - `within_block_mutations_preserve_symmetric_two_block_and_c32_zero`
  - `single_block_41_markstrom25_and_gluing_theorem42`
- `make rust-engine`: clean native release build (`_build/sglab-rust-engine`, 0 warnings).
- `PYTHONPATH=src python3 -m unittest tests.test_rust_engine tests.test_resources -v`: **11/11 passed** (`--serve` protocol v2 parity with C++ unchanged).

## Experiment 6: M4-Certified `single_block_41` Scan (`k = 21..31`, `n = 41..61`)

Hardware: 16-core AMD Ryzen 9 7950X3D (`--workers 16`, `--cap 64 --adaptive-cap-max 512`, `3.0s/order` ILS-tabu + dedicated `6.0s` Markström-25 ILS & SA runs). Every best block `B` was glued into `G = B +_0 B` of order `n = 2k - 1` and independently certified across all forbidden lengths `[4, 8, 16, 32]` by the M4 C++17 exact verifier (`_build/sglab-cyclecheck`).

| Case | Block `k` | Glued `n` | Throughput | Eff. cap | Block `total` | Block `(C4, C8, C16)` | M4 Certified Absent (`G = B +_0 B`) | M4 Found |
|---|---:|---:|---:|---:|---:|---|---|---|
| `sb41_k21_ils` | 21 | 41 | `4.85M ev/s` | 256 | **2** | `(2, 0, 0)` | `[8, 16, 32]` | `[4]` |
| `sb41_k22_ils` | 22 | 43 | `3.75M ev/s` | 256 | **3** | `(3, 0, 0)` | `[8, 16, 32]` | `[4]` |
| `sb41_k23_ils` | 23 | 45 | `4.46M ev/s` | 256 | **3** | `(3, 0, 0)` | `[8, 16, 32]` | `[4]` |
| `sb41_k24_ils` | 24 | 47 | `3.60M ev/s` | 512 | **3** | `(3, 0, 0)` | `[8, 16, 32]` | `[4]` |
| `sb41_k25_ils` | 25 | 49 | `4.15M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k26_ils` | 26 | 51 | `3.34M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k27_ils` | 27 | 53 | `3.78M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k28_ils` | 28 | 55 | `3.09M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k29_ils` | 29 | 57 | `3.49M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k30_ils` | 30 | 59 | `2.95M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k31_ils` | 31 | 61 | `3.42M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k25_markstrom_ils` | 25 | 49 | `4.18M ev/s` | 512 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |
| `sb41_k25_markstrom_sa` | 25 | 49 | `3.63M ev/s` | 256 | **3** | `(2, 1, 0)` | `[16, 32]` | `[4, 8]` |

### Scientific Interpretation

- **No counterexample was found**; M4 refuted all 13 glued candidates with zero timeouts.
- Operating on the half-size block `B` (`k = 21..31`) sustains `2.95–4.85M ev/s` and drives `C16 = 0, C32 = 0` across the entire `n = 41..61` odd frontier in 3 seconds per order, reaching `total = 2` (`C4 = 2`, `C8 = C16 = C32 = 0`) at `n = 41` and `total = 3` at `n = 43..61`.
- At `k = 25..31`, both random and Markström-25 trajectories converge to the exact `(C4=2, C8=1, C16=0)` local minimum because `ordering_key` minimizes `total` before `C4/C8` and single 2-edge switches cannot cross the `C4 = C8 = 0` barrier without spiking `C16`. This directly motivates Wave B (H7 gadget seeds, 3-edge switches, hot-edge weighting, and Hashimoto macro-gradient).
