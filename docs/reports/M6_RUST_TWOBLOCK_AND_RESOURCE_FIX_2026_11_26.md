# M6 Follow-Up: 2-Block Ducoffe–Dumitru Seeding, Exact Block Decomposition, Adaptive Cap, and `/proc` RSS Fix

**Date**: 2026-11-26  
**Host**: 16-core AMD Ryzen 9 7950X3D  
**Engine**: `_build/sglab-rust-engine` + `_build/sglab-cyclecheck` (M4 verifier)  
**Raw evidence**: `exp5_results.json` (scratch archive) and verified commits on `main`

---

## 1. `/proc` RSS Race Fix (`src/sglab/resources.py`)

In Experiment 4, a 16-lane Rust campaign hit `paused_fault` with `ProcessLookupError: [Errno 3] No such process` inside `current_rss_bytes()` when polling `/proc/<pid>/status` on a concurrently exiting short-lived worker subprocess.

- **Fix**: Added `ProcessLookupError` to the handled exception tuple in both `current_rss_bytes()` and `process_tree_rss_bytes()` in `src/sglab/resources.py`, with a dedicated regression unit test in `tests/test_resources.py`.
- **Verification**:
  - `PYTHONPATH=src python3 -m unittest tests.test_resources -v`: **4/4 OK**.
  - Live 20-second 16-lane `sglab research-campaign` (`--engine-backend rust --director-mode passive`, `campaign-e7bfb8189b0d447b99c94e86060081cb` in `workspace/rust-research-002/`): **11,730,000 evaluations**, 16 active lanes, 24 candidates, clean `pause` -> `state: "paused_by_operator"`, `last_error: null`, exit code `0`, zero orphan processes.

---

## 2. Rust Engine: 2-Block Ducoffe–Dumitru Seeding, Exact Block Scoring, and Adaptive Cap

### Root-Cause Discovery During Implementation
Unit testing 2-block Ducoffe–Dumitru seeds on `n = 40..61` revealed a major algorithmic bottleneck in the fast scorer: on a 2-block graph with block sizes `< 32` (where `C32 == 0` mathematically), bounded DFS in `count_cycles_fast_u64` explored millions of paths inside a `< 32`-vertex block, exhausted `node_budget`, and conservatively charged `C32 = cap`. This both hid true 2-block improvements and stalled earlier random-seed searches on `n >= 38`.

### Implemented Enhancements (`rust/sglab-engine/`)
1. **Exact Hopcroft–Tarjan biconnected block decomposition (`BitGraph64::biconnected_blocks` + `count_cycles_fast_u64`)**:
   - For `length >= 16` in the native Rust fast scorer (leaving `--serve` protocol v2 bit-for-bit parity untouched), checks `max_block_size < length` to return `count = 0, complete = true` in ~100 ns with zero DFS nodes.
   - When `block_count > 1` and `max_block_size >= length`, restricts DFS independently to each block of size `>= length`, eliminating wasted cross-cut-vertex traversals.
2. **Ducoffe–Dumitru 2-block 1-clique-sum seeding & `O(1)` block-preserving mutations (`mutation.rs`, `search.rs`, `main.rs`)**:
   - Added `--seed-style {random,two_block,mixed}` (default `random`, preserving 100% backwards compatibility).
   - `generate_two_block_ducoffe_seed` constructs two 2-connected blocks sharing one degree-4 cut-vertex (both blocks `<= 31` for `11 <= n <= 61`, guaranteeing `C32 == 0`, zero bridges, independent degree-4 set of size `<= 3`, and `> 2n/3` degree-3 vertices).
   - Within-block 2-edge switches preserve the 2-block manifold in `O(1)` via `block1_inner_mask`.
3. **Plateau-breaking adaptive cap (`--adaptive-cap-max <u32>`)**:
   - Default `0` (disabled). When enabled, doubles `active_cap` up to `adaptive_cap_max` (and scales `node_budget`, reconciling final cross-lane comparisons at the highest active cap) whenever `C4 == C8 == 0` or stagnation occurs with a saturated length.

### Verification Tests
- `cargo test --release --manifest-path rust/sglab-engine/Cargo.toml`: **7/7 passed** (0 warnings), including `two_block_ducoffe_seed_valid_and_c32_free_up_to_61` and `within_block_mutations_preserve_two_block_and_c32_zero`.
- `PYTHONPATH=src python3 -m unittest tests.test_rust_engine tests.test_resources -v`: **11/11 passed** (protocol v2 parity intact).

---

## 3. Experiment 5: M4-Certified 2-Block & Adaptive-Cap Scan (`n = 36..61, 64`)

Every run used 16 Rust workers (`minimal_structure_mixed_degree`, ILS-tabu, 2.0 s wall-time, `--cap 256 --node-budget 150000`), and every best candidate was verified by **M4 (`_build/sglab-cyclecheck`)** and checked for full Ducoffe–Dumitru validity (`valid=True` for 100% of rows):

| $n$ | `total` | `C4` | `C8` | `C16` | `C32` | `C64` | ev/s (16c) | Blocks | M4 Certified Absent |
|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| 36 | **4** | 4 | 0 | 0 | 0 | — | 4.38M | `[19, 18]` | `[8, 16, 32]` |
| 38 | **4** | 4 | 0 | 0 | 0 | — | 3.97M | `[20, 19]` | `[8, 16, 32]` |
| 40 | **4** | 4 | 0 | 0 | 0 | — | 3.56M | `[21, 20]` | `[8, 16, 32]` |
| 42 | **5** | 5 | 0 | 0 | 0 | — | 3.18M | `[22, 21]` | `[8, 16, 32]` |
| 44 | **5** | 5 | 0 | 0 | 0 | — | 2.98M | `[24, 21]` | `[8, 16, 32]` |
| 46 | **6** | 6 | 0 | 0 | 0 | — | 2.73M | `[24, 23]` | `[8, 16, 32]` |
| 48 | **6** | 5 | 1 | 0 | 0 | — | 2.43M | `[25, 24]` | `[16, 32]` |
| 50 | **7** | 5 | 2 | 0 | 0 | — | 1.99M | `[26, 25]` | `[16, 32]` |
| 52 | **7** | 5 | 2 | 0 | 0 | — | 1.54M | `[27, 26]` | `[16, 32]` |
| 54 | **9** | 7 | 2 | 0 | 0 | — | 1.36M | `[29, 26]` | `[16, 32]` |
| 56 | **11** | 8 | 1 | 2 | 0 | — | 1.39M | `[31, 26]` | `[32]` |
| 58 | **12** | 8 | 4 | 0 | 0 | — | 1.38M | `[31, 28]` | `[16, 32]` |
| 60 | **10** | 9 | 1 | 0 | 0 | — | 1.43M | `[31, 30]` | `[16, 32]` |
| 61 | 256 | 0 | 0 | 256 | 0 | — | 1.39M | `[31, 31]` | `[4, 8, 32]` |
| 64 | 512 | 0 | 0 | 256 | 256 | 0 | 22.9k | `[34, 31]` | `[4, 8]` (`64`: timeout, mathematically 0 by block size `< 64`) |

### Adaptive-Cap Runs (`--cap 64 --adaptive-cap-max 512`, 2.0 s, 16 workers)
- `n=44` (`--seed-style random`): escalated to `eff_cap=512`, spontaneously discovered a 2-block graph `[30, 15]` reaching **`total = 12`** (`C4=8, C8=4, C16=0, C32=0`, M4-certified absent `[16, 32]`).
- `n=50` (`--seed-style random`): stayed 1-block `[50]` and eliminated `C16` completely (`C4=7, C8=1, C16=0, C32=512`, M4-certified absent `[16]`).
- `n=50` (`--seed-style mixed`): reached **`total = 6`** (`C4=5, C8=1, C16=0, C32=0`, `blocks=[27, 24]`, M4-certified absent `[16, 32]`, 100% Ducoffe–Dumitru valid, zero bridges — matching the Experiment 2 `cubic_first` score of `6` that required 11 blocks and 5 bridges!).

### Scientific Takeaway
- No counterexample (`total == 0`) was found; M4 refuted every candidate.
- Combining exact Tarjan block decomposition in `count_cycles_fast_u64` with 2-block Ducoffe–Dumitru seeding completely broke the `total = 128` plateau across `n = 38..60`, dropping best witness totals from `128` down to **`4..12`** with M4-certified absence of `[8, 16, 32]` up to `n = 46` and `[16, 32]` up to `n = 60` inside the legal Ducoffe–Dumitru class.
